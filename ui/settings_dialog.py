# -*- coding: utf-8 -*-
"""
設定視窗：熱鍵、遊戲視窗、其他（日誌資料夾、版本）。約定見 02_Tkinter外型.md「設定選單（定案）」。

    settings = {
        "hotkeys": {"start", "stop"}, "default_hotkeys": {"start", "stop"},
        "set_hotkeys": fn(start, stop) -> (ok, 訊息), "pause_hotkeys": fn(paused) -> (ok, 訊息),
        "list_windows": fn() -> [{"id", "title"}], "current_window": fn() -> id | None,
        "select_window": fn(id) -> (ok, 訊息),
    }
沒給的項目，對應的區塊就不顯示。
"""
import logging
import sys
import tkinter as tk

import customtkinter as ctk

from .theme import C, F, L, M, S, XL, XS, RADIUS, Box, card, label, outline_button, primary_button
from .widgets import Tooltip

log = logging.getLogger("ui")

DEFAULT_HOTKEYS = {"start": "F5", "stop": "F6"}
NAMES = {"start": "開始", "stop": "停止"}
MOD_KEYSYMS = {"Shift_L", "Shift_R", "Control_L", "Control_R", "Alt_L", "Alt_R", "Meta_L", "Meta_R",
               "Super_L", "Super_R", "Win_L", "Win_R", "Caps_Lock", "Num_Lock", "ISO_Level3_Shift"}


# ================================================================== 熱鍵規則（和 app/hotkeys.py 一致）
def normalize(text):
    """(標準寫法, "") 或 (None, 中文錯誤原因)。F1～F24 可單獨用；字母、數字要有 Ctrl 或 Alt；順序 Ctrl+Alt+Shift+鍵。"""
    parts = [p.strip() for p in str(text or "").split("+") if p.strip()]
    if not parts:
        return None, "沒有設定按鍵"
    mods = set()
    for p in parts[:-1]:
        q = p.lower()
        if q in ("ctrl", "control"):
            mods.add("Ctrl")
        elif q in ("alt", "shift"):
            mods.add(q.capitalize())
        else:
            return None, f"看不懂「{p}」"
    k = parts[-1].upper()
    is_f = k.startswith("F") and k[1:].isdigit() and 1 <= int(k[1:]) <= 24
    if not is_f and not (len(k) == 1 and k.isascii() and k.isalnum()):
        return None, f"不支援「{parts[-1]}」，請用 F1～F24、英文字母或數字"
    if not is_f and not ({"Ctrl", "Alt"} & mods):
        return None, f"「{k}」要搭配 Ctrl 或 Alt（只有 Shift 會擋到打字）"
    return "+".join([m for m in ("Ctrl", "Alt", "Shift") if m in mods] + [k]), ""


def tk_sequence(hotkey):
    """標準寫法 → Tk 的按鍵事件（視窗有焦點時也能用）。例：Ctrl+F5 → <Control-KeyPress-F5>"""
    norm, err = normalize(hotkey)
    if err:
        return None
    *mods, key = norm.split("+")
    tkmods = [{"Ctrl": "Control", "Alt": "Alt", "Shift": "Shift"}[m] for m in mods]
    if len(key) == 1 and key.isalpha():
        key = key if "Shift" in mods else key.lower()
    return "<" + "-".join(tkmods + ["KeyPress", key]) + ">"


def _event_to_hotkey(e):
    """按鍵事件 → (標準寫法或 None, 顯示用文字)。"""
    mods = []
    st = e.state
    if st & 0x4:
        mods.append("Ctrl")
    if st & (0x20000 if sys.platform == "win32" else 0x8):
        mods.append("Alt")
    if st & 0x1:
        mods.append("Shift")
    key = None
    kc = getattr(e, "keycode", 0)
    if sys.platform == "win32" and kc:                 # Windows：用虛擬鍵碼，不受 Shift 影響
        if 0x70 <= kc <= 0x87:
            key = f"F{kc - 0x6F}"
        elif 0x30 <= kc <= 0x39 or 0x41 <= kc <= 0x5A:
            key = chr(kc)
    if key is None:
        ks = e.keysym or ""
        if ks.upper().startswith("F") and ks[1:].isdigit():
            key = ks.upper()
        elif len(ks) == 1 and ks.isascii() and ks.isalnum():
            key = ks.upper()
    return key, mods


# ================================================================== 熱鍵錄製框
class HotkeyField:
    def __init__(self, master, value, on_change):
        self.value = value
        self.on_change = on_change
        self.recording = False
        self.enabled = True
        self.frame = ctk.CTkFrame(master, fg_color=C["input"], border_color=C["border"], border_width=1,
                                  corner_radius=RADIUS, height=36)
        self.frame.grid_propagate(False)
        self.frame.pack_propagate(False)
        self.inner = Box(self.frame, "input")
        self.inner.pack(side="left", fill="both", expand=True, padx=(10, 4), pady=4)
        for w in (self.frame, self.inner):
            w.bind("<Button-1>", lambda e: self.start())
        # CTkFrame.bind 會綁在內部畫布上，鍵盤事件要綁在真正拿到焦點的 tk.Frame（inner）
        self.inner.configure(takefocus=1)
        self.inner.bind("<KeyPress>", self._key)
        self.inner.bind("<FocusOut>", lambda e: self.stop(cancel=True))
        self._render()

    def _render(self):
        for c in self.inner.winfo_children():
            c.destroy()
        if self.recording:
            t = label(self.inner, "請按下按鍵組合…（Esc 取消）", F.small, "accent_text")
            t.pack(side="left")
            t.bind("<Button-1>", lambda e: "break")
            return
        parts = (self.value or "").split("+") if self.value else []
        if not parts:
            t = label(self.inner, "（未設定）", F.small, "faint")
            t.pack(side="left")
            t.bind("<Button-1>", lambda e: self.start())
        for p in parts:
            chip = ctk.CTkLabel(self.inner, text=p, font=F.small, fg_color="#2F2F2F",
                                text_color=C["text"] if self.enabled else C["faint"],
                                corner_radius=4, height=22, width=10)
            chip.pack(side="left", padx=(0, 4))
            chip.bind("<Button-1>", lambda e: self.start())

    def _paint(self):
        self.frame.configure(border_color=C["accent"] if self.recording else C["border"],
                             border_width=2 if self.recording else 1)

    def start(self):
        if not self.enabled or self.recording:
            return
        self.recording = True
        self._paint()
        self._render()
        self.inner.focus_set()

    def stop(self, cancel=False):
        if not self.recording:
            return
        self.recording = False
        self._paint()
        self._render()
        if not cancel:
            self.on_change()

    def _key(self, e):
        if not self.recording:
            return
        if e.keysym == "Escape":
            self.stop(cancel=True)
            return "break"
        if e.keysym in MOD_KEYSYMS:          # 只按修飾鍵：繼續等
            return "break"
        key, mods = _event_to_hotkey(e)
        if key is None:
            self.on_change(error=f"不支援這個按鍵（{e.keysym}），請用 F1～F24、英文字母或數字")
            return "break"
        norm, err = normalize("+".join(mods + [key]))
        if err:
            self.on_change(error=err)
            return "break"
        self.value = norm
        self.stop()
        self.frame.master.focus_set()
        return "break"

    def set(self, value):
        self.value = value
        self._render()

    def set_enabled(self, on):
        self.enabled = on
        if not on:
            self.stop(cancel=True)
        self._render()


# ================================================================== 設定視窗
class SettingsDialog:
    def __init__(self, main, settings, running, on_open_logs=None, version_text=""):
        """main：MainWindow；settings：約定的 dict（可以是空的）"""
        self.main = main
        self.s = settings or {}
        self.running = running
        self.paused = False
        self.closed = False

        root = main.root
        w = self.win = ctk.CTkToplevel(root, fg_color=C["bg"])
        w.title("設定")
        w.resizable(False, False)
        w.transient(root)
        w.protocol("WM_DELETE_WINDOW", self.cancel)
        w.bind("<Escape>", lambda e: self.cancel() if not self._any_recording() else None)

        body = Box(w, "bg")
        body.pack(fill="both", expand=True, padx=XL, pady=(L + XS, L))
        body.grid_columnconfigure(0, weight=1)
        row = 0

        # ---- 熱鍵
        self.hk_fields = {}
        self.has_hotkeys = "set_hotkeys" in self.s
        if self.has_hotkeys:
            sec = self._section(body, row, "熱鍵")
            row += 1
            self.reset_btn = outline_button(sec.head, "還原預設", self._reset_hotkeys, width=76, height=26)
            self.reset_btn.pack(side="right")
            self.hk_note = label(sec.body, "", F.small, "accent_text", anchor="w")
            cur = dict(DEFAULT_HOTKEYS)
            cur.update(getattr(main, "hotkeys", None) or self.s.get("hotkeys") or {})   # 用目前的（改過會更新）
            self.orig_hotkeys = {k: normalize(v)[0] or v for k, v in cur.items()}
            for i, name in enumerate(("start", "stop")):
                label(sec.body, NAMES[name], F.body).grid(row=i + 1, column=0, sticky="w", pady=(0, S))
                f = HotkeyField(sec.body, self.orig_hotkeys[name], self._hotkey_changed)
                f.frame.grid(row=i + 1, column=1, sticky="ew", pady=(0, S), padx=(M, 0))
                self.hk_fields[name] = f
            self.hk_err = label(sec.body, "", F.small, "err", anchor="w", justify="left")
            self.hk_err.grid(row=3, column=0, columnspan=2, sticky="w")
            self.hk_err.grid_remove()
            label(sec.body, "點一下框框，再按想要的按鍵。F1～F12 可以單獨用；\n其他鍵要搭配 Ctrl 或 Alt。遊戲在別的桌面時也有效。",
                  F.small, "sub", anchor="w", justify="left").grid(row=4, column=0, columnspan=2, sticky="w", pady=(XS, 0))

        # ---- 遊戲視窗
        self.has_windows = "list_windows" in self.s and "select_window" in self.s
        self.win_var = tk.StringVar(value="")
        if self.has_windows:
            sec = self._section(body, row, "遊戲視窗")
            row += 1
            self.refresh_btn = outline_button(sec.head, "⟳ 重新整理", self._load_windows, width=86, height=26)
            self.refresh_btn.pack(side="right")
            self.win_note = label(sec.body, "", F.small, "accent_text", anchor="w")
            self.win_list = Box(sec.body, "panel")
            self.win_list.grid(row=1, column=0, columnspan=2, sticky="ew")
            self.win_list.grid_columnconfigure(0, weight=1)
            self.win_err = label(sec.body, "", F.small, "err", anchor="w", justify="left")
            self.win_err.grid(row=2, column=0, columnspan=2, sticky="w")
            self.win_err.grid_remove()
            label(sec.body, "有多個遊戲視窗時，選要操作的那一個。", F.small, "sub", anchor="w").grid(
                row=3, column=0, columnspan=2, sticky="w", pady=(XS, 0))
            self.orig_window = None
            self._load_windows(first=True)

        # ---- 其他
        sec = self._section(body, row, "其他")
        row += 1
        r = 0
        if on_open_logs:
            label(sec.body, "日誌資料夾", F.body).grid(row=r, column=0, sticky="w", pady=(0, S))
            outline_button(sec.body, "開啟", lambda: self._safe(on_open_logs), width=56, height=28).grid(
                row=r, column=1, sticky="e", pady=(0, S))
            r += 1
        label(sec.body, "版本", F.body).grid(row=r, column=0, sticky="w")
        label(sec.body, version_text, F.small, "sub").grid(row=r, column=1, sticky="e")

        # ---- 按鈕
        foot = Box(w, "panel")
        foot.pack(fill="x", side="bottom")
        Box(foot, "border", height=1).pack(fill="x", side="top")
        btns = Box(foot, "panel")
        btns.pack(fill="x", padx=XL, pady=M)
        self.apply_btn = primary_button(btns, "套用", self.apply, width=88, height=34)
        self.apply_btn.pack(side="right")
        outline_button(btns, "取消", self.cancel, width=72, height=34, font=F.body_bold).pack(side="right", padx=(0, S))
        foot.pack_forget()
        foot.pack(fill="x", side="bottom", before=body)

        self.set_running(running)
        w.after(10, self._show)

    # ---------------------------------------------------------------- 外框
    def _section(self, master, row, title):
        c = card(master)
        c.grid(row=row, column=0, sticky="ew", pady=(0, M))
        c.grid_columnconfigure(0, weight=1)
        head = Box(c, "panel")
        head.grid(row=0, column=0, sticky="ew", padx=(L, M), pady=(M, S))
        label(head, title, F.section, "sub").pack(side="left")
        body = Box(c, "panel")
        body.grid(row=1, column=0, sticky="ew", padx=L, pady=(0, M + XS))
        body.grid_columnconfigure(0, minsize=70)
        body.grid_columnconfigure(1, weight=1)
        c.head, c.body = head, body
        return c

    def _show(self):
        w, root = self.win, self.main.root
        w.minsize(500, 200)               # 只給最小寬度，高度跟著內容（出現錯誤訊息時會自動長高）
        w.update_idletasks()
        sc = self.main.scale
        ww = max(500, w.winfo_reqwidth() / sc)
        x = root.winfo_rootx() / sc + (root.winfo_width() / sc - ww) / 2
        y = root.winfo_rooty() / sc + 60
        w.geometry(f"+{int(max(0, x))}+{int(max(0, y))}")
        w.lift()
        w.focus_force()
        w.after(150, self._grab)

    def _grab(self):
        try:
            self.win.grab_set()
        except tk.TclError:
            pass

    def _safe(self, fn, *args, default=(False, "")):
        try:
            return fn(*args)
        except Exception as e:
            log.exception("設定回呼失敗")
            return (False, f"發生錯誤：{e}") if default is not None else None

    # ---------------------------------------------------------------- 熱鍵
    def _any_recording(self):
        return any(f.recording for f in self.hk_fields.values())

    def _pause(self, on):
        if "pause_hotkeys" not in self.s or self.paused == on:
            return
        res = self._safe(self.s["pause_hotkeys"], on)
        self.paused = on
        if isinstance(res, tuple) and not res[0] and res[1]:
            self.main.append_log(res[1], "warn")

    def _hotkey_changed(self, error=""):
        if error:
            self._hk_error(error)
            return
        a, b = self.hk_fields["start"].value, self.hk_fields["stop"].value
        self._hk_error("開始和停止不能用同一個鍵" if a and a == b else "")

    def _hk_error(self, msg):
        if msg:
            self.hk_err.configure(text=msg)
            self.hk_err.grid()
        else:
            self.hk_err.grid_remove()
        self._refresh_apply()

    def _reset_hotkeys(self):
        d = dict(DEFAULT_HOTKEYS)
        d.update(self.s.get("default_hotkeys") or {})
        for name, f in self.hk_fields.items():
            f.set(normalize(d[name])[0] or d[name])
        self._hotkey_changed()

    def _hotkeys_dirty(self):
        return self.has_hotkeys and any(self.hk_fields[n].value != self.orig_hotkeys[n] for n in self.hk_fields)

    # ---------------------------------------------------------------- 遊戲視窗
    def _load_windows(self, first=False):
        for c in self.win_list.winfo_children():
            c.destroy()
        items = self._safe(self.s["list_windows"], default=None) or []
        cur = self._safe(self.s["current_window"], default=None) if "current_window" in self.s else None
        if first:
            self.orig_window = cur
            self.win_var.set("" if cur is None else str(cur))
        elif self.win_var.get() not in {str(it.get("id")) for it in items}:
            self.win_var.set("" if cur is None else str(cur))
        if not items:
            label(self.win_list, "找不到遊戲視窗（請先開啟遊戲，再按「重新整理」）", F.small, "sub").grid(
                row=0, column=0, sticky="w", pady=(0, S))
        for i, it in enumerate(items):
            title = str(it.get("title", ""))
            name = title.split(" - ", 1)[1] if " - " in title else title
            row = Box(self.win_list, "panel")
            row.grid(row=i, column=0, sticky="ew", pady=(0, 2))
            row.grid_columnconfigure(1, weight=1)
            rb = ctk.CTkRadioButton(row, text=name or "（沒有名稱）", value=str(it.get("id")), variable=self.win_var,
                                    font=F.body, text_color=C["text"], text_color_disabled=C["faint"],
                                    fg_color=C["accent"], hover_color=C["accent_hover"], border_color=C["sub"],
                                    radiobutton_width=16, radiobutton_height=16, border_width_unchecked=2,
                                    border_width_checked=5, command=self._refresh_apply)
            rb.grid(row=0, column=0, sticky="w", pady=4)
            if title and name != title:
                Tooltip(rb, title)
            if it.get("id") == cur:
                label(row, "● 目前連接", F.small, "ok").grid(row=0, column=1, sticky="e")
            rb.configure(state="disabled" if self.running else "normal")
        self._refresh_apply()

    def _window_dirty(self):
        return self.has_windows and self.win_var.get() and self.win_var.get() != (
            "" if self.orig_window is None else str(self.orig_window))

    # ---------------------------------------------------------------- 狀態
    def set_running(self, running):
        self.running = running
        if self.has_hotkeys:
            for f in self.hk_fields.values():
                f.set_enabled(not running)
            self.reset_btn.configure(state="disabled" if running else "normal")
            self._note(self.hk_note, running)
            if not running:
                self._pause(True)       # 錄熱鍵時暫停全域熱鍵（執行中不暫停，F6 停止要能用）
        if self.has_windows:
            self.refresh_btn.configure(state="disabled" if running else "normal")
            self._note(self.win_note, running)
            for row in self.win_list.winfo_children():
                for c in row.winfo_children():
                    if isinstance(c, ctk.CTkRadioButton):
                        c.configure(state="disabled" if running else "normal")
        self._refresh_apply()

    def _note(self, lbl, on):
        if on:
            lbl.configure(text="執行中不能修改，請先停止任務")
            lbl.grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, S))
        else:
            lbl.grid_remove()

    def _refresh_apply(self):
        if not hasattr(self, "apply_btn"):
            return
        bad = self.has_hotkeys and self.hk_err.winfo_manager() != ""
        can = not self.running and not bad and (self._hotkeys_dirty() or self._window_dirty())
        self.apply_btn.configure(state="normal" if can else "disabled",
                                 fg_color=C["accent"] if can else C["accent_dim"])

    # ---------------------------------------------------------------- 套用／取消
    def apply(self):
        if self.running:
            return
        if self._hotkeys_dirty():
            a, b = self.hk_fields["start"].value, self.hk_fields["stop"].value
            ok, msg = self._safe(self.s["set_hotkeys"], a, b) or (False, "")
            if not ok:
                self._hk_error(msg or "熱鍵設定失敗")
                return
            self.orig_hotkeys = {"start": a, "stop": b}
            self.main.set_hotkey_labels(a, b)        # 主程式也會呼叫；先更新不用等
        if self._window_dirty():
            target = next((it for it in (self._safe(self.s["list_windows"], default=None) or [])
                           if str(it.get("id")) == self.win_var.get()), None)
            if target is None:
                self._win_error("這個視窗已經關掉了，請按「重新整理」")
                return
            ok, msg = self._safe(self.s["select_window"], target.get("id")) or (False, "")
            if not ok:
                self._win_error(msg or "切換視窗失敗")
                return
        self.close()

    def _win_error(self, msg):
        self.win_err.configure(text=msg)
        self.win_err.grid()

    def cancel(self):
        self.close()

    def close(self):
        if self.closed:
            return
        self.closed = True
        self._pause(False)
        try:
            self.win.grab_release()
        except tk.TclError:
            pass
        self.win.destroy()
        self.main._settings_closed()
