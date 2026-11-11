# -*- coding: utf-8 -*-
"""
Windows API 宣告（ctypes）。只在 Windows 上載入；其他系統 AVAILABLE = False，
讓離線測試模式（用截圖檔代替遊戲）在任何地方都能跑。
"""
import sys

AVAILABLE = sys.platform == "win32"

if AVAILABLE:
    import ctypes
    import ctypes.wintypes as wt

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

    HWND, HDC = wt.HWND, wt.HDC
    WNDENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, HWND, wt.LPARAM)

    def _sig(fn, args, res=None):
        fn.argtypes = args
        if res is not None:
            fn.restype = res

    _sig(user32.EnumWindows, [WNDENUMPROC, wt.LPARAM])
    _sig(user32.EnumChildWindows, [HWND, WNDENUMPROC, wt.LPARAM])
    _sig(user32.IsWindow, [HWND], wt.BOOL)
    _sig(user32.IsWindowVisible, [HWND], wt.BOOL)
    _sig(user32.IsIconic, [HWND], wt.BOOL)
    _sig(user32.GetWindowTextW, [HWND, wt.LPWSTR, ctypes.c_int])
    _sig(user32.GetClassNameW, [HWND, wt.LPWSTR, ctypes.c_int])
    _sig(user32.GetWindowThreadProcessId, [HWND, ctypes.POINTER(wt.DWORD)], wt.DWORD)
    _sig(user32.GetWindowRect, [HWND, ctypes.POINTER(wt.RECT)], wt.BOOL)
    _sig(user32.GetClientRect, [HWND, ctypes.POINTER(wt.RECT)], wt.BOOL)
    _sig(user32.ClientToScreen, [HWND, ctypes.POINTER(wt.POINT)], wt.BOOL)
    _sig(user32.PostMessageW, [HWND, wt.UINT, wt.WPARAM, wt.LPARAM], wt.BOOL)
    _sig(user32.MapVirtualKeyW, [wt.UINT, wt.UINT], wt.UINT)
    _sig(user32.GetDC, [HWND], HDC)
    _sig(user32.ReleaseDC, [HWND, HDC], ctypes.c_int)
    _sig(user32.PrintWindow, [HWND, HDC, wt.UINT], wt.BOOL)
    _sig(kernel32.OpenProcess, [wt.DWORD, wt.BOOL, wt.DWORD], wt.HANDLE)
    _sig(kernel32.QueryFullProcessImageNameW,
         [wt.HANDLE, wt.DWORD, wt.LPWSTR, ctypes.POINTER(wt.DWORD)], wt.BOOL)
    _sig(kernel32.CloseHandle, [wt.HANDLE], wt.BOOL)
    _sig(gdi32.CreateCompatibleDC, [HDC], HDC)
    _sig(gdi32.CreateCompatibleBitmap, [HDC, ctypes.c_int, ctypes.c_int], wt.HBITMAP)
    _sig(gdi32.SelectObject, [HDC, wt.HGDIOBJ], wt.HGDIOBJ)
    _sig(gdi32.DeleteObject, [wt.HGDIOBJ], wt.BOOL)
    _sig(gdi32.DeleteDC, [HDC], wt.BOOL)
    _sig(gdi32.GetDIBits, [HDC, wt.HBITMAP, wt.UINT, wt.UINT, ctypes.c_void_p,
                           ctypes.c_void_p, wt.UINT], ctypes.c_int)

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [("biSize", wt.DWORD), ("biWidth", wt.LONG), ("biHeight", wt.LONG),
                    ("biPlanes", wt.WORD), ("biBitCount", wt.WORD), ("biCompression", wt.DWORD),
                    ("biSizeImage", wt.DWORD), ("biXPelsPerMeter", wt.LONG),
                    ("biYPelsPerMeter", wt.LONG), ("biClrUsed", wt.DWORD),
                    ("biClrImportant", wt.DWORD)]

    WM_ACTIVATE = 0x0006
    WM_KEYDOWN = 0x0100
    WM_KEYUP = 0x0101
    WM_MOUSEMOVE = 0x0200
    WM_LBUTTONDOWN = 0x0201
    WM_LBUTTONUP = 0x0202
    WM_MOUSEWHEEL = 0x020A
    WHEEL_DELTA = 120
    MK_LBUTTON = 0x0001
    PW_RENDERFULLCONTENT = 2

_dpi_done = False


def _opt(name, args, res):
    """Win10 1607 以後才有的 API；沒有就回傳 None。"""
    fn = getattr(user32, name, None) if AVAILABLE else None
    if fn is not None:
        fn.argtypes = args
        fn.restype = res
    return fn


if AVAILABLE:
    _GetWindowDpiAwarenessContext = _opt("GetWindowDpiAwarenessContext", [HWND], ctypes.c_ssize_t)
    _SetThreadDpiAwarenessContext = _opt("SetThreadDpiAwarenessContext", [ctypes.c_ssize_t], ctypes.c_ssize_t)
    _GetAwarenessFromDpiAwarenessContext = _opt("GetAwarenessFromDpiAwarenessContext",
                                                [ctypes.c_ssize_t], ctypes.c_int)
    _GetDpiForWindow = _opt("GetDpiForWindow", [HWND], wt.UINT)


def window_dpi_awareness(hwnd):
    """視窗的 DPI 感知：0 = 不支援縮放（Windows 幫它放大）、1 = 系統、2 = 每個螢幕、-1 = 不明"""
    if not AVAILABLE or not _GetWindowDpiAwarenessContext or not _GetAwarenessFromDpiAwarenessContext:
        return -1
    return _GetAwarenessFromDpiAwarenessContext(_GetWindowDpiAwarenessContext(hwnd))


def window_dpi(hwnd):
    if not AVAILABLE or not _GetDpiForWindow:
        return 96
    return _GetDpiForWindow(hwnd) or 96


def monitor_dpi(hwnd):
    """視窗所在螢幕「實際」的 DPI（縮放 125% = 120）。"""
    if not AVAILABLE:
        return 96
    try:
        user32.MonitorFromWindow.argtypes = [HWND, wt.DWORD]
        user32.MonitorFromWindow.restype = wt.HMONITOR
        mon = user32.MonitorFromWindow(hwnd, 2)          # MONITOR_DEFAULTTONEAREST
        shcore = ctypes.WinDLL("shcore")
        x, y = wt.UINT(), wt.UINT()
        if shcore.GetDpiForMonitor(mon, 0, ctypes.byref(x), ctypes.byref(y)) == 0 and x.value:
            return x.value
    except Exception:
        pass
    return 96


def window_scale(hwnd):
    """
    畫面實際像素 ÷ 遊戲自己以為的像素。
    遊戲不支援「每個螢幕」縮放時（實測 GPG 是「系統」感知），縮放 125% 的電腦上
    PrintWindow 截到的是 100% 大小的畫面、點擊座標也是 100% 的座標，這時回傳 1.25。
    """
    if not AVAILABLE or window_dpi_awareness(hwnd) == 2:
        return 1.0
    s = monitor_dpi(hwnd) / max(1, window_dpi(hwnd))
    return 1.0 if abs(s - 1.0) < 0.01 else s


class same_dpi_as:
    """
    with same_dpi_as(hwnd): ...
    在這段期間，這個執行緒改用「跟 hwnd 一樣的 DPI 座標系」。
    遊戲視窗如果不支援縮放（縮放 125%/150% 時），截圖大小、視窗座標、點擊座標才會一致。
    """

    def __init__(self, hwnd):
        self.hwnd = hwnd
        self.old = None

    def __enter__(self):
        if AVAILABLE and _GetWindowDpiAwarenessContext and _SetThreadDpiAwarenessContext:
            ctx = _GetWindowDpiAwarenessContext(self.hwnd)
            if ctx:
                self.old = _SetThreadDpiAwarenessContext(ctx) or None
        return self

    def __exit__(self, *exc):
        if self.old:
            _SetThreadDpiAwarenessContext(self.old)
        return False


def set_dpi_awareness():
    """讓座標都用實際像素。縮放 125%/150% 的電腦一定要先呼叫（重複呼叫沒關係）。"""
    global _dpi_done
    if not AVAILABLE or _dpi_done:
        return
    _dpi_done = True
    try:
        user32.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_ssize_t]
        user32.SetProcessDpiAwarenessContext.restype = wt.BOOL
        if user32.SetProcessDpiAwarenessContext(-4):   # PER_MONITOR_AWARE_V2
            return
    except Exception:
        pass
    try:
        ctypes.WinDLL("shcore").SetProcessDpiAwareness(2)
        return
    except Exception:
        pass
    try:
        user32.SetProcessDPIAware()
    except Exception:
        pass
