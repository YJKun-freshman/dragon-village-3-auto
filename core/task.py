# -*- coding: utf-8 -*-
"""
任務基底類別。釣魚、戰鬥的每個任務都繼承 Task。

    from core.task import Task, Param

    class Fishing(Task):
        path = ("釣魚",)
        params = [Param("max_rounds", "釣魚次數上限", int, default=100, min=1, max=9999)]

        def run(self):
            for i in range(self.values["max_rounds"]):
                if self.should_stop():
                    break
                self.set_progress(f"第 {i + 1} 輪")
                self.sleep(1.0)
"""
import threading
from dataclasses import dataclass, field


@dataclass
class Param:
    key: str
    label: str                    # 介面上顯示的中文
    type: type                    # int / float / bool / str
    default: object
    min: float = None
    max: float = None
    choices: list = None          # 有值時顯示下拉選單
    help: str = ""                # 滑鼠移上去的說明
    widget: str = None            # 特殊編輯器（ui 看到就換成專用元件，值的型別不變）。目前有："sequence" 出招流程

    def coerce(self, value):
        """把介面／設定檔傳來的值轉成正確型別並限制範圍；轉不了就用預設值。"""
        if value is None:
            return self.default
        try:
            if self.type is bool:
                if isinstance(value, str):
                    v = value.strip().lower() in ("1", "true", "yes", "y", "on", "是")
                else:
                    v = bool(value)
            else:
                v = self.type(value)
        except (TypeError, ValueError):
            return self.default
        if self.type in (int, float):
            if self.min is not None and v < self.min:
                v = self.type(self.min)
            if self.max is not None and v > self.max:
                v = self.type(self.max)
        if self.choices and v not in self.choices:
            return self.default
        return v


class TaskStopped(Exception):
    """在任務裡 raise 這個可以直接結束 run()（app 會當成正常停止）。"""


class Task:
    path: tuple = ()              # 功能樹上的位置，例：("戰鬥", "討伐戰", "泰迪布羅")
    params: list = []
    description: str = ""
    needs_items: str = None       # 要讀某個類型所有自訂項目的設定時填 template_id（例 "raid"）
    items: dict = {}              # needs_items 有填時，主程式在 run() 前設定：{項目名稱: 參數 dict}

    def __init__(self, game, values: dict, log, stop_event: threading.Event = None, progress=None):
        """
        game        core.game.Game
        values      參數值 {key: value}，缺的用預設值
        log         log(text) 函式（app 提供，會顯示在介面並寫入日誌檔）
        stop_event  threading.Event，set() 就代表要停止
        progress    progress(text) 函式，顯示在介面狀態列（可不給）
        """
        self.game = game
        self.stop_event = stop_event or threading.Event()
        self._log = log or print
        self._progress = progress
        values = values or {}
        self.values = {p.key: p.coerce(values.get(p.key)) for p in self.params}
        game.stop_event = self.stop_event

    # 子類別實作
    def run(self):
        raise NotImplementedError

    # 工具
    @classmethod
    def name(cls):
        return " / ".join(cls.path) if cls.path else cls.__name__

    @classmethod
    def defaults(cls):
        return {p.key: p.default for p in cls.params}

    def should_stop(self) -> bool:
        return self.stop_event.is_set()

    def check_stop(self):
        """要停止就直接跳出 run()。"""
        if self.stop_event.is_set():
            raise TaskStopped()

    def sleep(self, seconds) -> bool:
        """可被停止中斷的 sleep。回傳 True = 睡完；False = 中途被停止。"""
        return not self.stop_event.wait(max(0.0, seconds))

    def log(self, text):
        self._log(str(text))

    def set_progress(self, text):
        if self._progress:
            self._progress(str(text))
