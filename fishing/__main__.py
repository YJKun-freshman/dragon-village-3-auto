# -*- coding: utf-8 -*-
"""
單獨測試釣魚（主程式整合前用）。在 D:\\龍村3 開命令提示字元：

    python -m fishing            # 預設 20 輪
    python -m fishing 5          # 釣 5 輪
    python -m fishing 60 廣告    # 釣 60 輪，魚餌用完自動看廣告（視窗要 9:16）

按 Ctrl+C 停止。
"""
import logging
import sys
import threading
import time

from core.game import Game, GameNotReady
from .fishing import Fishing


def main():
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    rounds = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    ads = any(a in ("廣告", "ad", "ads") for a in sys.argv[2:])

    game = Game()
    if not game.connect():
        print("找不到遊戲視窗，請先開啟 Google Play 遊戲的龍村3")
        return

    def log(text):
        print(time.strftime("%H:%M:%S"), text, flush=True)

    stop = threading.Event()
    task = Fishing(game, {"max_rounds": rounds, "watch_ads": ads}, log, stop_event=stop, progress=None)

    def worker():
        try:
            task.run()
        except GameNotReady as e:
            log(f"❌ {e}")
        except Exception:
            import traceback
            traceback.print_exc()

    th = threading.Thread(target=worker, daemon=True)
    th.start()
    log(f"開始釣魚（{rounds} 輪{'，魚餌用完自動看廣告' if ads else ''}），按 Ctrl+C 停止")
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
