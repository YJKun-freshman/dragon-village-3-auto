# -*- coding: utf-8 -*-
"""
背景截圖、偵測遊戲畫面範圍（去黑邊）、正規化成高度 1000。

座標名詞：
  子視窗座標  CROSVM_1 子視窗內的像素（點擊用這個）
  遊戲框 box  (x0, y0, x1, y1)：遊戲畫面在子視窗裡的範圍（去掉黑邊）
  比例座標    遊戲畫面的 0.0～1.0
  正規化畫面  遊戲框縮放到高度 NORM_H 的影像（找圖、樣板都用這個）
"""
import numpy as np

from . import _win32 as w

NORM_H = 1000            # 正規化後的高度
GAME_ASPECT = 9 / 16     # 遊戲畫面寬高比
LIT_LEVEL = 30           # 亮度 > 這個值才算「有畫面」
MIN_BLOCK = 10           # 寬/高小於這個的亮區當成雜邊（右、下的 1～3 像素亮邊）


# ---------------------------------------------------------------- 截圖
class Grabber:
    """PrintWindow 截主視窗，再裁出子視窗。重複使用 DC / bitmap 加快速度。"""

    def __init__(self):
        self._size = None
        self._sdc = self._mdc = self._bmp = self._old = None
        self._buf = None

    def _ensure(self, wdt, hgt):
        if self._size == (wdt, hgt):
            return
        self.close()
        self._sdc = w.user32.GetDC(None)
        self._mdc = w.gdi32.CreateCompatibleDC(self._sdc)
        self._bmp = w.gdi32.CreateCompatibleBitmap(self._sdc, wdt, hgt)
        self._old = w.gdi32.SelectObject(self._mdc, self._bmp)
        self._buf = np.empty((hgt, wdt, 4), np.uint8)
        self._size = (wdt, hgt)

    def close(self):
        if self._mdc:
            w.gdi32.SelectObject(self._mdc, self._old)
            w.gdi32.DeleteObject(self._bmp)
            w.gdi32.DeleteDC(self._mdc)
        if self._sdc:
            w.user32.ReleaseDC(None, self._sdc)
        self._size = None
        self._sdc = self._mdc = self._bmp = self._old = None

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass

    def grab(self, root, child):
        """回傳子視窗內容（BGR ndarray，可能含黑邊），失敗回傳 None。"""
        return self._grab(root, child, w.window_scale(child))

    def _grab(self, root, child, scale=1.0):
        import ctypes
        r = w.wt.RECT()
        w.user32.GetWindowRect(root, ctypes.byref(r))
        rw, rh = r.right - r.left, r.bottom - r.top
        c = w.wt.RECT()
        w.user32.GetClientRect(child, ctypes.byref(c))
        cw, ch = c.right, c.bottom
        if rw <= 0 or rh <= 0 or cw <= 0 or ch <= 0:
            return None
        o = w.wt.POINT(0, 0)
        w.user32.ClientToScreen(child, ctypes.byref(o))
        ox, oy = o.x - r.left, o.y - r.top

        self._ensure(rw, rh)
        if not w.user32.PrintWindow(root, self._mdc, w.PW_RENDERFULLCONTENT):
            return None
        bi = w.BITMAPINFOHEADER(40, rw, -rh, 1, 32, 0, rw * rh * 4, 0, 0, 0, 0)
        got = w.gdi32.GetDIBits(self._mdc, self._bmp, 0, rh,
                                self._buf.ctypes.data_as(ctypes.c_void_p), ctypes.byref(bi), 0)
        if got != rh:
            return None
        if scale != 1.0:
            # 遊戲不支援縮放：截圖內容是縮小（100%）的大小，座標也要換成 100% 的
            ox, oy = round(ox / scale), round(oy / scale)
            cw, ch = round(cw / scale), round(ch / scale)
        x0, y0 = max(0, ox), max(0, oy)
        x1, y1 = min(rw, ox + cw), min(rh, oy + ch)
        if x1 <= x0 or y1 <= y0:
            return None
        return np.ascontiguousarray(self._buf[y0:y1, x0:x1, :3])


# ---------------------------------------------------------------- 去黑邊
def _runs(mask):
    """布林陣列中連續 True 的區段 [(start, end), ...]（end 不含）"""
    m = np.concatenate(([False], mask, [False]))
    d = np.diff(m.astype(np.int8))
    starts = np.flatnonzero(d == 1)
    ends = np.flatnonzero(d == -1)
    return list(zip(starts.tolist(), ends.tolist()))


def _main_run(mask, merge_gap):
    """取最大的連續亮區；間隔小於 merge_gap 的亮區先合併（遊戲內暗色區塊不會切斷）。
    寬度 < MIN_BLOCK 的獨立亮區（例如右邊 1 像素亮邊）不採用。"""
    runs = [r for r in _runs(mask)]
    if not runs:
        return None
    merged = [list(runs[0])]
    for s, e in runs[1:]:
        if s - merged[-1][1] <= merge_gap and (e - s) >= MIN_BLOCK:
            merged[-1][1] = e
        else:
            merged.append([s, e])
    merged = [r for r in merged if r[1] - r[0] >= MIN_BLOCK]
    if not merged:
        return None
    s, e = max(merged, key=lambda r: r[1] - r[0])
    return s, e


def fallback_box(cw, ch):
    """偵測失敗（例如全黑的讀取畫面）時：假設遊戲畫面 9:16、置中、填滿高度。"""
    gh = ch
    gw = min(cw, round(gh * GAME_ASPECT))
    if gw == cw and cw / ch < GAME_ASPECT:      # 視窗比 9:16 還窄 → 寬度填滿
        gh = min(ch, round(cw / GAME_ASPECT))
    x0 = (cw - gw) // 2
    y0 = (ch - gh) // 2
    return x0, y0, x0 + gw, y0 + gh


def detect_game_box(img):
    """
    找出遊戲畫面範圍（去掉黑邊）。
    回傳 (box, confident)。confident=False 表示偵測不可靠、用了 fallback_box，
    呼叫端不要快取，下次再偵測。
    """
    ch, cw = img.shape[:2]
    # 列方向每 4 列取 1 列、欄方向每 4 欄取 1 欄，邊界位置仍是逐像素
    col_ratio = (img[::4].max(axis=2) > LIT_LEVEL).mean(axis=0)
    cols = _main_run(col_ratio > 0.03, merge_gap=max(4, cw // 20))
    if cols is None:
        return fallback_box(cw, ch), False
    x0, x1 = cols
    row_ratio = (img[:, x0:x1:4].max(axis=2) > LIT_LEVEL).mean(axis=1)
    rows = _main_run(row_ratio > 0.03, merge_gap=max(4, ch // 20))
    if rows is None:
        return fallback_box(cw, ch), False
    y0, y1 = rows
    gw, gh = x1 - x0, y1 - y0
    aspect = gw / max(1, gh)
    # 合理範圍：9:16 附近，而且撐滿高度或寬度（實測 1001/1004）。
    # 以前是 80%：轉場時上／下方約 10% 暗色的畫面也會被當成可靠範圍並快取到視窗大小改變為止 → 改 97%
    if 0.50 <= aspect <= 0.62 and (gh >= ch * 0.97 or gw >= cw * 0.97):
        return (x0, y0, x1, y1), True
    return fallback_box(cw, ch), False


# ---------------------------------------------------------------- 正規化
def normalize(img, box):
    """把遊戲框裁出來，縮放到高度 NORM_H。"""
    import cv2
    x0, y0, x1, y1 = box
    g = img[y0:y1, x0:x1]
    gh, gw = g.shape[:2]
    if gh == NORM_H:
        return np.ascontiguousarray(g)
    nw = max(1, round(gw * NORM_H / gh))
    interp = cv2.INTER_AREA if gh > NORM_H else cv2.INTER_LINEAR
    return cv2.resize(g, (nw, NORM_H), interpolation=interp)


def norm_width(box):
    x0, y0, x1, y1 = box
    return max(1, round((x1 - x0) * NORM_H / max(1, y1 - y0)))
