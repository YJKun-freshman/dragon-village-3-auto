# -*- coding: utf-8 -*-
"""
龍村3 截圖工具（開發用）
  - 背景截圖：存的是「正規化畫面」（去黑邊、高度 1000），可以直接從裡面裁樣板
  - 連拍：每 N 毫秒截一張，連拍 M 秒（分析釣魚時機用）
  - 框選：在圖上拖曳框出範圍 → 顯示比例座標，可複製 region、存成樣板
  - 點擊／拖曳測試：在預覽圖上點，會在背景送到遊戲（不動真實滑鼠）

執行：在專案根目錄 `python -m core.tools.capture_tool`（或雙擊 capture.bat）
"""
import base64
import datetime
import logging
import os
import re
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import cv2  # noqa: E402

from core import __version__, paths, vision  # noqa: E402
from core.game import Game, GameNotReady  # noqa: E402

PREVIEW_MS = 500


def safe_name(s, fallback):
    s = re.sub(r'[\\/:*?"<>|]', "_", s.strip())
    return s or fallback


def unique_path(folder, name, ext=".png"):
    p = os.path.join(folder, name + ext)
    n = 2
    while os.path.exists(p):
        p = os.path.join(folder, f"{name}_{n}{ext}")
        n += 1
    return p


class CaptureTool:
    def __init__(self, root):
        self.root = root
        self.game = Game(click_jitter=0)
        self.windows = []
        self.image = None            # 目前顯示的正規化畫面（原尺寸）
        self.image_name = ""
        self.scale = 1.0
        self.sel = None              # 框選 (x0, y0, x1, y1) 原圖像素
        self._drag_start = None
        self._photo = None
        self.busy = False
        self.tpl_dir = paths.ROOT

        root.title(f"龍村3 截圖工具（core v{__version__}）")
        sh = root.winfo_screenheight()
        self.scale = min(1.0, max(0.4, (sh - 160) / 1000))
        self._build()
        self.refresh_windows()
        self.root.after(PREVIEW_MS, self._preview_loop)

    # ------------------------------------------------------------ 介面
    def _build(self):
        top = ttk.Frame(self.root, padding=6)
        top.pack(fill="x")
        ttk.Label(top, text="遊戲視窗：").pack(side="left")
        self.win_var = tk.StringVar()
        self.win_box = ttk.Combobox(top, textvariable=self.win_var, state="readonly", width=32)
        self.win_box.pack(side="left")
        self.win_box.bind("<<ComboboxSelected>>", lambda e: self.connect_selected())
        ttk.Button(top, text="重新尋找", command=self.refresh_windows).pack(side="left", padx=4)
        self.status = tk.StringVar(value="")
        ttk.Label(top, textvariable=self.status, foreground="#555").pack(side="left", padx=8)

        body = ttk.Frame(self.root, padding=(6, 0, 6, 6))
        body.pack(fill="both", expand=True)
        cw, ch = int(570 * self.scale), int(1000 * self.scale)
        self.canvas = tk.Canvas(body, width=cw, height=ch, bg="#222", highlightthickness=0, cursor="crosshair")
        self.canvas.pack(side="left")
        self.canvas.bind("<ButtonPress-1>", self._on_down)
        self.canvas.bind("<B1-Motion>", self._on_move_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_up)
        self.canvas.bind("<Motion>", self._on_hover)
        self.canvas.bind("<MouseWheel>", self._on_wheel)

        side = ttk.Frame(body, padding=(10, 0, 0, 0))
        side.pack(side="left", fill="y")

        # 截圖
        f = ttk.LabelFrame(side, text="截圖", padding=6)
        f.pack(fill="x")
        ttk.Label(f, text="名稱（例：釣魚_上鉤）").pack(anchor="w")
        self.name_var = tk.StringVar()
        e = ttk.Entry(f, textvariable=self.name_var, width=28)
        e.pack(fill="x")
        e.bind("<Return>", lambda ev: self.shot())
        row = ttk.Frame(f)
        row.pack(fill="x", pady=(4, 0))
        ttk.Button(row, text="截圖 (Enter)", command=self.shot).pack(side="left")
        ttk.Button(row, text="開啟截圖資料夾", command=self.open_folder).pack(side="left", padx=4)
        self.whole_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(f, text="整個視窗（含黑邊，16:9 的廣告用）", variable=self.whole_var,
                        command=self._whole_changed).pack(anchor="w", pady=(4, 0))
        self.live_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(f, text="即時預覽", variable=self.live_var).pack(anchor="w", pady=(4, 0))
        self.live_var.trace_add("write", lambda *a: self._draw_paused())

        # 連拍
        f = ttk.LabelFrame(side, text="連拍", padding=6)
        f.pack(fill="x", pady=(8, 0))
        row = ttk.Frame(f)
        row.pack(fill="x")
        ttk.Label(row, text="每").pack(side="left")
        self.burst_ms = tk.IntVar(value=100)
        ttk.Spinbox(row, from_=30, to=5000, increment=10, textvariable=self.burst_ms, width=6).pack(side="left")
        ttk.Label(row, text="毫秒，連拍").pack(side="left")
        self.burst_sec = tk.DoubleVar(value=5)
        ttk.Spinbox(row, from_=1, to=120, increment=1, textvariable=self.burst_sec, width=5).pack(side="left")
        ttk.Label(row, text="秒").pack(side="left")
        row = ttk.Frame(f)
        row.pack(fill="x", pady=(4, 0))
        self.burst_btn = ttk.Button(row, text="開始連拍", command=self.burst)
        self.burst_btn.pack(side="left")
        ttk.Button(row, text="測速", command=self.bench).pack(side="left", padx=4)
        ttk.Button(row, text="縮放診斷", command=self.diagnose).pack(side="left")

        # 框選 / 樣板
        f = ttk.LabelFrame(side, text="框選與樣板", padding=6)
        f.pack(fill="x", pady=(8, 0))
        ttk.Button(f, text="開啟圖片…", command=self.open_image).pack(anchor="w")
        self.hover_var = tk.StringVar(value="游標：-")
        ttk.Label(f, textvariable=self.hover_var).pack(anchor="w", pady=(4, 0))
        self.sel_var = tk.StringVar(value="框選：在圖上拖曳")
        ttk.Label(f, textvariable=self.sel_var, wraplength=260, justify="left").pack(anchor="w")
        row = ttk.Frame(f)
        row.pack(fill="x", pady=(4, 0))
        ttk.Button(row, text="複製 region", command=self.copy_region).pack(side="left")
        ttk.Button(row, text="複製中心點", command=self.copy_center).pack(side="left", padx=4)
        ttk.Label(f, text="樣板名稱").pack(anchor="w", pady=(6, 0))
        self.tpl_var = tk.StringVar()
        ttk.Entry(f, textvariable=self.tpl_var, width=28).pack(fill="x")
        self.tpl_dir_var = tk.StringVar(value=self._short(self.tpl_dir))
        ttk.Label(f, textvariable=self.tpl_dir_var, foreground="#555", wraplength=260).pack(anchor="w")
        row = ttk.Frame(f)
        row.pack(fill="x", pady=(4, 0))
        ttk.Button(row, text="選資料夾…", command=self.pick_tpl_dir).pack(side="left")
        ttk.Button(row, text="存成樣板", command=self.save_template).pack(side="left", padx=4)
        ttk.Button(row, text="測試找圖", command=self.test_find).pack(side="left")

        # 點擊模式
        f = ttk.LabelFrame(side, text="在預覽圖上滑鼠左鍵的作用", padding=6)
        f.pack(fill="x", pady=(8, 0))
        self.mode = tk.StringVar(value="select")
        ttk.Radiobutton(f, text="框選範圍", variable=self.mode, value="select").pack(anchor="w")
        ttk.Radiobutton(f, text="點擊測試（送到遊戲）", variable=self.mode, value="click").pack(anchor="w")
        ttk.Radiobutton(f, text="拖曳測試（按住拖動，送到遊戲）", variable=self.mode, value="drag").pack(anchor="w")
        ttk.Radiobutton(f, text="滾輪測試（在預覽圖上滾滾輪，送到遊戲）", variable=self.mode, value="wheel").pack(anchor="w")
        ttk.Label(f, text="※ 測試會真的點到遊戲，別點購買類按鈕", foreground="#a33").pack(anchor="w")

        self.msg = tk.StringVar(value="")
        ttk.Label(side, textvariable=self.msg, wraplength=270, justify="left").pack(anchor="w", pady=(10, 0))

    def _short(self, p):
        try:
            rel = os.path.relpath(p, paths.ROOT)
            return "存到：" + ("專案根目錄" if rel == "." else rel)
        except ValueError:
            return "存到：" + p

    def _grab(self):
        """遊戲畫面；勾了「整個視窗」就是整個子視窗（含黑邊）。"""
        return self.game.capture_window() if self.whole_var.get() else self.game.capture()

    def _whole_changed(self):
        self.sel = None
        if self.whole_var.get():
            self.say("現在截的是整個視窗（含黑邊）。比例座標以整個視窗為準，點擊測試用 click_window。\n"
                     "16:9 的廣告請用這個模式截，檔名例：廣告16比9_略過")
        else:
            self.say("現在截的是遊戲畫面（去黑邊）。")

    def say(self, text):
        self.msg.set(text)

    # ------------------------------------------------------------ 視窗
    def refresh_windows(self):
        self.windows = Game.list_windows()
        self.win_box["values"] = [w.title for w in self.windows]
        if self.windows:
            self.win_box.current(0)
            self.connect_selected()
        else:
            self.win_var.set("")
            self.status.set("找不到遊戲視窗，打開遊戲後按「重新尋找」")

    def connect_selected(self):
        i = self.win_box.current()
        if i < 0:
            return
        self.game.connect(self.windows[i])
        self.game.reset_box()
        self.update_status()

    def update_status(self):
        ok, why = self.game.is_ready()
        if not ok:
            self.status.set("⚠ " + why)
            return False
        b = self.game.game_box
        aw, pct, sc = self.game.dpi_info()
        dpi = f"　縮放 {pct}%" + (f"（換算 ×{sc:.2f}）" if sc != 1.0 else "")
        if b:
            self.status.set(f"遊戲畫面 {b[2] - b[0]}×{b[3] - b[1]}（位置 {b[0]},{b[1]}）{dpi}")
        else:
            self.status.set("已連接" + dpi)
        return True

    # ------------------------------------------------------------ 顯示
    def show(self, img, name=""):
        self.image = img
        self.image_name = name
        h, w = img.shape[:2]
        dw, dh = max(1, int(w * self.scale)), max(1, int(h * self.scale))
        small = cv2.resize(img, (dw, dh), interpolation=cv2.INTER_AREA)
        ok, buf = cv2.imencode(".png", small)
        self._photo = tk.PhotoImage(data=base64.b64encode(buf.tobytes()))
        self.canvas.config(width=dw, height=dh)
        self.canvas.delete("img")
        self.canvas.create_image(0, 0, image=self._photo, anchor="nw", tags="img")
        self.canvas.tag_lower("img")
        self._draw_sel()
        self._draw_paused()

    def _draw_paused(self):
        """即時預覽關掉時，在預覽圖左上角顯示提示，避免以為畫面卡住。"""
        self.canvas.delete("paused")
        if self.live_var.get() or self.image is None:
            return
        t = self.canvas.create_text(8, 8, text="⏸ 已暫停即時預覽（勾選右邊「即時預覽」恢復）",
                                    anchor="nw", fill="#fff", tags="paused")
        x0, y0, x1, y1 = self.canvas.bbox(t)
        r = self.canvas.create_rectangle(x0 - 4, y0 - 3, x1 + 4, y1 + 3, fill="#c0392b", outline="", tags="paused")
        self.canvas.tag_raise(t, r)

    def _preview_loop(self):
        try:
            if self.live_var.get() and not self.busy and self.game.window:
                try:
                    self.show(self._grab(), "即時預覽")
                    self.update_status()
                except GameNotReady as e:
                    self.status.set("⚠ " + str(e))
        finally:
            self.root.after(PREVIEW_MS, self._preview_loop)

    # ------------------------------------------------------------ 截圖 / 連拍
    def shot(self):
        try:
            frame = self._grab()
        except GameNotReady as e:
            messagebox.showwarning("截圖", str(e))
            return
        name = safe_name(self.name_var.get(), datetime.datetime.now().strftime("%H%M%S"))
        path = unique_path(paths.SCREENSHOT_DIR, name)
        vision.imwrite(path, frame)
        self.live_var.set(False)
        self.show(frame, os.path.basename(path))
        self.say(f"✓ 已存：截圖\\{os.path.basename(path)}（{frame.shape[1]}×{frame.shape[0]}）\n已暫停即時預覽，可直接框選。")
        self.name_var.set("")

    def burst(self):
        if self.busy:
            return
        try:
            interval = max(0.03, self.burst_ms.get() / 1000)
            seconds = max(0.5, float(self.burst_sec.get()))
        except (tk.TclError, ValueError):
            messagebox.showwarning("連拍", "請輸入數字")
            return
        ok, why = self.game.is_ready()
        if not ok:
            messagebox.showwarning("連拍", why)
            return
        name = safe_name(self.name_var.get(), "連拍")
        folder = os.path.join(paths.SCREENSHOT_DIR, f"{name}_{datetime.datetime.now():%m%d_%H%M%S}")
        os.makedirs(folder, exist_ok=True)
        self.busy = True
        self.burst_btn.config(state="disabled")
        self.say("連拍中…")

        def work():
            frames, t0 = [], time.perf_counter()
            nxt = t0
            err = None
            try:
                while time.perf_counter() - t0 < seconds:
                    t = time.perf_counter()
                    frames.append((int((t - t0) * 1000), self._grab()))
                    nxt += interval
                    time.sleep(max(0.0, nxt - time.perf_counter()))
            except GameNotReady as e:
                err = str(e)
            # 先全部截完再存檔，存檔不會拖慢連拍
            for i, (ms, f) in enumerate(frames):
                vision.imwrite(os.path.join(folder, f"{i:04d}_{ms:06d}ms.png"), f)
            self.root.after(0, done, frames, err)

        def done(frames, err):
            self.busy = False
            self.burst_btn.config(state="normal")
            n = len(frames)
            real = (frames[-1][0] / max(1, n - 1)) if n > 1 else 0
            text = f"✓ 連拍 {n} 張，實際平均間隔 {real:.0f} 毫秒\n存在：截圖\\{os.path.basename(folder)}"
            if err:
                text += f"\n⚠ 中途停止：{err}"
            self.say(text)

        threading.Thread(target=work, daemon=True).start()

    def bench(self):
        try:
            self._grab()
            ts = []
            for _ in range(20):
                t = time.perf_counter()
                self._grab()
                ts.append((time.perf_counter() - t) * 1000)
        except GameNotReady as e:
            messagebox.showwarning("測速", str(e))
            return
        ts.sort()
        self.say(f"截圖＋正規化 20 次：平均 {sum(ts) / len(ts):.1f} ms，最快 {ts[0]:.1f}，最慢 {ts[-1]:.1f} ms\n（目標 < 50 ms）")

    def open_folder(self):
        os.makedirs(paths.SCREENSHOT_DIR, exist_ok=True)
        if sys.platform == "win32":
            os.startfile(paths.SCREENSHOT_DIR)

    def open_image(self):
        p = filedialog.askopenfilename(initialdir=paths.SCREENSHOT_DIR if os.path.isdir(paths.SCREENSHOT_DIR) else paths.ROOT,
                                       filetypes=[("圖片", "*.png *.jpg *.bmp")])
        if not p:
            return
        img = vision.imread(p)
        if img.shape[0] != 1000:
            # 不是正規化畫面（例如舊截圖工具截的整個視窗）→ 自動去黑邊並正規化
            from core import capture as cap
            if self.whole_var.get():
                box = (0, 0, img.shape[1], img.shape[0])
            else:
                box, _ = cap.detect_game_box(img)
            img = cap.normalize(img, box)
            self.say("這張不是正規化畫面，已自動去黑邊、縮放成高度 1000。")
        self.live_var.set(False)
        self.sel = None
        self.show(img, os.path.basename(p))

    # ------------------------------------------------------------ 滑鼠
    def _img_xy(self, ev):
        if self.image is None:
            return None
        h, w = self.image.shape[:2]
        x = min(w - 1, max(0, int(ev.x / self.scale)))
        y = min(h - 1, max(0, int(ev.y / self.scale)))
        return x, y

    def _on_hover(self, ev):
        p = self._img_xy(ev)
        if not p:
            return
        h, w = self.image.shape[:2]
        b, g, r = (int(v) for v in self.image[p[1], p[0]])
        self.hover_var.set(f"游標：({p[0] / w:.3f}, {p[1] / h:.3f})  像素 {p[0]},{p[1]}  BGR {b},{g},{r}")

    def _on_down(self, ev):
        self._drag_start = self._img_xy(ev)
        if self.mode.get() == "select" and self._drag_start:
            self.live_var.set(False)

    def _on_move_drag(self, ev):
        self._on_hover(ev)
        p = self._img_xy(ev)
        if not (self._drag_start and p):
            return
        if self.mode.get() == "select":
            self.sel = (*self._drag_start, *p)
            self._draw_sel()
        elif self.mode.get() == "drag":
            self.canvas.delete("dragline")
            s = self.scale
            self.canvas.create_line(self._drag_start[0] * s, self._drag_start[1] * s, ev.x, ev.y,
                                    fill="#0f0", width=2, arrow="last", tags="dragline")

    def _on_up(self, ev):
        p = self._img_xy(ev)
        start, self._drag_start = self._drag_start, None
        if not (start and p) or self.image is None:
            return
        h, w = self.image.shape[:2]
        mode = self.mode.get()
        if mode == "select":
            x0, x1 = sorted((start[0], p[0]))
            y0, y1 = sorted((start[1], p[1]))
            if x1 - x0 < 3 or y1 - y0 < 3:
                self.sel = None
                self.sel_var.set("框選：在圖上拖曳")
            else:
                self.sel = (x0, y0, x1 + 1, y1 + 1)
            self._draw_sel()
        elif mode == "click":
            click = self.game.click_window if self.whole_var.get() else self.game.click
            self._send(lambda: click(p[0] / w, p[1] / h),
                       f"已送出點擊 ({p[0] / w:.3f}, {p[1] / h:.3f})")
        elif mode == "drag":
            self.canvas.delete("dragline")
            a = (start[0] / w, start[1] / h, p[0] / w, p[1] / h)
            self._send(lambda: self.game.drag(*a, seconds=0.4),
                       "已送出拖曳 ({:.3f}, {:.3f}) → ({:.3f}, {:.3f})".format(*a))

    def _on_wheel(self, ev):
        if self.mode.get() != "wheel":
            return
        p = self._img_xy(ev)
        if not p:
            return
        h, w = self.image.shape[:2]
        n = 1 if ev.delta > 0 else -1
        self._send(lambda: self.game.scroll(p[0] / w, p[1] / h, n),
                   f"已送出滾輪 {'上' if n > 0 else '下'} 1 格 ({p[0] / w:.3f}, {p[1] / h:.3f})")

    def diagnose(self):
        """縮放問題診斷：用三種 DPI 座標系各截一次，存圖和數據。"""
        import contextlib
        import ctypes
        import platform
        from core import _win32 as w
        from core.capture import Grabber
        gw = self.game.window
        ok, why = self.game.is_ready()
        if not ok:
            messagebox.showwarning("縮放診斷", why)
            return
        folder = os.path.join(paths.SCREENSHOT_DIR, f"診斷_{datetime.datetime.now():%m%d_%H%M%S}")
        os.makedirs(folder, exist_ok=True)
        lines = [f"core v{__version__}　Windows {platform.version()}",
                 f"視窗：{gw.title}",
                 f"主視窗 DPI 感知 {w.window_dpi_awareness(gw.root)}，DPI {w.window_dpi(gw.root)}",
                 f"子視窗 DPI 感知 {w.window_dpi_awareness(gw.child)}，DPI {w.window_dpi(gw.child)}",
                 f"螢幕 DPI {w.monitor_dpi(gw.root)}，換算倍數 {w.window_scale(gw.child):.3f}",
                 "（感知 0 = 不支援縮放、1 = 系統、2 = 每個螢幕）", ""]
        modes = [("程式本身", None), ("跟子視窗", gw.child), ("跟主視窗", gw.root)]
        for tag, h in modes:
            with (w.same_dpi_as(h) if h else contextlib.nullcontext()):
                r = w.wt.RECT(); w.user32.GetWindowRect(gw.root, ctypes.byref(r))
                c = w.wt.RECT(); w.user32.GetClientRect(gw.child, ctypes.byref(c))
                o = w.wt.POINT(0, 0); w.user32.ClientToScreen(gw.child, ctypes.byref(o))
                g = Grabber()
                img = g._grab(gw.root, gw.child, w.window_scale(gw.child))
                full = g._buf[:, :, :3].copy() if g._buf is not None else None
                g.close()
            lines.append(f"[{tag}] 主視窗 {r.left},{r.top}-{r.right},{r.bottom}（{r.right - r.left}×{r.bottom - r.top}）"
                         f"　子視窗內容區 {c.right}×{c.bottom}　子視窗左上 {o.x},{o.y}")
            if full is not None:
                vision.imwrite(os.path.join(folder, f"{tag}_主視窗.png"), full)
            if img is not None:
                vision.imwrite(os.path.join(folder, f"{tag}_子視窗.png"), img)
            else:
                lines.append("    截圖失敗")
        with open(os.path.join(folder, "診斷結果.txt"), "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        self.say(f"✓ 診斷完成，存在：截圖\\{os.path.basename(folder)}\n跟 Claude 說一聲就好。")

    def _send(self, fn, text):
        try:
            fn()
        except GameNotReady as e:
            messagebox.showwarning("測試", str(e))
            return
        self.say(text + "\n1 秒後自動截圖，請看遊戲有沒有反應。")
        self.root.after(1000, self._after_test)

    def _after_test(self):
        try:
            self.show(self._grab(), "測試後")
        except GameNotReady:
            pass

    def _draw_sel(self):
        self.canvas.delete("sel")
        if not self.sel or self.image is None:
            return
        x0, y0, x1, y1 = self.sel
        s = self.scale
        self.canvas.create_rectangle(x0 * s, y0 * s, x1 * s, y1 * s, outline="#ff3b3b", width=2, tags="sel")
        h, w = self.image.shape[:2]
        x0, x1 = sorted((x0, x1))
        y0, y1 = sorted((y0, y1))
        self.sel_var.set(f"框選：region=({x0 / w:.3f}, {y0 / h:.3f}, {x1 / w:.3f}, {y1 / h:.3f})\n"
                         f"中心 ({(x0 + x1) / 2 / w:.3f}, {(y0 + y1) / 2 / h:.3f})，大小 {x1 - x0}×{y1 - y0} 像素")

    def _norm_sel(self):
        if not self.sel or self.image is None:
            return None
        x0, y0, x1, y1 = self.sel
        x0, x1 = sorted((x0, x1))
        y0, y1 = sorted((y0, y1))
        return x0, y0, x1, y1

    def _clip(self, text):
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.say(f"已複製：{text}")

    def copy_region(self):
        s = self._norm_sel()
        if s:
            h, w = self.image.shape[:2]
            self._clip(f"region=({s[0] / w:.3f}, {s[1] / h:.3f}, {s[2] / w:.3f}, {s[3] / h:.3f})")

    def copy_center(self):
        s = self._norm_sel()
        if s:
            h, w = self.image.shape[:2]
            self._clip(f"{(s[0] + s[2]) / 2 / w:.3f}, {(s[1] + s[3]) / 2 / h:.3f}")

    def pick_tpl_dir(self):
        d = filedialog.askdirectory(initialdir=self.tpl_dir)
        if d:
            self.tpl_dir = d
            self.tpl_dir_var.set(self._short(d))

    def save_template(self):
        s = self._norm_sel()
        if not s:
            messagebox.showinfo("存成樣板", "請先在圖上框選範圍（模式選「框選範圍」）")
            return
        name = safe_name(self.tpl_var.get(), "")
        if not name:
            messagebox.showinfo("存成樣板", "請輸入樣板名稱")
            return
        path = os.path.join(self.tpl_dir, name + ".png")
        if os.path.exists(path) and not messagebox.askyesno("存成樣板", f"{name}.png 已存在，要覆蓋嗎？"):
            return
        crop = self.image[s[1]:s[3], s[0]:s[2]].copy()
        vision.imwrite(path, crop)
        vision.clear_cache()
        self.say(f"✓ 已存樣板：{name}.png（{crop.shape[1]}×{crop.shape[0]}）\n{path}")

    def test_find(self):
        if self.image is None:
            return
        p = filedialog.askopenfilename(initialdir=self.tpl_dir, title="選一張樣板，在目前畫面上找",
                                       filetypes=[("圖片", "*.png")])
        if not p:
            return
        vision.clear_cache()
        ms = vision.find_all(self.image, p, threshold=0.7, max_results=10)
        best = vision.best_score(self.image, p)
        self.canvas.delete("found")
        h, w = self.image.shape[:2]
        s = self.scale
        for m in ms:
            x0, y0 = (m.x - m.w / 2) * w * s, (m.y - m.h / 2) * h * s
            x1, y1 = (m.x + m.w / 2) * w * s, (m.y + m.h / 2) * h * s
            self.canvas.create_rectangle(x0, y0, x1, y1, outline="#3bff6b", width=2, tags="found")
            self.canvas.create_text(x0, y0 - 2, text=f"{m.score:.2f}", fill="#3bff6b", anchor="sw", tags="found")
        lines = [f"最高分 {best:.3f}，分數 ≥ 0.70 的有 {len(ms)} 個"]
        lines += [f"  ({m.x:.3f}, {m.y:.3f}) 分數 {m.score:.3f}" for m in ms[:5]]
        self.say("\n".join(lines))


def main():
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    root = tk.Tk()
    try:
        CaptureTool(root)
    except Exception as e:
        messagebox.showerror("截圖工具", repr(e))
        raise
    root.mainloop()


if __name__ == "__main__":
    main()
