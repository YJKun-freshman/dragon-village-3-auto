# -*- coding: utf-8 -*-
"""
背景點擊：對 CROSVM_1 子視窗 PostMessage 滑鼠訊息，不移動真實滑鼠。
這裡的座標都是「子視窗座標（像素）」，比例座標的換算在 game.py。
"""
import time

from . import _win32 as w

FRAME_STEP = 0.016   # 拖曳時每一步的間隔（約 60fps）


def _lp(x, y):
    return ((int(y) & 0xFFFF) << 16) | (int(x) & 0xFFFF)


def _post(hwnd, msg, wp, x, y):
    if not w.user32.PostMessageW(hwnd, msg, wp, _lp(x, y)):
        raise OSError("送出滑鼠訊息失敗（遊戲視窗可能已關閉）")


def _wait(seconds, stop=None):
    """可被中斷的等待。回傳 True = 被要求停止。"""
    if seconds <= 0:
        return stop is not None and stop.is_set()
    if stop is None:
        time.sleep(seconds)
        return False
    return stop.wait(seconds)


def mouse_down(hwnd, x, y):
    _post(hwnd, w.WM_MOUSEMOVE, 0, x, y)
    time.sleep(0.02)
    _post(hwnd, w.WM_LBUTTONDOWN, w.MK_LBUTTON, x, y)


def mouse_up(hwnd, x, y):
    _post(hwnd, w.WM_LBUTTONUP, 0, x, y)


def click(hwnd, x, y, hold=0.08):
    """座標是子視窗的實際像素（game.to_client 已處理縮放換算）。"""
    mouse_down(hwnd, x, y)
    time.sleep(hold)
    mouse_up(hwnd, x, y)


def long_press(hwnd, x, y, seconds, stop=None):
    """長按。被停止時也一定會放開按鍵。"""
    mouse_down(hwnd, x, y)
    try:
        _wait(seconds, stop)
    finally:
        mouse_up(hwnd, x, y)


def drag(hwnd, x0, y0, x1, y1, seconds=0.3, hold_start=0.05, hold_end=0.05, stop=None):
    """按住 → 平滑移動 → 放開。"""
    steps = max(2, int(seconds / FRAME_STEP))
    mouse_down(hwnd, x0, y0)
    x, y = x0, y0
    try:
        if _wait(hold_start, stop):
            return
        for i in range(1, steps + 1):
            t = i / steps
            t = t * t * (3 - 2 * t)          # 頭尾慢、中間快
            x = x0 + (x1 - x0) * t
            y = y0 + (y1 - y0) * t
            _post(hwnd, w.WM_MOUSEMOVE, w.MK_LBUTTON, x, y)
            if _wait(seconds / steps, stop):
                return
        _wait(hold_end, stop)
    finally:
        mouse_up(hwnd, x, y)


def wheel(hwnd, x, y, notches, interval=0.05, stop=None):
    """
    滾輪。notches > 0 往上（通常是放大）、< 0 往下（通常是縮小），1 格 = 120。
    WM_MOUSEWHEEL 的座標是「螢幕座標」，所以要先換算。
    """
    import ctypes
    p = w.wt.POINT(0, 0)
    w.user32.ClientToScreen(hwnd, ctypes.byref(p))     # 實際像素（x, y 也是實際像素）
    sx, sy = p.x + int(x), p.y + int(y)
    _post(hwnd, w.WM_MOUSEMOVE, 0, x, y)
    step = 1 if notches > 0 else -1
    for _ in range(abs(int(notches))):
        wp = ((w.WHEEL_DELTA * step) & 0xFFFF) << 16
        _post(hwnd, w.WM_MOUSEWHEEL, wp, sx, sy)
        if _wait(interval, stop):
            return


# ---------------------------------------------------------------- 鍵盤（core v0.3.0，由「釣魚」對話新增）
VK = {
    "shift": 0x10, "ctrl": 0x11, "alt": 0x12, "tab": 0x09, "enter": 0x0D,
    "esc": 0x1B, "space": 0x20, "back": 0x08,
    "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
}


def _key_lp(vk, up):
    scan = w.user32.MapVirtualKeyW(vk, 0) & 0xFF      # MAPVK_VK_TO_VSC
    lp = 1 | (scan << 16)
    if up:
        lp |= (1 << 30) | (1 << 31)
    return lp


def key(hwnd, *names, hold=0.05):
    """
    背景按鍵：對子視窗 PostMessage WM_KEYDOWN / WM_KEYUP，不影響真實鍵盤。
    names 依序按下、反序放開，例：key(hwnd, "shift", "tab") = Shift+Tab。
    單一字母／數字也可以：key(hwnd, "a")。
    """
    vks = []
    for n in names:
        n = str(n).lower()
        if n in VK:
            vks.append(VK[n])
        elif len(n) == 1 and n.isalnum():
            vks.append(ord(n.upper()))
        else:
            raise ValueError(f"不支援的按鍵：{n}")
    try:
        for vk in vks:
            if not w.user32.PostMessageW(hwnd, w.WM_KEYDOWN, vk, _key_lp(vk, False)):
                raise OSError("送出按鍵失敗（遊戲視窗可能已關閉）")
            time.sleep(0.02)
        time.sleep(hold)
    finally:
        for vk in reversed(vks):
            w.user32.PostMessageW(hwnd, w.WM_KEYUP, vk, _key_lp(vk, True))
            time.sleep(0.02)
