# -*- coding: utf-8 -*-
"""日誌：同時寫進 logs\\YYYY-MM-DD.log 和顯示在介面上。"""
import datetime
import glob
import logging
import os
import time

FMT = "%(asctime)s %(levelname)-7s [%(name)s] %(message)s"
UI_LEVEL = {logging.DEBUG: "info", logging.INFO: "info", logging.WARNING: "warn",
            logging.ERROR: "error", logging.CRITICAL: "error"}


class UiHandler(logging.Handler):
    """把日誌轉給介面的 append_log(text, level)。介面還沒建好前先暫存。"""

    def __init__(self):
        super().__init__(logging.INFO)
        self.ui = None
        self.pending = []

    def attach(self, ui):
        self.ui = ui
        for text, level in self.pending:
            self._send(text, level)
        self.pending.clear()

    def _send(self, text, level):
        try:
            self.ui.append_log(text, level)
        except Exception:
            pass

    def emit(self, record):
        text = record.getMessage()
        if record.exc_info and record.levelno >= logging.ERROR:
            text += "（詳細錯誤在日誌檔）"
        level = UI_LEVEL.get(record.levelno, "info")
        if self.ui is None:
            self.pending.append((text, level))
        else:
            self._send(text, level)


def cleanup(folder, keep_days):
    cutoff = time.time() - keep_days * 86400
    files = []
    for ext in ("log", "png", "jpg"):          # 日誌檔＋任務存的除錯截圖
        files += glob.glob(os.path.join(folder, f"*.{ext}"))
    for f in files:
        try:
            if os.path.getmtime(f) < cutoff:
                os.remove(f)
        except OSError:
            pass


def setup(folder, keep_days=7):
    """設定日誌，回傳 (UiHandler, 日誌檔路徑)。"""
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    for h in list(root.handlers):
        root.removeHandler(h)
    path = None
    try:
        os.makedirs(folder, exist_ok=True)
        cleanup(folder, keep_days)
        path = os.path.join(folder, f"{datetime.date.today():%Y-%m-%d}.log")
        fh = logging.FileHandler(path, encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(logging.Formatter(FMT))
        root.addHandler(fh)
    except OSError:
        path = None
    ui = UiHandler()
    root.addHandler(ui)
    return ui, path
