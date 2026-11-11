# -*- coding: utf-8 -*-
"""找 Google Play 遊戲電腦版（GPG）的遊戲視窗。"""
import os
from dataclasses import dataclass

from . import _win32 as w

GAME_PROCESS = "crosvm.exe"
CHILD_CLASS_PREFIX = "CROSVM"


@dataclass
class GameWindow:
    root: int          # 主視窗（截圖用）
    child: int         # CROSVM_1 子視窗（點擊要送到這裡）
    title: str

    def __str__(self):
        return self.title


def _text(h):
    import ctypes
    b = ctypes.create_unicode_buffer(512)
    w.user32.GetWindowTextW(h, b, 512)
    return b.value


def _class(h):
    import ctypes
    b = ctypes.create_unicode_buffer(256)
    w.user32.GetClassNameW(h, b, 256)
    return b.value


def _proc_name(h):
    import ctypes
    pid = w.wt.DWORD()
    w.user32.GetWindowThreadProcessId(h, ctypes.byref(pid))
    ph = w.kernel32.OpenProcess(0x1000, False, pid.value)   # PROCESS_QUERY_LIMITED_INFORMATION
    if not ph:
        return ""
    try:
        b = ctypes.create_unicode_buffer(1024)
        n = w.wt.DWORD(1024)
        w.kernel32.QueryFullProcessImageNameW(ph, 0, b, ctypes.byref(n))
        return os.path.basename(b.value).lower()
    finally:
        w.kernel32.CloseHandle(ph)


def _find_child(root):
    kids = []

    def cb(h, _):
        if _class(h).startswith(CHILD_CLASS_PREFIX):
            kids.append(h)
        return True

    w.user32.EnumChildWindows(root, w.WNDENUMPROC(cb), 0)
    return kids[0] if kids else None


def list_windows():
    """回傳所有 GPG 遊戲視窗（list[GameWindow]）。非 Windows 系統回傳空清單。"""
    if not w.AVAILABLE:
        return []
    w.set_dpi_awareness()
    roots = []

    def cb(h, _):
        if w.user32.IsWindowVisible(h) and _proc_name(h) == GAME_PROCESS:
            t = _text(h)
            if t:
                roots.append((h, t))
        return True

    w.user32.EnumWindows(w.WNDENUMPROC(cb), 0)
    out = []
    for h, t in roots:
        child = _find_child(h)
        if child:
            out.append(GameWindow(int(h), int(child), t))
    return out


def window_status(gw):
    """(可用?, 原因)"""
    if gw is None:
        return False, "還沒連接遊戲視窗"
    if not w.AVAILABLE:
        return False, "只能在 Windows 上連接遊戲"
    if not w.user32.IsWindow(gw.root) or not w.user32.IsWindow(gw.child):
        return False, "找不到遊戲視窗（遊戲可能被關掉了）"
    if w.user32.IsIconic(gw.root):
        return False, "遊戲視窗被縮到最小，請還原（可以放在其他桌面，但不能縮到最小）"
    return True, ""


def window_exists(gw):
    """視窗還在（不管有沒有縮到最小）。"""
    if gw is None or not w.AVAILABLE:
        return False
    return bool(w.user32.IsWindow(gw.root) and w.user32.IsWindow(gw.child))


def client_size(h):
    r = w.wt.RECT()
    w.user32.GetClientRect(h, r)
    return r.right, r.bottom
