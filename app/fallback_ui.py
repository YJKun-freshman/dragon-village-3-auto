# -*- coding: utf-8 -*-
"""
臨時介面：正式介面（ui/，由「Tkinter外型」對話製作）完成前使用。
介面方法和 02_Tkinter外型.md 約定的一樣，可以直接換成正式版。
"""
import datetime
import queue
import tkinter as tk
from tkinter import ttk


class _Tip:
    def __init__(self, widget, text):
        self.w, self.text, self.tip = widget, text, None
        widget.bind("<Enter>", self.show)
        widget.bind("<Leave>", self.hide)

    def show(self, _):
        if not self.text or self.tip:
            return
        x, y = self.w.winfo_rootx() + 10, self.w.winfo_rooty() + self.w.winfo_height() + 4
        self.tip = tk.Toplevel(self.w)
        self.tip.wm_overrideredirect(True)
        self.tip.geometry(f"+{x}+{y}")
        tk.Label(self.tip, text=self.text, bg="#ffffe0", relief="solid", borderwidth=1,
                 padx=6, pady=3, justify="left").pack()

    def hide(self, _):
        if self.tip:
            self.tip.destroy()
            self.tip = None


class MainWindow:
    def __init__(self, title, tasks, on_start, on_stop, saved_values=None, selected=None):
        self.tasks = {tuple(t["path"]): t for t in tasks}
        self.on_start, self.on_stop = on_start, on_stop
        self.values = {p: dict(v) for p, v in (saved_values or {}).items()}
        self.current = None
        self.vars = {}
        self.running = False
        self._q = queue.Queue()

        self.root = tk.Tk()
        self.root.title(title + "（臨時介面）")
        self.root.geometry("820x600")
        self.root.minsize(640, 460)
        self.root.report_callback_exception = self._tk_error
        self._build()
        for path in self.tasks:
            self._add_tree(path)
        if selected and tuple(selected) in self.tasks:
            iid = "/".join(selected)
            self.tree.see(iid)
            self.tree.selection_set(iid)
        self.root.bind("<F5>", lambda e: self.request_start())
        self.root.bind("<F6>", lambda e: self.request_stop())
        self.root.after(50, self._poll)

    # ------------------------------------------------------------ 版面
    def _build(self):
        top = ttk.PanedWindow(self.root, orient="vertical")
        top.pack(fill="both", expand=True, padx=6, pady=6)
        upper = ttk.PanedWindow(top, orient="horizontal")
        top.add(upper, weight=3)

        self.tree = ttk.Treeview(upper, show="tree", selectmode="browse")
        upper.add(self.tree, weight=1)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)

        right = ttk.Frame(upper, padding=(10, 0, 0, 0))
        upper.add(right, weight=3)
        self.title_var = tk.StringVar(value="← 選擇任務")
        ttk.Label(right, textvariable=self.title_var, font=("Microsoft JhengHei UI", 13, "bold")).pack(anchor="w")
        self.desc_var = tk.StringVar()
        ttk.Label(right, textvariable=self.desc_var, wraplength=480, justify="left").pack(anchor="w", pady=(2, 8))
        self.param_box = ttk.LabelFrame(right, text="參數設定", padding=8)
        self.param_box.pack(fill="x")
        btns = ttk.Frame(right)
        btns.pack(anchor="w", pady=10)
        self.start_btn = ttk.Button(btns, text="▶ 開始 (F5)", command=self.request_start)
        self.start_btn.pack(side="left")
        self.stop_btn = ttk.Button(btns, text="■ 停止 (F6)", command=self.request_stop, state="disabled")
        self.stop_btn.pack(side="left", padx=6)
        self.err_var = tk.StringVar()
        ttk.Label(right, textvariable=self.err_var, foreground="#c0392b").pack(anchor="w")

        logf = ttk.Frame(top)
        top.add(logf, weight=2)
        bar = ttk.Frame(logf)
        bar.pack(fill="x")
        ttk.Label(bar, text="日誌").pack(side="left")
        ttk.Button(bar, text="清除", command=lambda: self.log.delete("1.0", "end")).pack(side="right")
        self.log = tk.Text(logf, height=10, wrap="word", font=("Microsoft JhengHei UI", 9))
        sb = ttk.Scrollbar(logf, command=self.log.yview)
        self.log.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.log.pack(fill="both", expand=True)
        self.log.tag_configure("warn", foreground="#b9770e")
        self.log.tag_configure("error", foreground="#c0392b")

        status = ttk.Frame(self.root, padding=(6, 2))
        status.pack(fill="x")
        self.game_var = tk.StringVar(value="● 遊戲：檢查中…")
        self.game_lbl = ttk.Label(status, textvariable=self.game_var)
        self.game_lbl.pack(side="left")
        self.state_var = tk.StringVar(value="│ 狀態：停止")
        ttk.Label(status, textvariable=self.state_var).pack(side="left", padx=8)
        self.prog_var = tk.StringVar()
        ttk.Label(status, textvariable=self.prog_var).pack(side="left")
        self.time_var = tk.StringVar()
        ttk.Label(status, textvariable=self.time_var).pack(side="right")
        self._t0 = None

    def _add_tree(self, path):
        for i in range(len(path)):
            iid = "/".join(path[:i + 1])
            if not self.tree.exists(iid):
                parent = "/".join(path[:i]) if i else ""
                self.tree.insert(parent, "end", iid=iid, text=path[i], open=True)

    def _on_select(self, _=None):
        if self.running:
            return
        sel = self.tree.selection()
        path = tuple(sel[0].split("/")) if sel else None
        if path not in self.tasks:
            return
        self._store_current()
        self.current = path
        t = self.tasks[path]
        self.title_var.set(path[-1])
        self.desc_var.set(t["description"])
        for w in self.param_box.winfo_children():
            w.destroy()
        self.vars = {}
        saved = self.values.get(path, {})
        for r, p in enumerate(t["params"]):
            ttk.Label(self.param_box, text=p["label"]).grid(row=r, column=0, sticky="w", pady=2)
            val = saved.get(p["key"], p["default"])
            if p["type"] is bool:
                v = tk.BooleanVar(value=bool(val))
                w = ttk.Checkbutton(self.param_box, variable=v)
            elif p["choices"]:
                v = tk.StringVar(value=str(val))
                w = ttk.Combobox(self.param_box, textvariable=v, values=[str(c) for c in p["choices"]],
                                 state="readonly", width=14)
            elif p["type"] in (int, float):
                v = tk.StringVar(value=str(val))
                w = ttk.Spinbox(self.param_box, textvariable=v, width=12,
                                from_=p["min"] if p["min"] is not None else -1e9,
                                to=p["max"] if p["max"] is not None else 1e9,
                                increment=1 if p["type"] is int else 0.1)
            else:
                v = tk.StringVar(value=str(val))
                w = ttk.Entry(self.param_box, textvariable=v, width=20)
            w.grid(row=r, column=1, sticky="w", padx=8, pady=2)
            if p["help"]:
                _Tip(w, p["help"])
            self.vars[p["key"]] = (v, p)

    def _read(self):
        """讀目前參數；有錯回傳 (None, 錯誤訊息)。"""
        out = {}
        for key, (v, p) in self.vars.items():
            raw = v.get()
            if p["type"] in (int, float):
                try:
                    val = p["type"](str(raw).strip())
                except ValueError:
                    return None, f"「{p['label']}」要填{'整數' if p['type'] is int else '數字'}"
                if p["min"] is not None and val < p["min"]:
                    return None, f"「{p['label']}」不能小於 {p['min']}"
                if p["max"] is not None and val > p["max"]:
                    return None, f"「{p['label']}」不能大於 {p['max']}"
            elif p["choices"]:
                val = next((c for c in p["choices"] if str(c) == raw), p["default"])
            else:
                val = raw
            out[key] = val
        return out, ""

    def _store_current(self):
        if self.current:
            vals, _ = self._read()
            if vals is not None:
                self.values[self.current] = vals

    # ------------------------------------------------------------ 執行緒安全（排進佇列，由 Tk 主執行緒處理）
    def _call(self, fn, *args):
        self._q.put((fn, args))

    def _poll(self):
        try:
            while True:
                fn, args = self._q.get_nowait()
                fn(*args)
        except queue.Empty:
            pass
        if self._t0 and self.running:
            s = int((datetime.datetime.now() - self._t0).total_seconds())
            self.time_var.set(f"{s // 3600:d}:{s // 60 % 60:02d}:{s % 60:02d}")
        self.root.after(100, self._poll)

    def _tk_error(self, exc, val, tb):
        import logging
        logging.getLogger("ui").error("介面錯誤：%s", val, exc_info=(exc, val, tb))

    # ------------------------------------------------------------ 約定的方法
    def append_log(self, text, level="info"):
        self._call(self._append_log, text, level)

    def _append_log(self, text, level):
        line = f"{datetime.datetime.now():%H:%M:%S} {text}\n"
        self.log.insert("end", line, (level,) if level in ("warn", "error") else ())
        self.log.see("end")

    def set_running(self, running):
        self._call(self._set_running, bool(running))

    def _set_running(self, running):
        self.running = running
        self.start_btn.config(state="disabled" if running else "normal")
        self.stop_btn.config(state="normal" if running else "disabled")
        self.state_var.set("│ 狀態：" + ("執行中" if running else "停止"))
        state = "disabled" if running else "!disabled"
        for w in self.param_box.winfo_children():
            try:
                w.state([state])
            except tk.TclError:
                pass
        if running:
            self._t0 = datetime.datetime.now()
        else:
            self.prog_var.set("")

    def set_game_status(self, text, ok):
        self._call(lambda: (self.game_var.set(("● 遊戲：" if ok else "○ 遊戲：") + text),
                            self.game_lbl.configure(foreground="#1e8449" if ok else "#c0392b")))

    def set_progress(self, text):
        self._call(lambda: self.prog_var.set(f"│ {text}" if text else ""))

    def get_values(self):
        self._store_current()
        return {p: dict(v) for p, v in self.values.items()}

    def request_start(self):
        """按開始或 F5：檢查參數後呼叫 on_start。可從背景執行緒呼叫。"""
        self._call(self._do_start)

    def request_stop(self):
        self._call(self.on_stop)

    def _do_start(self):
        if self.running:
            return
        if not self.current:
            self.err_var.set("請先在左邊選擇一個任務")
            return
        vals, err = self._read()
        self.err_var.set(err)
        if vals is None:
            return
        self.values[self.current] = vals
        self.set_running(True)            # 先鎖住按鈕；on_start 失敗時主程式會 set_running(False)
        self.on_start(self.current, vals)

    def run(self):
        self.root.mainloop()
