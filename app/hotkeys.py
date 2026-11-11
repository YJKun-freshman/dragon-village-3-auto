# -*- coding: utf-8 -*-
"""
全域熱鍵（Windows RegisterHotKey）。在自己的執行緒跑訊息迴圈，
遊戲在其他桌面、程式視窗沒有焦點時也有效。

RegisterHotKey 只能在「建立它的執行緒」取消，所以重新註冊、暫停都排進熱鍵執行緒裡做
（PostThreadMessage 喚醒訊息迴圈）。
"""
import logging
import queue
import sys
import threading

log = logging.getLogger("app")

MOD_ALT, MOD_CTRL, MOD_SHIFT = 0x0001, 0x0002, 0x0004
MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
WM_APP_CMD = 0x8000 + 1          # WM_APP + 1：有指令要處理

DEFAULT = {"start": "F5", "stop": "F6"}
NAMES = {"start": "開始", "stop": "停止"}


# ---------------------------------------------------------------- 格式與規則
def normalize(text):
    """
    檢查並整理熱鍵文字。回傳 (標準寫法, None) 或 (None, 中文錯誤原因)。
    規則（和 ui 一致，見 02_Tkinter外型.md）：
      - F1～F24 可以單獨用；字母、數字至少要有 Ctrl 或 Alt（只有 Shift 不行）
      - 修飾鍵順序固定 Ctrl+Alt+Shift+鍵
    """
    parts = [p.strip() for p in str(text or "").split("+") if p.strip()]
    if not parts:
        return None, "沒有設定按鍵"
    mods = set()
    for p in parts[:-1]:
        q = p.lower()
        if q in ("ctrl", "control"):
            mods.add("Ctrl")
        elif q == "alt":
            mods.add("Alt")
        elif q == "shift":
            mods.add("Shift")
        else:
            return None, f"看不懂「{p}」，修飾鍵只能用 Ctrl、Alt、Shift"
    k = parts[-1].strip()
    ku = k.upper()
    if ku.startswith("F") and ku[1:].isdigit() and 1 <= int(ku[1:]) <= 24:
        key, is_f = ku, True
    elif len(k) == 1 and k.isascii() and k.isalnum():
        key, is_f = ku, False
    else:
        return None, f"不支援「{k}」，請用 F1～F24、英文字母或數字"
    if not is_f and not ({"Ctrl", "Alt"} & mods):
        return None, f"「{key}」要搭配 Ctrl 或 Alt（只有 Shift 會擋到打字）"
    order = [m for m in ("Ctrl", "Alt", "Shift") if m in mods]
    return "+".join(order + [key]), None


def parse(text):
    """標準寫法 → (mods, vk)；不合規則回傳 None。"""
    norm, err = normalize(text)
    if err:
        return None
    *mods, key = norm.split("+")
    m = (MOD_CTRL if "Ctrl" in mods else 0) | (MOD_ALT if "Alt" in mods else 0) | \
        (MOD_SHIFT if "Shift" in mods else 0)
    vk = 0x70 + int(key[1:]) - 1 if key.startswith("F") and len(key) > 1 else ord(key)
    return m, vk


def validate_pair(start, stop):
    """回傳 ({"start", "stop"} 標準寫法, None) 或 (None, 中文錯誤原因)。"""
    out = {}
    for name, text in (("start", start), ("stop", stop)):
        norm, err = normalize(text)
        if err:
            return None, f"{NAMES[name]}熱鍵：{err}"
        out[name] = norm
    if out["start"] == out["stop"]:
        return None, "開始和停止不能用同一個鍵"
    return out, None


# ---------------------------------------------------------------- 執行緒
class HotkeyThread:
    """keys = {"start": "F5", "stop": "F6"}；callbacks = {"start": fn, "stop": fn}"""

    def __init__(self, keys, callbacks):
        self.keys = dict(keys)
        self.callbacks = dict(callbacks)
        self.paused = False
        self._ids = {}                  # id -> name（已註冊的）
        self._cmds = queue.Queue()
        self._thread = None
        self._tid = None
        self._ready = threading.Event()
        self._u = None

    # ---- 外部呼叫（任何執行緒）
    def start(self):
        if sys.platform != "win32":
            return
        self._thread = threading.Thread(target=self._loop, name="hotkeys", daemon=True)
        self._thread.start()
        self._ready.wait(2)

    def stop(self):
        if self._tid:
            import ctypes
            ctypes.WinDLL("user32").PostThreadMessageW(self._tid, WM_QUIT, 0, 0)

    def set_keys(self, keys):
        """換熱鍵。回傳 (ok, 訊息)。失敗時保留原本的熱鍵。暫停中也會先試註冊確認沒被佔用。"""
        return self._run(lambda: self._set_keys(dict(keys)))

    def pause(self, paused):
        """暫停（ui 錄製熱鍵時）或恢復。"""
        return self._run(lambda: self._pause(bool(paused)))

    def _run(self, fn, timeout=2.0):
        if not self._tid:                          # 不是 Windows / 還沒啟動：只改設定
            return fn() if sys.platform != "win32" else (False, "熱鍵功能沒有啟動")
        done, box = threading.Event(), {}

        def job():
            try:
                box["r"] = fn()
            except Exception as e:                 # noqa: BLE001
                log.debug("熱鍵指令失敗", exc_info=True)
                box["r"] = (False, f"熱鍵設定失敗：{e}")
            done.set()

        self._cmds.put(job)
        import ctypes
        ctypes.WinDLL("user32").PostThreadMessageW(self._tid, WM_APP_CMD, 0, 0)
        if not done.wait(timeout):
            return False, "熱鍵設定沒有回應"
        return box["r"]

    # ---- 熱鍵執行緒內
    def _register_all(self, keys):
        """全部註冊；有任何一個失敗就全部取消。回傳 None 或失敗的 name。"""
        ids = {}
        for i, name in enumerate(("start", "stop"), 1):
            pk = parse(keys.get(name))
            if not pk or not self._u.RegisterHotKey(None, i, pk[0] | MOD_NOREPEAT, pk[1]):
                for hid in ids:
                    self._u.UnregisterHotKey(None, hid)
                return name
            ids[i] = name
        self._ids = ids
        return None

    def _unregister_all(self):
        for hid in self._ids:
            self._u.UnregisterHotKey(None, hid)
        self._ids = {}

    def _set_keys(self, keys):
        if not self._u:                             # 非 Windows（測試用）
            self.keys = keys
            return True, "已套用"
        old = dict(self.keys)
        self._unregister_all()
        bad = self._register_all(keys)
        if bad:
            self._register_all(old) if not self.paused else None
            return False, f"「{keys[bad]}」被其他程式佔用了，請換一個鍵"
        self.keys = keys
        if self.paused:
            self._unregister_all()                  # 只是確認能註冊，恢復時才真的啟用
        return True, "已套用"

    def _pause(self, paused):
        if self._u and paused != self.paused:
            if paused:
                self._unregister_all()
            else:
                bad = self._register_all(self.keys)
                if bad:
                    log.warning("熱鍵 %s 註冊失敗（被其他程式佔用），請在設定裡換一個鍵", self.keys[bad])
        self.paused = paused
        return True, "已暫停" if paused else "已恢復"

    def _loop(self):
        import ctypes
        import ctypes.wintypes as wt
        u = ctypes.WinDLL("user32", use_last_error=True)
        u.RegisterHotKey.argtypes = [wt.HWND, ctypes.c_int, wt.UINT, wt.UINT]
        u.UnregisterHotKey.argtypes = [wt.HWND, ctypes.c_int]
        u.GetMessageW.argtypes = [ctypes.POINTER(wt.MSG), wt.HWND, wt.UINT, wt.UINT]
        u.PeekMessageW.argtypes = [ctypes.POINTER(wt.MSG), wt.HWND, wt.UINT, wt.UINT, wt.UINT]
        self._u = u
        msg = wt.MSG()
        u.PeekMessageW(ctypes.byref(msg), None, 0, 0, 0)     # 建立訊息佇列，之後才收得到 PostThreadMessage
        self._tid = ctypes.WinDLL("kernel32").GetCurrentThreadId()
        bad = self._register_all(self.keys)
        if bad:
            log.warning("熱鍵 %s 註冊失敗（格式錯誤或被其他程式佔用），請到設定換一個鍵，或用介面上的按鈕", self.keys[bad])
        self._ready.set()
        try:
            while u.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == WM_HOTKEY and msg.wParam in self._ids:
                    cb = self.callbacks.get(self._ids[msg.wParam])
                    try:
                        cb and cb()
                    except Exception:
                        log.exception("熱鍵處理失敗")
                elif msg.message == WM_APP_CMD:
                    while True:
                        try:
                            self._cmds.get_nowait()()
                        except queue.Empty:
                            break
        finally:
            self._unregister_all()
