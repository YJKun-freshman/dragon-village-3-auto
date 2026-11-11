# -*- coding: utf-8 -*-
"""
路徑：不要寫死，在原始碼版與 PyInstaller exe 版都要能用。

  ROOT      程式資源所在（樣板圖等）。原始碼版 = 專案根目錄；exe 版 = sys._MEIPASS
  DATA_DIR  使用者資料（截圖、設定檔、日誌）。原始碼版 = 專案根目錄；exe 版 = exe 所在資料夾
"""
import os
import sys

if getattr(sys, "frozen", False):
    ROOT = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    DATA_DIR = os.path.dirname(sys.executable)
else:
    ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    DATA_DIR = ROOT

SCREENSHOT_DIR = os.path.join(DATA_DIR, "截圖")


def resource(path):
    """相對路徑 → 以 ROOT 為準的絕對路徑（例："fishing/templates/上鉤.png"）。"""
    path = os.fspath(path)
    if os.path.isabs(path):
        return path
    return os.path.join(ROOT, *path.replace("\\", "/").split("/"))


def data(path):
    path = os.fspath(path)
    if os.path.isabs(path):
        return path
    return os.path.join(DATA_DIR, *path.replace("\\", "/").split("/"))
