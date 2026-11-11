# -*- coding: utf-8 -*-
"""
core 對外的統一入口。

    from core.game import Game
    game = Game()
    if not game.connect():
        print(game.is_ready()[1])
    m = game.find("fishing/templates/上鉤.png", region=(0.3, 0.6, 0.7, 0.9))
    if m:
        game.click_match(m)

座標一律是「遊戲畫面的比例」0.0～1.0（不含黑邊），跟視窗大小無關。
"""
import glob
import logging
import os
import random
import threading
import time

import numpy as np

from . import _win32, capture as cap, input as inp, vision
from .capture import NORM_H
from .vision import Match
from .window import GameWindow, list_windows, window_exists, window_status

log = logging.getLogger("core")

SMALL_WINDOW_H = 600     # 遊戲畫面高度低於這個就警告


class GameNotReady(RuntimeError):
    """遊戲視窗不能用（找不到、縮到最小、截圖失敗）。訊息是給使用者看的中文。"""


class Game:
    def __init__(self, click_jitter=2.0, delay_jitter=0.0, fake_frames=None, loop_frames=False):
        """
        click_jitter  每次點擊隨機偏移的最大距離（正規化畫面的像素，高度 1000 為準），0 = 不偏移
        delay_jitter  每次點擊前隨機多等 0～N 秒
        fake_frames   離線測試：截圖檔路徑或 ndarray 的清單，capture() 依序回傳，點擊只記錄
        loop_frames   離線測試：最後一張之後回到第一張（False = 一直停在最後一張）
        """
        self.click_jitter = float(click_jitter)
        self.delay_jitter = float(delay_jitter)
        self.stop_event = None           # Task 會設定；wait_for / long_press 會被它中斷
        self.window = None               # GameWindow
        self.last_frame = None
        self.last_window = None              # capture_both() 的整個視窗畫面
        self._raw_size = None

        self._grabber = None
        self._box = None                 # 遊戲框（子視窗座標）
        self._box_client = None          # 算 box 時的子視窗大小
        self._warned_small = False
        self._lock = threading.RLock()

        # 離線模式
        self.offline = fake_frames is not None
        self.clicks = []                 # 離線模式下記錄的操作 [(動作, 參數...)]
        self._fake = list(fake_frames or [])
        self._fake_i = 0
        self._loop = loop_frames

    # ------------------------------------------------------------ 建立
    @classmethod
    def from_images(cls, source, loop=False, **kw):
        """離線測試：source 是資料夾（依檔名排序讀所有 png/jpg/bmp）或檔案清單。"""
        if isinstance(source, (str, os.PathLike)) and os.path.isdir(source):
            files = []
            for ext in ("png", "jpg", "jpeg", "bmp"):
                files += glob.glob(os.path.join(os.fspath(source), f"*.{ext}"))
            files.sort()
        elif isinstance(source, (str, os.PathLike)):
            files = [os.fspath(source)]
        else:
            files = list(source)
        if not files:
            raise FileNotFoundError(f"找不到截圖：{source}")
        return cls(fake_frames=files, loop_frames=loop, **kw)

    @staticmethod
    def list_windows():
        """所有 GPG 遊戲視窗（給 app 讓使用者選）。"""
        return list_windows()

    def connect(self, hwnd=None):
        """
        連接遊戲視窗。hwnd 可以是 GameWindow、主視窗 hwnd，或不給（自動找第一個）。
        找不到回傳 False。
        """
        if self.offline:
            return True
        _win32.set_dpi_awareness()
        wins = list_windows()
        target = None
        if isinstance(hwnd, GameWindow):
            target = hwnd
        elif hwnd is not None:
            target = next((g for g in wins if g.root == int(hwnd) or g.child == int(hwnd)), None)
        elif wins:
            target = wins[0]
        with self._lock:
            same = bool(target and self.window and self.window.root == target.root)
            self.window = target
            self._box = self._box_client = None
            self._warned_small = False
            if target and self._grabber is None:
                self._grabber = cap.Grabber()
        if target and not same:
            log.info("已連接遊戲視窗：%s", target.title)
        return target is not None

    def window_exists(self):
        """遊戲視窗還在（縮到最小也算在）。離線模式永遠 True。"""
        return True if self.offline else window_exists(self.window)

    def is_ready(self):
        """(可用?, 原因)"""
        if self.offline:
            return True, ""
        return window_status(self.window)

    # ------------------------------------------------------------ 截圖
    def _raw(self):
        """子視窗原始截圖（含黑邊）。"""
        ok, why = self.is_ready()
        if not ok:
            raise GameNotReady(why)
        img = self._grabber.grab(self.window.root, self.window.child)
        if img is None:
            ok, why = self.is_ready()
            raise GameNotReady(why or "截圖失敗，請確認遊戲視窗沒有縮到最小")
        return img

    def _next_fake(self):
        if not self._fake:
            raise GameNotReady("離線模式沒有截圖")
        item = self._fake[min(self._fake_i, len(self._fake) - 1)]
        self._fake_i += 1
        if self._loop and self._fake_i >= len(self._fake):
            self._fake_i = 0
        return vision.imread(item) if not isinstance(item, np.ndarray) else item

    def _update_box(self, img):
        ch, cw = img.shape[:2]
        if self._box is not None and self._box_client == (cw, ch):
            return self._box
        box, confident = cap.detect_game_box(img)
        if confident:
            self._box, self._box_client = box, (cw, ch)
        else:
            self._box, self._box_client = box, None     # 下次重新偵測
        gh = box[3] - box[1]
        if gh < SMALL_WINDOW_H and not self._warned_small:
            self._warned_small = True
            log.warning("遊戲畫面只有 %d 像素高，視窗太小，辨識可能不準。建議把視窗拉大。", gh)
        return box

    def capture(self):
        """正規化後的遊戲畫面（numpy BGR，高度 1000，沒有黑邊）。"""
        return self.capture_both(window=False)[0]

    def capture_both(self, window=True):
        """
        同一次截圖回傳 (遊戲畫面, 整個視窗畫面)，兩張都正規化成高度 1000。
        整個視窗畫面包含黑邊，給「播滿整個視窗的廣告」用（16:9 視窗時廣告的關閉鈕在黑邊上），
        座標用 click_window()。
        """
        with self._lock:
            img = self._next_fake() if self.offline else self._raw()
            box = self._update_box(img)
            frame = cap.normalize(img, box)
            h, w = img.shape[:2]
            whole = cap.normalize(img, (0, 0, w, h)) if window else None   # 不需要就不算（省 3～5 ms）
            self.last_frame = frame
            self.last_window = whole
            self._raw_size = (w, h)
            return frame, whole

    def capture_window(self):
        """整個子視窗（含黑邊）正規化成高度 1000。比例座標用 click_window()。"""
        return self.capture_both()[1]

    @property
    def letterboxed(self):
        """遊戲畫面左右有黑邊（16:9 視窗）。還沒截過圖時是 False。"""
        if self._box is None or not getattr(self, "_raw_size", None):
            return False
        x0, _, x1, _ = self._box
        return (x1 - x0) < self._raw_size[0] * 0.9

    def capture_raw(self):
        """子視窗原始截圖（含黑邊），除錯用。"""
        with self._lock:
            return self._next_fake() if self.offline else self._raw()

    def reset_box(self):
        """強制下次截圖重新偵測黑邊（例如使用者切換了視窗比例）。"""
        with self._lock:
            self._box = self._box_client = None

    @property
    def game_box(self):
        """遊戲畫面在子視窗中的範圍 (x0, y0, x1, y1)，還沒截過圖時是 None。"""
        return self._box

    # ------------------------------------------------------------ 找圖
    def _frame(self, frame):
        return self.capture() if frame is None else frame

    def find(self, template, region=None, threshold=0.85, frame=None, scales=None, blur=0):
        """scales、blur 見 vision.find()（預設關閉）。"""
        return vision.find(self._frame(frame), template, region, threshold, scales, blur)

    def find_all(self, template, region=None, threshold=0.85, frame=None, max_results=50, scales=None, blur=0):
        return vision.find_all(self._frame(frame), template, region, threshold, max_results, scales, blur)

    def best_score(self, template, region=None, frame=None, scales=None, blur=0):
        """不管門檻的最高分，調 threshold 用。"""
        return vision.best_score(self._frame(frame), template, region, scales, blur)

    def _stop(self, stop):
        return stop if stop is not None else self.stop_event

    def wait_for(self, template, timeout=10, interval=0.2, region=None, threshold=0.85, stop=None,
                 scales=None, blur=0):
        """等到樣板出現就回傳 Match；超時或被停止回傳 None。"""
        stop = self._stop(stop)
        end = time.monotonic() + timeout
        while True:
            m = self.find(template, region, threshold, scales=scales, blur=blur)
            if m:
                return m
            if time.monotonic() >= end:
                return None
            if inp._wait(interval, stop):
                return None

    def wait_gone(self, template, timeout=10, interval=0.2, region=None, threshold=0.85, stop=None,
                  scales=None, blur=0):
        """等到樣板消失回傳 True；超時或被停止回傳 False。"""
        stop = self._stop(stop)
        end = time.monotonic() + timeout
        while True:
            if not self.find(template, region, threshold, scales=scales, blur=blur):
                return True
            if time.monotonic() >= end:
                return False
            if inp._wait(interval, stop):
                return False

    def pixel(self, rx, ry, frame=None):
        """某一點的顏色 (B, G, R)。"""
        f = self._frame(frame)
        h, w = f.shape[:2]
        x = min(w - 1, max(0, int(rx * w)))
        y = min(h - 1, max(0, int(ry * h)))
        b, g, r = f[y, x]
        return int(b), int(g), int(r)

    # ------------------------------------------------------------ 點擊
    def _ensure_box(self):
        if self._box is None:
            self.capture()
        return self._box

    def to_client(self, rx, ry, jitter=True):
        """比例座標 → 子視窗像素座標。"""
        x0, y0, x1, y1 = self._ensure_box()
        gw, gh = x1 - x0, y1 - y0
        px, py = x0 + rx * gw, y0 + ry * gh
        if jitter and self.click_jitter > 0:
            s = gh / NORM_H                       # 正規化像素 → 實際像素
            px += random.uniform(-1, 1) * self.click_jitter * s
            py += random.uniform(-1, 1) * self.click_jitter * s
        px = min(x1 - 1, max(x0, px))
        py = min(y1 - 1, max(y0, py))
        # 截圖是 100% 座標，但遊戲收點擊用的是實際像素（縮放 125% 時要 ×1.25）
        sc = 1.0 if self.offline or not self.window else _win32.window_scale(self.window.child)
        return int(round(px * sc)), int(round(py * sc))

    def window_to_client(self, rx, ry):
        """「整個視窗」比例座標 → 子視窗像素座標（可以點到黑邊上）。"""
        if not getattr(self, "_raw_size", None):
            self.capture()
        w, h = self._raw_size
        px = min(w - 1, max(0, rx * w))
        py = min(h - 1, max(0, ry * h))
        sc = 1.0 if self.offline or not self.window else _win32.window_scale(self.window.child)
        return int(round(px * sc)), int(round(py * sc))

    def click_window(self, rx, ry):
        """點「整個視窗」的比例座標（含黑邊）。比例以 capture_window() 的畫面為準。"""
        self._pre_delay()
        if self.offline:
            self.clicks.append(("click_window", rx, ry))
            return
        self._check()
        x, y = self.window_to_client(rx, ry)
        inp.click(self.window.child, x, y)

    def _pre_delay(self):
        if self.delay_jitter > 0:
            inp._wait(random.uniform(0, self.delay_jitter), self.stop_event)

    def _check(self):
        ok, why = self.is_ready()
        if not ok:
            raise GameNotReady(why)

    def click(self, rx, ry):
        self._pre_delay()
        if self.offline:
            self.clicks.append(("click", rx, ry))
            return
        self._check()
        x, y = self.to_client(rx, ry)
        inp.click(self.window.child, x, y)

    def click_match(self, m: Match):
        self.click(m.x, m.y)

    def long_press(self, rx, ry, seconds):
        self._pre_delay()
        if self.offline:
            self.clicks.append(("long_press", rx, ry, seconds))
            return
        self._check()
        x, y = self.to_client(rx, ry)
        inp.long_press(self.window.child, x, y, seconds, self.stop_event)

    def drag(self, rx0, ry0, rx1, ry1, seconds=0.3):
        self._pre_delay()
        if self.offline:
            self.clicks.append(("drag", rx0, ry0, rx1, ry1, seconds))
            return
        self._check()
        x0, y0 = self.to_client(rx0, ry0)
        x1, y1 = self.to_client(rx1, ry1)
        inp.drag(self.window.child, x0, y0, x1, y1, seconds, stop=self.stop_event)

    def scroll(self, rx, ry, notches):
        """在 (rx, ry) 滾動滾輪。notches > 0 往上、< 0 往下（1 = 一格）。"""
        self._pre_delay()
        if self.offline:
            self.clicks.append(("scroll", rx, ry, notches))
            return
        self._check()
        x, y = self.to_client(rx, ry, jitter=False)
        inp.wheel(self.window.child, x, y, notches, stop=self.stop_event)

    def key(self, *names):
        """背景按鍵，例：game.key("shift", "tab")、game.key("esc")。（core v0.3.0，由「釣魚」對話新增）"""
        if self.offline:
            self.clicks.append(("key",) + tuple(names))
            return
        self._check()
        inp.key(self.window.child, *names)

    def dpi_info(self):
        """(遊戲視窗的 DPI 感知, 螢幕縮放%, 換算倍數)，除錯用。"""
        if self.offline or not self.window:
            return -1, 100, 1.0
        return (_win32.window_dpi_awareness(self.window.child),
                round(_win32.monitor_dpi(self.window.root) / 96 * 100),
                _win32.window_scale(self.window.child))

    # ------------------------------------------------------------ 其他
    def save_frame(self, path, frame=None):
        """存正規化畫面（支援中文路徑）。"""
        return vision.imwrite(path, self._frame(frame) if frame is None else frame)

    def close(self):
        if self._grabber:
            self._grabber.close()
            self._grabber = None
