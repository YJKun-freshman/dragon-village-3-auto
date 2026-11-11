# -*- coding: utf-8 -*-
"""
設定檔 config.json。
位置：程式旁邊（原始碼版 = 專案根目錄；exe 版 = exe 所在資料夾）；
那裡寫不進去（例如放在 Program Files）時，改放 %APPDATA%\\龍村3自動腳本\\。
"""
import json
import logging
import os
import threading

from core import paths

log = logging.getLogger("app")

APPDATA_DIR_NAME = "龍村3自動腳本"
FILE_NAME = "config.json"

DEFAULTS = {
    "hotkeys": {"start": "F5", "stop": "F6"},
    "last_task": None,          # ["戰鬥", "討伐戰", "泰迪布羅"]
    "values": {},               # {"戰鬥/討伐戰/泰迪布羅": {key: value}}
    "click_jitter": 2.0,        # 點擊隨機偏移（正規化像素）
    "log_keep_days": 7,
    "show_demo_tasks": False,   # 顯示「開發測試」任務（開發時在 config.json 設 true，或用 --demo）
    "custom_tasks": {},         # 自訂項目：{template_id: [名稱, ...]}（順序 = 功能樹順序）
    "game_window": None,        # 使用者在設定選的遊戲視窗標題；有多個視窗時優先連這個
    "window": None,             # 視窗大小、位置、精簡／完整模式（ui 的 get_window_state()）
}


def _appdata_dir():
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, APPDATA_DIR_NAME)


def _writable(folder):
    try:
        os.makedirs(folder, exist_ok=True)
        test = os.path.join(folder, ".write_test")
        with open(test, "w") as f:
            f.write("ok")
        os.remove(test)
        return True
    except OSError:
        return False


def data_dir():
    """設定檔與日誌所在資料夾。"""
    local = paths.DATA_DIR
    if os.path.exists(os.path.join(local, FILE_NAME)) or _writable(local):
        return local
    return _appdata_dir()


def path_key(path):
    return "/".join(path)


class Config:
    def __init__(self, folder=None):
        self.folder = folder or data_dir()
        self.path = os.path.join(self.folder, FILE_NAME)
        self.data = json.loads(json.dumps(DEFAULTS))
        self._lock = threading.Lock()
        self.load()

    def load(self):
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, encoding="utf-8") as f:
                loaded = json.load(f)
        except (OSError, ValueError) as e:
            # 壞掉的設定檔改名保留，用預設值繼續
            log.warning("設定檔讀取失敗，改用預設值：%s", e)
            try:
                os.replace(self.path, self.path + ".bad")
            except OSError:
                pass
            return
        for k, v in loaded.items():
            if isinstance(v, dict) and isinstance(self.data.get(k), dict):
                self.data[k].update(v)
            else:
                self.data[k] = v

    def save(self):
        with self._lock:
            try:
                os.makedirs(self.folder, exist_ok=True)
                tmp = self.path + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(self.data, f, ensure_ascii=False, indent=2)
                os.replace(tmp, self.path)
            except OSError as e:
                log.warning("設定檔存檔失敗：%s", e)

    # 便利方法
    def __getitem__(self, k):
        return self.data[k]

    def __setitem__(self, k, v):
        self.data[k] = v

    def task_values(self, path):
        return dict(self.data["values"].get(path_key(path), {}))

    def set_task_values(self, path, values):
        self.data["values"][path_key(path)] = dict(values)

    def all_values(self, paths_):
        """給 ui 的 saved_values：{path(tuple): {key: value}}"""
        return {tuple(p): self.task_values(p) for p in paths_ if path_key(p) in self.data["values"]}
