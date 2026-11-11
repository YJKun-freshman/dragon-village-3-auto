# -*- coding: utf-8 -*-
"""在背景執行緒跑任務；同一時間只跑一個。另有監看執行緒定時檢查遊戲視窗。"""
import logging
import threading
import time

from core.game import GameNotReady
from core.task import TaskStopped

log = logging.getLogger("app")
task_log = logging.getLogger("task")

MONITOR_INTERVAL = 1.0


def _fmt_duration(sec):
    sec = int(sec)
    return f"{sec // 3600:d}:{sec // 60 % 60:02d}:{sec % 60:02d}"


class Runner:
    def __init__(self, game, task_classes, config):
        self.game = game
        self.tasks = {tuple(t.path): t for t in task_classes}
        self.config = config
        self.ui = None
        self.items_provider = None          # fn(template_id) -> {名稱: 參數}（Catalog.items_values）
        self._lock = threading.Lock()
        self._thread = None
        self._stop_event = None
        self._mon_stop = threading.Event()
        self._last_status = None
        self._multi_warned = False

    def set_tasks(self, task_classes):
        """自訂項目改變後換新的任務清單（執行中不會被呼叫）。"""
        self.tasks = {tuple(t.path): t for t in task_classes}

    # ------------------------------------------------------------ 介面呼叫
    def _ui(self, method, *args):
        fn = getattr(self.ui, method, None) if self.ui else None
        if fn:
            try:
                fn(*args)
            except Exception:
                log.debug("ui.%s 失敗", method, exc_info=True)

    @property
    def running(self):
        return self._thread is not None and self._thread.is_alive()

    def start(self, path, values):
        """ui 按開始（或熱鍵）時呼叫。成功開始回傳 True。"""
        path = tuple(path or ())
        with self._lock:
            if self.running:
                log.warning("已經有任務在執行，請先停止")
                return False
            cls = self.tasks.get(path)
            if cls is None:
                log.warning("請先在左邊選擇一個任務")
                self._ui("set_running", False)
                return False

            # 記住參數
            values = dict(values or {})
            self.config.set_task_values(path, {p.key: p.coerce(values.get(p.key)) for p in cls.params})
            self.config["last_task"] = list(path)
            self.config.save()

            # 檢查遊戲
            ok, why = self.game.is_ready()
            if not ok:
                self.game.connect()
                ok, why = self.game.is_ready()
            if not ok:
                log.warning("無法開始：%s", why)
                self._ui("set_running", False)
                return False

            self._stop_event = threading.Event()
            task = cls(self.game, values, log=task_log.info, stop_event=self._stop_event,
                       progress=lambda t: self._ui("set_progress", t))
            need = getattr(cls, "needs_items", None)
            if need:
                # 例：討伐戰巡迴要用每個討伐戰項目的出招流程（執行中不能編輯，開始時取一次就好）
                task.items = self.items_provider(need) if self.items_provider else {}
                log.debug("%s 讀到 %d 個「%s」項目", task.name(), len(task.items), need)
            self._ui("set_running", True)
            self._thread = threading.Thread(target=self._run, args=(task,), name="task", daemon=True)
            self._thread.start()
            return True

    def stop(self, wait=0.0):
        """ui 按停止（或熱鍵）時呼叫。"""
        ev = self._stop_event
        if ev and self.running and not ev.is_set():
            log.info("停止中…")
            ev.set()
        if wait and self._thread:
            self._thread.join(wait)

    def _run(self, task):
        name = task.name()
        log.info("▶ 開始：%s", name)
        t0 = time.monotonic()
        result = "完成"
        try:
            task.run()
            if task.should_stop():
                result = "已停止"
        except TaskStopped:
            result = "已停止"
        except GameNotReady as e:
            result = "遊戲無法使用"
            log.warning("遊戲無法使用：%s", e)
        except Exception as e:
            result = "發生錯誤"
            log.error("任務發生錯誤：%s", e, exc_info=True)
        finally:
            self.game.stop_event = None
            log.info("■ %s 結束（%s，執行時間 %s）", name, result, _fmt_duration(time.monotonic() - t0))
            self._ui("set_progress", "")
            self._ui("set_running", False)

    # ------------------------------------------------------------ 監看遊戲視窗
    def start_monitor(self):
        threading.Thread(target=self._monitor, name="monitor", daemon=True).start()

    def stop_monitor(self):
        self._mon_stop.set()

    def _monitor(self):
        while not self._mon_stop.is_set():
            try:
                self._check_game()
            except Exception:
                log.debug("監看失敗", exc_info=True)
            self._mon_stop.wait(MONITOR_INTERVAL)

    def _push_status(self, ok, why, force=False):
        if ok:
            title = self.game.window.title if self.game.window else "離線測試"
            status = (f"已連接：{title}", True)
        else:
            status = (why, False)
        if force or status != self._last_status:
            self._last_status = status
            self._ui("set_game_status", *status)

    # ------------------------------------------------------------ 設定選單：遊戲視窗
    def list_windows(self):
        return [{"id": int(w.root), "title": w.title} for w in self.game.list_windows()]

    def current_window(self):
        w = self.game.window
        return int(w.root) if w else None

    def select_window(self, wid):
        if self.running:
            return False, "執行中不能換視窗，請先停止"
        target = next((w for w in self.game.list_windows() if int(w.root) == int(wid)), None)
        if target is None:
            return False, "找不到這個視窗，可能已經關掉了，請重新整理"
        self.game.connect(target)
        ok, why = self.game.is_ready()
        self.config["game_window"] = target.title
        self.config.save()
        self._push_status(ok, why, force=True)
        if not ok:
            return False, why
        log.info("改用遊戲視窗：%s", target.title)
        return True, f"已連接：{target.title}"

    def _check_game(self):
        ok, why = self.game.is_ready()
        # 只有視窗不見了才重新找；縮到最小時視窗還在，重連也沒用（以前每秒重連並洗日誌）
        if not ok and not self.running and not self.game.window_exists():
            wins = self.game.list_windows()
            if wins:
                want = self.config["game_window"]
                pick = next((w for w in wins if w.title == want), wins[0])
                if len(wins) > 1 and not self._multi_warned:
                    self._multi_warned = True
                    log.warning("偵測到 %d 個遊戲視窗，使用：%s（可在設定裡換）", len(wins), pick.title)
                self.game.connect(pick)
                ok, why = self.game.is_ready()
        self._push_status(ok, why)
        if not ok and self.running and self._stop_event and not self._stop_event.is_set():
            log.warning("執行中遊戲無法使用（%s），停止任務", why)
            self._stop_event.set()
