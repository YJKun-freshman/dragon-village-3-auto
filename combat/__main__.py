# -*- coding: utf-8 -*-
"""
單獨測試戰鬥（主程式整合前用）。在 D:\\龍村3 開命令提示字元：

    python -m combat                                   # 討伐戰／泰迪布羅，用預設流程
    python -m combat 泰迪布羅 "技能1 > 替換2 > 必殺技 > 自動"   # 沒寫類型 = 討伐戰，名稱隨便取（只用在日誌）
    python -m combat 討伐戰 屠龍者 "自動"
    python -m combat 公會BOSS 喵喵王 "技能1 > 自動"
    python -m combat 泰迪布羅 "技能1 > 自動" 最小化   # 最後的自動改成按最小化，腳本直接結束（討伐戰）
    python -m combat 泰迪布羅 "技能1 > 自動" 恢復劑 鑽石   # 體力不足時只用寫出來的（順序固定：廣告 → 恢復劑 → 鑽石）
    python -m combat 泰迪布羅 "技能1 > 自動" 不補         # 體力不足就停止
      （都沒寫時用討伐戰的預設：看廣告 ✅、恢復劑 ✅、鑽石 ❌）
    python -m combat 檢查 "技能1 > 替換 > 替換2 > 自動"   # 只檢查流程寫法，不開遊戲

按 Ctrl+C 停止。
"""
import logging
import sys
import threading
import time

from core.game import Game, GameNotReady
from core.task import TaskStopped
from .sequence import SequenceError, parse, to_text


def disable_quick_edit():
    """
    關掉命令提示字元的「快速編輯模式」。
    開著的時候，滑鼠點一下 CMD 視窗就會進入選取狀態，程式印日誌時會被卡住（看起來像當掉），
    要按一下鍵盤或點回視窗才會繼續。
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes
        k32 = ctypes.windll.kernel32
        h = k32.GetStdHandle(-10)                      # STD_INPUT_HANDLE
        mode = ctypes.c_uint32()
        if k32.GetConsoleMode(h, ctypes.byref(mode)):
            ENABLE_QUICK_EDIT, ENABLE_EXTENDED_FLAGS = 0x0040, 0x0080
            k32.SetConsoleMode(h, (mode.value & ~ENABLE_QUICK_EDIT) | ENABLE_EXTENDED_FLAGS)
    except Exception:
        pass


def main():
    disable_quick_edit()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    args = sys.argv[1:]
    if args and args[0] == "檢查":
        try:
            steps = parse(args[1] if len(args) > 1 else "")
            for n, s in enumerate(steps, 1):
                print(f"{n}. {to_text([s])}")
            print("✅ 流程沒問題")
        except SequenceError as e:
            print(f"❌ {e}")
        return

    from .kinds import TEMPLATES, Raid, make_item
    kinds = {t.type_name: t for t in TEMPLATES}
    if args and args[0] in kinds:
        tpl, args = kinds[args[0]], args[1:]
    else:
        tpl = Raid
    name = args[0] if args else "泰迪布羅"
    preset = dict(tpl.default_items).get(name)
    cls = make_item(tpl, name, preset)
    keys = {p.key for p in cls.params}
    values = {}
    if len(args) > 1:
        values["sequence"] = args[1]
    flags = args[2:]
    refill = {"廣告": "refill_ad", "恢復劑": "refill_potion", "鑽石": "refill_gems"}
    if "refill_ad" in keys and (any(w in flags for w in refill) or "不補" in flags):
        for word, key in refill.items():
            values[key] = word in flags
    if "最小化" in flags:
        if "finish_mode" in keys:
            from .raid.common import MINIMIZE
            values["finish_mode"] = MINIMIZE
        else:
            print(f"⚠ {tpl.type_name}沒有最小化按鈕，忽略「最小化」")

    game = Game()
    if not game.connect():
        print("找不到遊戲視窗，請先開啟 Google Play 遊戲的龍村3")
        return

    def log(text):
        print(time.strftime("%H:%M:%S"), text, flush=True)

    stop = threading.Event()
    task = cls(game, values, log, stop_event=stop, progress=None)

    def worker():
        try:
            task.run()
        except TaskStopped:
            log("已停止")
        except GameNotReady as e:
            log(f"❌ {e}")
        except Exception:
            import traceback
            traceback.print_exc()

    th = threading.Thread(target=worker, daemon=True)
    th.start()
    log("按 Ctrl+C 停止")
    try:
        while th.is_alive():
            th.join(0.2)
    except KeyboardInterrupt:
        log("停止中…")
        stop.set()
        th.join(5)
    game.close()


if __name__ == "__main__":
    main()
