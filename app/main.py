# -*- coding: utf-8 -*-
"""程式進入點：根目錄 main.py 會呼叫 run()。"""
import inspect
import logging
import os
import sys
import threading

from core import _win32
from core.game import Game

from . import APP_NAME, __version__, config as cfgmod, logs, registry
from .hotkeys import DEFAULT as HK_DEFAULT, HotkeyThread, validate_pair
from .runner import Runner

log = logging.getLogger("app")


def load_ui():
    """正式介面（ui/）還沒好或載入失敗時，用 app 內建的臨時介面。"""
    try:
        from ui import MainWindow
        return MainWindow
    except ModuleNotFoundError as e:
        if e.name != "ui":
            log.exception("載入介面失敗，改用臨時介面")
    except Exception:
        log.exception("載入介面失敗，改用臨時介面")
    from .fallback_ui import MainWindow
    return MainWindow


def _accepts(fn, name):
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        return False
    return name in sig.parameters or any(p.kind == p.VAR_KEYWORD for p in sig.parameters.values())


def _sequence_tools():
    """出招流程編輯器用的轉換函式（ui 不能 import combat，由這裡傳進去）。"""
    try:
        from combat import sequence
    except Exception:
        log.debug("沒有 combat.sequence，出招流程用一般文字欄位", exc_info=True)
        return None
    return {"parse": sequence.parse, "to_text": sequence.to_text, "validate": sequence.validate}


def _open_folder(folder):
    os.makedirs(folder, exist_ok=True)
    os.startfile(folder)


def _install_excepthooks():
    def hook(exc_type, exc, tb):
        logging.getLogger("app").critical("未處理的錯誤：%s", exc, exc_info=(exc_type, exc, tb))

    sys.excepthook = hook
    threading.excepthook = lambda a: hook(a.exc_type, a.exc_value, a.exc_traceback)


def run(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    _win32.set_dpi_awareness()                # 一定要在建立任何視窗之前

    cfg = cfgmod.Config()
    ui_log, log_file = logs.setup(os.path.join(cfg.folder, "logs"), cfg["log_keep_days"])
    _install_excepthooks()
    log.debug("%s v%s 啟動，Python %s，設定檔 %s", APP_NAME, __version__, sys.version.split()[0], cfg.path)

    catalog = registry.Catalog(cfg, include_demo=cfg["show_demo_tasks"] or "--demo" in argv)
    task_classes = catalog.classes
    game = Game(click_jitter=cfg["click_jitter"])
    runner = Runner(game, task_classes, cfg)
    runner.items_provider = catalog.items_values

    MainWindow = load_ui()
    kwargs = dict(
        title=f"{APP_NAME} v{__version__}",
        tasks=catalog.to_ui(),
        on_start=runner.start,
        on_stop=runner.stop,
        saved_values=cfg.all_values([t.path for t in task_classes]),
    )
    if catalog.templates and _accepts(MainWindow.__init__, "task_groups"):
        kwargs["task_groups"] = catalog.groups()
    if catalog.templates and _accepts(MainWindow.__init__, "task_editor"):
        def edit(op):
            def fn(*args):
                if runner.running:
                    return False, "執行中不能編輯", None
                try:
                    ok, msg, _ = getattr(catalog, op)(*args)
                except Exception as e:                       # noqa: BLE001
                    log.error("編輯任務失敗：%s", e, exc_info=True)
                    return False, f"編輯失敗：{e}", None
                if not ok:
                    return False, msg, None
                cfg.save()
                runner.set_tasks(catalog.rebuild())
                log.info(msg)
                return True, msg, catalog.to_ui()
            return fn
        kwargs["task_editor"] = {op: edit(op) for op in ("add", "rename", "delete", "move")}
    last = tuple(cfg["last_task"] or ())
    if last and _accepts(MainWindow.__init__, "selected"):
        kwargs["selected"] = last
    if _accepts(MainWindow.__init__, "sequence_tools"):
        kwargs["sequence_tools"] = _sequence_tools()
    if _accepts(MainWindow.__init__, "window_state"):
        kwargs["window_state"] = cfg["window"]
    if _accepts(MainWindow.__init__, "on_open_logs"):
        log_dir = os.path.join(cfg.folder, "logs")
        kwargs["on_open_logs"] = lambda: _open_folder(log_dir)
    # 熱鍵：設定檔的值不合規則就用預設
    keys, err = validate_pair(cfg["hotkeys"].get("start"), cfg["hotkeys"].get("stop"))
    if err:
        log.warning("設定檔的熱鍵不正確（%s），改用預設 F5／F6", err)
        keys = dict(HK_DEFAULT)
    cfg["hotkeys"] = dict(keys)
    win_ref = {}
    hotkeys = HotkeyThread(keys, {
        "start": lambda: win_ref["w"].request_start() if hasattr(win_ref["w"], "request_start") else None,
        "stop": runner.stop,
    })

    def set_hotkeys(start, stop):
        if runner.running:
            return False, "執行中不能修改熱鍵，請先停止"
        new, err = validate_pair(start, stop)
        if err:
            return False, err
        ok, msg = hotkeys.set_keys(new)
        if ok:
            cfg["hotkeys"] = dict(new)
            cfg.save()
            if hasattr(win_ref["w"], "set_hotkey_labels"):
                win_ref["w"].set_hotkey_labels(new["start"], new["stop"])
            log.info("熱鍵改為：開始 %s、停止 %s", new["start"], new["stop"])
        return ok, msg

    if _accepts(MainWindow.__init__, "settings"):
        kwargs["settings"] = {
            "hotkeys": dict(keys),
            "default_hotkeys": dict(HK_DEFAULT),
            "set_hotkeys": set_hotkeys,
            "pause_hotkeys": lambda paused: hotkeys.pause(paused),
            "list_windows": runner.list_windows,
            "current_window": runner.current_window,
            "select_window": runner.select_window,
        }
    win = MainWindow(**kwargs)
    win_ref["w"] = win
    runner.ui = win
    ui_log.attach(win)
    hotkeys.start()

    log.info("%s v%s 已啟動。%s 開始、%s 停止（遊戲在其他桌面也有效）",
             APP_NAME, __version__, keys["start"], keys["stop"])
    if log_file:
        log.debug("日誌檔：%s", log_file)
    runner.start_monitor()
    try:
        win.run()
    finally:
        try:
            # 改了參數沒按開始就關掉，也要記住（ui 的 get_values() 關掉後仍可呼叫）
            for path, vals in win.get_values().items():
                if tuple(path) in runner.tasks:
                    cfg.set_task_values(path, vals)
        except Exception:
            log.debug("讀取參數失敗", exc_info=True)
        if hasattr(win, "get_window_state"):
            try:
                cfg["window"] = win.get_window_state()
            except Exception:
                log.debug("讀取視窗狀態失敗", exc_info=True)
        runner.stop(wait=3)
        runner.stop_monitor()
        hotkeys.stop()
        game.close()
        cfg.save()
