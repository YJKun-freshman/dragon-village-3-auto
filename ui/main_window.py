# -*- coding: utf-8 -*-
"""
主視窗。介面約定見 02_Tkinter外型.md「與主程式的介面」。

版面（左右排）：
    ┌ 標題列 ─────────────────────────────────────────────┐
    │ 功能樹 │ 設定（可捲動）＋ 開始／停止 │ 日誌              │
    └ 狀態列 ─────────────────────────────────────────────┘

參數區自動摺疊成「摘要列」的時機：執行中，或視窗寬度 < NARROW。
摺疊時可以按「展開參數」暫時打開；開始／停止或視窗寬度改變時恢復自動。
"""
import ctypes
import datetime
import logging
import queue
import re
import tkinter as tk

import customtkinter as ctk

from . import theme
from .theme import C, F, L, M, S, XL, XS, Box, card, label, outline_button, primary_button, px
from .widgets import LogView, ParamForm, ScrollFrame, TaskTree, Tooltip, split_unit
from .sequence_editor import SequenceEditor
from .dialogs import AddItemDialog, ConfirmDialog, unique_name, validate_name
from .settings_dialog import DEFAULT_HOTKEYS, SettingsDialog, normalize as normalize_hotkey, tk_sequence

log = logging.getLogger("ui")

NARROW = 1000          # 視窗寬度（未縮放的像素）小於這個值就摺疊參數區
SETTINGS_W = 460       # 設定欄寬度
TREE_W = 210           # 功能樹寬度
SIZES = {"full": (1240, 800), "compact": (780, 640)}    # 完整／精簡模式的預設大小
RELAYOUT_DELAY = 100   # 調整視窗大小停下多久（毫秒）後才重排內容


class MainWindow:
    def __init__(self, title, tasks, on_start, on_stop, saved_values=None, selected=None,
                 sequence_tools=None, on_open_logs=None, window_state=None, settings=None,
                 task_groups=None, task_editor=None):
        """
        title           視窗標題，例「龍村3 自動腳本 v0.1.0」
        tasks           [{"path", "description", "params": [{key, label, type, default, min, max, choices, help, widget}]}]
        on_start        on_start(path, values)
        on_stop         on_stop()
        saved_values    {path(tuple): {key: 值}}
        selected        上次選的任務路徑
        sequence_tools  {"parse", "to_text", "validate"}（combat.sequence），有才顯示出招流程編輯器
        on_open_logs    開啟日誌資料夾（沒給就不顯示按鈕）
        task_groups     [{"path", "id", "name"}]：自訂項目的類型資料夾（沒有項目也顯示）
        task_editor     {"add", "rename", "delete", "move"}：功能樹編輯（見 02「自訂戰鬥項目」）；沒給就不能編輯
        settings        設定選單的資料與回呼（見 02「設定選單（定案）」）；沒給的項目不顯示
        window_state    上次的視窗狀態（get_window_state() 的回傳值），用來還原大小、位置、精簡／完整模式
        """
        self.tasks = {tuple(t["path"]): t for t in tasks}
        self.on_start, self.on_stop = on_start, on_stop
        self.sequence_tools = sequence_tools
        self.on_open_logs = on_open_logs
        self.settings_cfg = dict(settings or {})       # 設定選單（self.settings 是設定卡片）
        self.hotkeys = dict(DEFAULT_HOTKEYS)
        self.hotkeys.update({k: normalize_hotkey(v)[0] or v for k, v in (self.settings_cfg.get("hotkeys") or {}).items()})
        self._key_binds = []
        self.dialog = None
        self._modal = None
        self.task_editor = dict(task_editor or {})
        self.groups = [tuple(g["path"]) for g in (task_groups or []) if g.get("path")]
        self.group_names = {tuple(g["path"]): g.get("name") or g["path"][-1] for g in (task_groups or []) if g.get("path")}
        self._rename_entry = None
        self.title = title
        # 每個任務的參數：values = 最近一次正確的值（給 get_values）；drafts = 畫面上的內容（切換任務時保留）
        self.values = {}
        for path, t in self.tasks.items():
            saved = dict((saved_values or {}).get(path, {}))
            self.values[path] = {p["key"]: saved.get(p["key"], p["default"]) for p in t["params"]}
        self.drafts = {}
        self.current = None
        self.form = None
        self.running = False
        self.narrow = False
        self.expanded = False         # 摺疊時使用者按了「展開參數」
        self.view = None
        self._t0 = None
        self._q = queue.Queue()
        self._resize_job = None

        theme.ctk.set_appearance_mode("dark")
        self.root = ctk.CTk(fg_color=C["bg"])
        theme.init(self.root)
        self.scale = ctk.ScalingTracker.get_window_scaling(self.root)
        self.root.title(title)
        self._restore_window(window_state)
        self.root.minsize(720, 520)
        self.root.report_callback_exception = self._tk_error
        self.root.protocol("WM_DELETE_WINDOW", self._close)
        theme.set_scale(self.scale)
        theme.style_ttk(self.root)

        self._build()
        target = tuple(selected) if selected and tuple(selected) in self.tasks else self.tree.first_task()
        if target:
            self.tree.select(target)
            self._select(target)
        else:
            self._select(None)
        self._apply_layout()
        self._refresh_buttons()

        self._bind_hotkeys()
        self.root.bind("<Configure>", self._on_resize, add="+")
        self._jobs = {"poll": self.root.after(50, self._poll), "tick": self.root.after(1000, self._tick)}
        ctk.ScalingTracker.add_widget(self._on_scaling, self.root)     # Windows 顯示比例改變時

    # ================================================================ 版面
    # ---------------------------------------------------------------- 視窗大小、位置、精簡／完整模式
    def _screen_area(self):
        """可用的桌面範圍（未縮放的像素）：多螢幕時是所有螢幕合起來的範圍。"""
        sc = self.scale
        try:
            u = ctypes.windll.user32
            x, y, w, h = (u.GetSystemMetrics(i) for i in (76, 77, 78, 79))
            if w > 0 and h > 0:
                return x / sc, y / sc, w / sc, h / sc
        except Exception:
            pass
        return 0, 0, self.root.winfo_screenwidth() / sc, self.root.winfo_screenheight() / sc

    @staticmethod
    def _parse_geo(g):
        m = re.match(r"^(\d+)x(\d+)([+-]-?\d+)([+-]-?\d+)$", str(g or ""))
        return tuple(int(v) for v in m.groups()) if m else None

    def _fit(self, w, h, x=None, y=None):
        """把視窗限制在螢幕範圍內；位置看不到（例如換了螢幕）就置中。"""
        sx, sy, sw, sh = self._screen_area()
        w, h = int(min(max(w, 720), sw)), int(min(max(h, 520), sh - 40))
        if x is None or not (sx - w + 120 <= x <= sx + sw - 120 and sy <= y <= sy + sh - 80):
            x, y = sx + (sw - w) / 2, sy + (sh - h) / 3
        return f"{w}x{h}+{int(x)}+{int(y)}"

    def _restore_window(self, state):
        st = dict(state) if isinstance(state, dict) else {}
        self.mode = st.get("mode") if st.get("mode") in SIZES else "full"
        self._win = {"mode": self.mode, "zoomed": bool(st.get("zoomed")),
                     "full": st.get("full"), "compact": st.get("compact")}
        g = self._parse_geo(self._win.get(self.mode))
        geo = self._fit(*g) if g else self._fit(*SIZES[self.mode])
        self.root.geometry(geo)
        if self._win["zoomed"] and self.mode == "full":
            self.root.after(100, lambda: self._safe_state("zoomed"))

    def _safe_state(self, value):
        try:
            self.root.state(value)
        except tk.TclError:
            pass

    def _remember_window(self):
        try:
            state = self.root.state()
        except tk.TclError:
            return
        if state == "normal":
            self._win[self.mode] = self.root.geometry()
            self._win["zoomed"] = False
        elif state == "zoomed":
            self._win["zoomed"] = True

    def _toggle_mode(self):
        self._remember_window()
        if self.root.state() == "zoomed":
            self._safe_state("normal")
        cur = self._parse_geo(self.root.geometry())
        self.mode = "compact" if self.mode == "full" else "full"
        self._win["mode"] = self.mode
        g = self._parse_geo(self._win.get(self.mode))
        w, h = (g[0], g[1]) if g else SIZES[self.mode]
        x, y = (cur[2], cur[3]) if cur else (None, None)
        self.root.geometry(self._fit(w, h, x, y))
        self._update_mode_btn()

    def _update_mode_btn(self):
        self.mode_btn.configure(text="⇱ 完整模式" if self.mode == "compact" else "⇲ 精簡模式")

    def get_window_state(self):
        """給主程式存設定檔：{"mode", "full", "compact", "zoomed"}。視窗關掉後也可以呼叫。"""
        return dict(self._win)

    def _build(self):
        r = self.root
        r.grid_columnconfigure(0, weight=1)
        r.grid_rowconfigure(1, weight=1)

        # ---- 標題列
        head = Box(r, "bg")
        head.grid(row=0, column=0, sticky="ew", padx=XL, pady=(L, M))
        m = re.match(r"^(.*?)\s+v(\d[\w.\-]*)$", self.title)
        name, ver = (m.group(1), m.group(2)) if m else (self.title, "")
        label(head, name, F.title).pack(side="left")
        if ver:
            ctk.CTkLabel(head, text=f"v{ver}", font=F.tiny, text_color=C["sub"], fg_color=C["panel"],
                         corner_radius=9, height=18, width=50).pack(side="left", padx=(S, 0))
        outline_button(head, "⚙ 設定", self._open_settings, width=72).pack(side="right")
        self.mode_btn = outline_button(head, "", self._toggle_mode, width=96)
        self.mode_btn.pack(side="right", padx=(0, S))
        Tooltip(self.mode_btn, "切換視窗大小\n精簡：小視窗，只顯示任務、摘要和日誌，適合放在遊戲旁邊\n"
                               "完整：設定和日誌並排\n兩種模式會各自記住你調整過的大小")
        self._update_mode_btn()

        # ---- 中間
        # 拖曳邊框調整大小時，中間內容先不重排（place 固定大小），停下來再一次排好 → 不會卡
        self.stage = Box(r, "bg")
        self.stage.grid(row=1, column=0, sticky="nsew", padx=XL)
        body = self.body = Box(self.stage, "bg")
        body.place(x=0, y=0, width=1, height=1)
        self._stage_size, self._stage_job = None, None
        self.stage.bind("<Configure>", self._on_stage, add="+")
        body.grid_columnconfigure(1, weight=1)
        body.grid_rowconfigure(0, weight=1)

        tree_card = card(body, width=TREE_W)
        tree_card.grid(row=0, column=0, sticky="ns", padx=(0, L))
        tree_card.grid_propagate(False)
        tree_card.grid_rowconfigure(1, weight=1)
        tree_card.grid_columnconfigure(0, weight=1)
        label(tree_card, "任務", F.small, "sub").grid(row=0, column=0, sticky="w", padx=L, pady=(M, XS))
        editing = bool(self.task_editor and self.groups)
        self.tree = TaskTree(tree_card, list(self.tasks), self._select, self.scale, groups=self.groups,
                             on_context=self._tree_menu if editing else None,
                             on_hint=(lambda g: self._add_item(group=g)) if editing else None,
                             on_key=self._tree_key if editing else None)
        self.tree.rebuild(list(self.tasks), self.groups, self._editable())
        self.tree.widget.grid(row=1, column=0, sticky="nsew", padx=(S, S), pady=(0, S if editing else M))
        self.tree_card = tree_card
        if editing:
            self.add_btn = outline_button(tree_card, "＋ 新增項目", lambda: self._add_item(), height=30)
            self.add_btn.grid(row=2, column=0, sticky="ew", padx=M, pady=(0, M))
            Tooltip(self.add_btn, "在「戰鬥」的類型底下新增自己的項目\n也可以在項目上按右鍵：複製、改名、上下移、刪除")

        self.right = Box(body, "bg")
        self.right.grid(row=0, column=1, sticky="nsew")

        # 設定卡片
        self.settings = card(self.right, width=SETTINGS_W)
        self.settings.grid_rowconfigure(0, weight=1)
        self.settings.grid_columnconfigure(0, weight=1)
        self.settings.grid_propagate(False)
        self.scroll = ScrollFrame(self.settings, "panel")
        self.scroll.widget.grid(row=0, column=0, sticky="nsew", padx=(XS, 3), pady=(4, 0))
        self.scroll.inner.grid_columnconfigure(0, weight=1)
        inner = self.content = Box(self.scroll.inner, "panel")
        inner.grid(row=0, column=0, sticky="nsew", padx=(M, M), pady=(M, 0))
        inner.grid_columnconfigure(0, weight=1)
        top = Box(inner, "panel")
        top.grid(row=0, column=0, sticky="ew")
        top.grid_columnconfigure(0, weight=1)
        self.crumb = label(top, "", F.small, "sub", anchor="w")
        self.crumb.grid(row=0, column=0, sticky="w")
        self.collapse_btn = outline_button(top, "⇤ 收起", self._toggle_expand, width=60, height=26)
        self.task_title = label(top, "", F.h2, anchor="w")
        self.task_title.grid(row=1, column=0, sticky="w", pady=(2, 2))
        self.desc = label(inner, "", F.small, "sub", anchor="w", justify="left")
        self.desc.grid(row=1, column=0, sticky="ew", pady=(0, L))
        self.form_holder = Box(inner, "panel")
        self.form_holder.grid(row=2, column=0, sticky="ew", pady=(0, L))
        self.form_holder.grid_columnconfigure(0, weight=1)
        self.settings.bind("<Configure>", self._on_settings_resize, add="+")

        btns = self.btn_bar = Box(self.settings, "panel")
        btns.grid(row=1, column=0, sticky="ew", padx=L + XS, pady=(M, L))
        btns.grid_columnconfigure((0, 1), weight=1, uniform="b")
        self.start_btn = primary_button(btns, "", self.request_start)
        self.start_btn.grid(row=0, column=0, sticky="ew", padx=(0, S))
        self.stop_btn = outline_button(btns, "", self.request_stop, height=36, font=F.body_bold)
        self.stop_btn.grid(row=0, column=1, sticky="ew")
        self.sep = Box(self.settings, "border", height=1)
        self.sep.grid(row=1, column=0, sticky="new", padx=1)

        # 摘要列（摺疊時）
        self.summary = card(self.right)
        self.summary.grid_columnconfigure(1, weight=1)
        self.sum_title = label(self.summary, "", F.body_bold)
        self.sum_title.grid(row=0, column=0, sticky="w", padx=(L, S), pady=(M, 0))
        self.sum_text = label(self.summary, "", F.small, "sub", anchor="w")
        self.sum_text.grid(row=0, column=1, columnspan=3, sticky="ew", padx=(0, L), pady=(M, 0))
        self.expand_btn = outline_button(self.summary, "⚙ 展開參數", self._toggle_expand, width=100)
        self.expand_btn.grid(row=1, column=0, columnspan=2, sticky="w", padx=L, pady=(S, M))
        self.sum_start = primary_button(self.summary, "", self.request_start, width=120, height=32)
        self.sum_start.grid(row=1, column=2, sticky="e", padx=(0, S), pady=(S, M))
        self.sum_stop = outline_button(self.summary, "", self.request_stop, width=64, height=32,
                                       font=F.body_bold)
        self.sum_stop.grid(row=1, column=3, sticky="e", padx=(0, L), pady=(S, M))

        # 日誌
        self.log_card = card(self.right)
        self.log_card.grid_rowconfigure(1, weight=1)
        self.log_card.grid_columnconfigure(0, weight=1)
        lh = Box(self.log_card, "panel")
        lh.grid(row=0, column=0, sticky="ew", padx=(L, M), pady=(M, XS))
        label(lh, "日誌", F.section, "sub").pack(side="left")
        outline_button(lh, "清除", lambda: self.log.clear(), width=52, height=26).pack(side="right")
        self.log = LogView(self.log_card, self.scale)
        self.log.widget.grid(row=1, column=0, sticky="nsew", padx=(L, S), pady=(0, M))

        # ---- 狀態列
        bar = Box(r, "panel")
        bar.grid(row=2, column=0, sticky="ew", pady=(M, 0))
        Box(bar, "border", height=1).pack(fill="x", side="top")
        inner_bar = Box(bar, "panel")
        inner_bar.pack(fill="x", padx=XL, pady=(5, 5))
        self.dot = label(inner_bar, "●", F.small, "faint")
        self.dot.pack(side="left")
        self.game_lbl = label(inner_bar, "遊戲：檢查中…", F.small, "sub")
        self.game_lbl.pack(side="left", padx=(4, 0))
        self._divider(inner_bar)
        self.state_lbl = label(inner_bar, "狀態：待機", F.small, "sub")
        self.state_lbl.pack(side="left")
        self.prog_div = self._divider(inner_bar)
        self.prog_lbl = label(inner_bar, "", F.small, "sub")
        self.prog_lbl.pack(side="left")
        self.time_lbl = label(inner_bar, "00:00:00", F.small, "sub")
        self.time_lbl.pack(side="right")
        self._set_progress("")
        self._update_hotkey_texts()

    def _on_stage(self, e):
        first = self._stage_size is None
        self._stage_size = (e.width, e.height)
        if self._stage_job:
            self.root.after_cancel(self._stage_job)
            self._stage_job = None
        if first:
            self._apply_stage()
        else:
            self._stage_job = self.root.after(RELAYOUT_DELAY, self._apply_stage)

    def _apply_stage(self):
        self._stage_job = None
        w, h = self._stage_size
        self.body.place_configure(width=w, height=h)

    def _divider(self, master):
        d = label(master, "│", F.small, "border")
        d.pack(side="left", padx=M)
        return d

    # ---------------------------------------------------------------- 摺疊
    def _on_resize(self, e):
        if e.widget is not self.root:
            return
        if self._resize_job:
            self.root.after_cancel(self._resize_job)
        self._resize_job = self.root.after(120, self._check_width)

    def _check_width(self):
        self._resize_job = None
        self._remember_window()
        narrow = self.root.winfo_width() / self.scale < NARROW
        if narrow != self.narrow:
            self.narrow = narrow
            self.expanded = False
            self._apply_layout()

    def _toggle_expand(self):
        self.expanded = not self.expanded
        self._apply_layout()

    def _apply_layout(self):
        folded = self.running or self.narrow
        if not folded or (self.expanded and not self.narrow):
            view = "side"
        elif self.expanded:
            view = "narrow_settings"
        else:
            view = "summary"
        self.right.grid_columnconfigure(0, weight=0)
        self.right.grid_columnconfigure(1, weight=1)
        for row in (0, 1):
            self.right.grid_rowconfigure(row, weight=0)
        for w in (self.settings, self.summary, self.log_card):
            w.grid_forget()
        if view == "side":
            self.settings.grid(row=0, column=0, sticky="ns", padx=(0, L))
            self.log_card.grid(row=0, column=1, sticky="nsew")
            self.right.grid_rowconfigure(0, weight=1)
        else:
            self.right.grid_columnconfigure(0, weight=1)
            self.summary.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, M))
            body = self.settings if view == "narrow_settings" else self.log_card
            body.grid(row=1, column=0, columnspan=2, sticky="nsew")
            self.right.grid_rowconfigure(1, weight=1)
        self.expand_btn.configure(text="收起參數" if view == "narrow_settings" else "⚙ 展開參數")
        if view == "narrow_settings":            # 摘要列已經有開始／停止
            self.btn_bar.grid_remove()
            self.sep.grid_remove()
        else:
            self.btn_bar.grid()
            self.sep.grid()
        if folded and view == "side":
            self.collapse_btn.grid(row=0, column=1, rowspan=2, sticky="ne")
        else:
            self.collapse_btn.grid_forget()
        self.view = view
        self._update_summary()

    def _on_settings_resize(self, e):
        w = max(200, e.width / self.scale - 60)
        self.desc.configure(wraplength=w)

    def _on_scaling(self, widget_scaling, window_scaling):
        """customtkinter 元件會自己縮放；這裡處理 ttk / tk 元件（功能樹、日誌、捲軸、間距）。"""
        new = ctk.ScalingTracker.get_window_scaling(self.root)
        if abs(new - self.scale) < 0.01:
            return
        self.scale = new
        theme.set_scale(new)
        theme.style_ttk(self.root)
        self.tree.rescale(new)
        self.log.rescale(new)
        if self.form:
            for fld, _, _ in self.form.fields.values():
                if isinstance(fld, SequenceEditor):
                    fld.scale = new
            self.form.frame.grid_columnconfigure(0, minsize=px(ParamForm.LABEL_W))

    # ================================================================ 任務與參數
    def _select(self, path):
        if self.running:
            return
        self._store_draft()
        self.current = path
        if self.form:
            self.form.frame.destroy()
            self.form = None
        if not path:
            self.crumb.configure(text="")
            self.task_title.configure(text="請從左邊選擇任務")
            self.desc.configure(text="")
            self._refresh_buttons()
            return
        t = self.tasks[path]
        self.crumb.configure(text=" › ".join(path[:-1]))
        self.crumb.grid() if len(path) > 1 else self.crumb.grid_remove()
        self.task_title.configure(text=path[-1])
        self.desc.configure(text=t.get("description") or "")
        self.desc.grid() if t.get("description") else self.desc.grid_remove()
        init = dict(self.values[path])
        init.update(self.drafts.get(path, {}))
        params = t["params"]
        if not params:
            self.form = None
            self._refresh_buttons()
            return
        self.form = ParamForm(self.form_holder, params, init, self._on_param_change, self._make_special)
        self.form.frame.grid(row=0, column=0, sticky="ew")
        self._on_param_change()
        try:
            self.scroll.to_top()
        except Exception:
            pass

    def _make_special(self, master, p, value, on_change):
        if p.get("widget") == "sequence" and self.sequence_tools:
            return SequenceEditor(master, p, value, on_change, self.sequence_tools, self.scale)
        return None                                  # 不認得的 widget → 一般欄位

    def _store_draft(self):
        if self.current and self.form:
            self.drafts[self.current] = self.form.raws()
            self.values[self.current].update(self.form.values())

    def _on_param_change(self):
        if self.current and self.form:
            self.values[self.current].update(self.form.values())
        self._refresh_buttons()
        self._update_summary()

    def _update_summary(self):
        if not self.current:
            self.sum_title.configure(text="未選擇任務")
            self.sum_text.configure(text="")
            return
        self.sum_title.configure(text=self.current[-1])
        parts = []
        if self.form:
            for fld, p, _ in self.form.fields.values():
                if p["type"] is bool:
                    continue
                if isinstance(fld, SequenceEditor):
                    parts.append(fld.summary())
                    continue
                v, err = fld.value()
                if err:
                    continue
                name, unit = split_unit(p["label"])
                parts.append(str(v) if p.get("choices") else f"{name} {v}{(' ' + unit) if unit else ''}")
                if len(parts) >= 3:
                    break
        self.sum_text.configure(text="  ·  ".join(parts[:3]))

    def _refresh_buttons(self):
        can_start = (not self.running and self.current is not None
                     and not (self.form and self.form.errors()))
        for b in (self.start_btn, self.sum_start):
            theme.set_primary_enabled(b, can_start)
        for b in (self.stop_btn, self.sum_stop):
            theme.set_stop_enabled(b, self.running)

    # ================================================================ 執行緒安全
    def _call(self, fn, *args):
        self._q.put((fn, args))

    def _poll(self):
        logs = []                                   # 連續的日誌一次寫入
        try:
            for _ in range(500):
                fn, args = self._q.get_nowait()
                if fn == self.log.append:
                    logs.append(args)
                    continue
                if logs:
                    self._flush_logs(logs)
                    logs = []
                try:
                    fn(*args)
                except Exception:
                    log.exception("介面更新失敗")
        except queue.Empty:
            pass
        if logs:
            self._flush_logs(logs)
        self._jobs["poll"] = self.root.after(50, self._poll)

    def _flush_logs(self, items):
        try:
            self.log.append_many(items)
        except Exception:
            log.exception("寫入日誌失敗")

    def _tick(self):
        if self.running and self._t0:
            s = int((datetime.datetime.now() - self._t0).total_seconds())
            self.time_lbl.configure(text=f"{s // 3600:02d}:{s // 60 % 60:02d}:{s % 60:02d}")
        self._jobs["tick"] = self.root.after(1000, self._tick)

    def _tk_error(self, exc, val, tb):
        log.error("介面錯誤：%s", val, exc_info=(exc, val, tb))
        try:
            self.log.append(f"介面錯誤：{val}", "error")
        except Exception:
            pass

    # ================================================================ 約定的方法（都可從背景執行緒呼叫）
    def append_log(self, text, level="info"):
        self._call(self.log.append, text, level)

    def set_running(self, running):
        self._call(self._set_running, bool(running))

    def set_game_status(self, text, ok):
        self._call(self._set_game_status, str(text), bool(ok))

    def set_progress(self, text):
        self._call(self._set_progress, "" if text is None else str(text))

    def get_values(self):
        """{path: {key: 值}}：每個任務最近一次正確的參數。"""
        return {p: dict(v) for p, v in self.values.items()}

    def request_start(self):
        """跟按「開始」一樣：檢查參數，沒問題就呼叫 on_start。F5 全域熱鍵會呼叫這個。"""
        self._call(self._do_start)

    def request_stop(self):
        self._call(self._do_stop)

    def run(self):
        self.root.mainloop()

    # ---------------------------------------------------------------- 實作
    def _set_running(self, running):
        if running == self.running:
            return
        self.running = running
        self.expanded = False
        if running:
            self._t0 = datetime.datetime.now()
            self.time_lbl.configure(text="00:00:00")
        self.state_lbl.configure(text="狀態：執行中" if running else "狀態：待機",
                                 text_color=C["accent_text"] if running else C["sub"])
        if self.form:
            self.form.set_enabled(not running)
        self.tree.set_locked(running)
        self._close_rename()
        if hasattr(self, "add_btn"):
            self.add_btn.configure(state="disabled" if running else "normal")
        if not running:
            self._set_progress("")
        if self.dialog:
            self.dialog.set_running(running)
        self._apply_layout()
        self._refresh_buttons()

    def _set_game_status(self, text, ok):
        self.dot.configure(text_color=C["ok"] if ok else C["err"])
        self.game_lbl.configure(text=f"遊戲：{text}")

    def _set_progress(self, text):
        self.prog_lbl.configure(text=text)
        if text:
            self.prog_div.pack(side="left", padx=M, before=self.prog_lbl)
        else:
            self.prog_div.pack_forget()

    def _do_start(self):
        if self.running:
            return
        if not self.current:
            self.log.append("請先在左邊選擇一個任務", "warn")
            return
        errs = self.form.errors() if self.form else []
        if errs:
            fld, p, msg = errs[0]
            self.log.append(f"無法開始：「{p['label']}」{msg}", "error")
            if self.view == "summary":
                self.expanded = True
                self._apply_layout()
            fld.focus()
            return
        vals = dict(self.values[self.current])
        if self.form:
            vals.update(self.form.values())
        self.values[self.current] = dict(vals)
        self._set_running(True)          # 先鎖住；on_start 失敗時主程式會呼叫 set_running(False)
        try:
            self.on_start(self.current, vals)
        except Exception as e:
            log.exception("on_start 失敗")
            self.log.append(f"無法開始：{e}", "error")
            self._set_running(False)

    def _do_stop(self):
        try:
            self.on_stop()
        except Exception as e:
            log.exception("on_stop 失敗")
            self.log.append(f"停止失敗：{e}", "error")

    def _open_logs(self):
        try:
            self.on_open_logs()
        except Exception as e:
            self.log.append(f"無法開啟日誌資料夾：{e}", "error")

    # ---------------------------------------------------------------- 熱鍵、設定視窗
    def _update_hotkey_texts(self):
        a, b = self.hotkeys["start"], self.hotkeys["stop"]
        self.start_btn.configure(text=f"▶  開始   {a}")
        self.stop_btn.configure(text=f"■  停止   {b}")
        self.sum_start.configure(text=f"▶  開始   {a}", width=max(120, 84 + 8 * len(a)))
        self.sum_stop.configure(text=f"■  {b}", width=max(64, 40 + 8 * len(b)))

    def _bind_hotkeys(self):
        """視窗有焦點時也接受熱鍵（全域熱鍵註冊失敗時的備案）。"""
        for seq in self._key_binds:
            self.root.unbind(seq)
        self._key_binds = []
        for name, fn in (("start", self.request_start), ("stop", self.request_stop)):
            seq = tk_sequence(self.hotkeys[name])
            if seq:
                try:
                    self.root.bind(seq, lambda e, fn=fn: fn())
                    self._key_binds.append(seq)
                except tk.TclError:
                    pass

    def set_hotkey_labels(self, start, stop):
        """主程式改熱鍵成功後呼叫：更新按鈕上的文字。可從背景執行緒呼叫。"""
        self._call(self._set_hotkey_labels, str(start), str(stop))

    def _set_hotkey_labels(self, start, stop):
        self.hotkeys = {"start": normalize_hotkey(start)[0] or start, "stop": normalize_hotkey(stop)[0] or stop}
        self._update_hotkey_texts()
        self._bind_hotkeys()

    def _open_settings(self):
        if self.dialog:
            self.dialog.win.lift()
            self.dialog.win.focus_force()
            return
        from . import __version__
        self.dialog = SettingsDialog(self, self.settings_cfg, self.running, self.on_open_logs,
                                     f"{self.title}　·　介面 v{__version__}")

    def _settings_closed(self):
        self.dialog = None

    # ---------------------------------------------------------------- 功能樹編輯（自訂項目）
    def _editable(self):
        return [p for p, t in self.tasks.items() if t.get("editable")]

    def _group_of(self, path):
        t = self.tasks.get(tuple(path))
        if t and t.get("group"):
            return tuple(t["group"])
        return next((g for g in self.groups if tuple(path)[:len(g)] == g), None)

    def _items_by_group(self):
        out = {g: [] for g in self.groups}
        for p in self.tree.paths:                       # 照顯示順序
            g = self._group_of(p)
            if g in out and self.tasks[p].get("editable"):
                out[g].append(p)
        return out

    def _can_edit(self):
        if self.running:
            self.log.append("執行中不能編輯任務，請先停止", "warn")
            return False
        if self._modal is not None or self._rename_entry is not None:
            return False
        return True

    def _call_editor(self, name, *args):
        fn = self.task_editor.get(name)
        if not fn:
            return False, "主程式沒有提供這個功能", None
        try:
            res = fn(*args)
        except Exception as e:
            log.exception("task_editor.%s 失敗", name)
            return False, f"發生錯誤：{e}", None
        res = tuple(res) + (None,) * (3 - len(tuple(res)))
        return bool(res[0]), str(res[1] or ""), res[2]

    def _reload_tasks(self, tasks, select=None):
        """用主程式回傳的新任務清單重建功能樹（參數草稿已經搬好）。"""
        self.tasks = {tuple(t["path"]): t for t in tasks}
        for path, t in self.tasks.items():
            if path not in self.values:
                self.values[path] = {p["key"]: p["default"] for p in t["params"]}
        for gone in [p for p in list(self.values) if p not in self.tasks]:
            self.values.pop(gone, None)
            self.drafts.pop(gone, None)
        self.current = None                             # 讓 _select 一定重建參數區
        self.tree.current = None
        self.tree.rebuild(list(self.tasks), self.groups, self._editable())
        target = select if select in self.tasks else self.tree.first_task()
        if target:
            self.tree.select(target)
        self._select(target)

    @staticmethod
    def _diff_new(old_paths, tasks, group, name):
        new = [tuple(t["path"]) for t in tasks]
        want = tuple(group) + (name.strip(),)
        if want in new:
            return want
        added = [p for p in new if p not in set(old_paths)]
        return added[0] if added else None

    # 右鍵選單 ------------------------------------------------------
    def _tree_menu(self, kind, path, x, y):
        m = tk.Menu(self.root, **theme.menu_style(self.scale))
        if self.running:
            m.add_command(label="執行中不能編輯", state="disabled")
        elif kind == "item":
            sib = self.tree.siblings(path)
            i = sib.index(path) if path in sib else 0
            m.add_command(label="新增項目…", command=lambda: self._add_item(group=self._group_of(path)))
            m.add_command(label="複製…", command=lambda: self._copy_item(path))
            m.add_command(label="改名", accelerator="F2", command=lambda: self._start_rename(path))
            m.add_separator()
            m.add_command(label="上移", command=lambda: self._move_item(path, -1), state="normal" if i > 0 else "disabled")
            m.add_command(label="下移", command=lambda: self._move_item(path, 1),
                          state="normal" if i < len(sib) - 1 else "disabled")
            m.add_separator()
            m.add_command(label="刪除", accelerator="Del", foreground=C["err"], activeforeground=C["white"],
                          activebackground="#8E2F2B", command=lambda: self._delete_item(path))
        elif kind == "group":
            m.add_command(label=f"在「{self.group_names.get(path, path[-1])}」新增項目…",
                          command=lambda: self._add_item(group=path))
        else:
            m.add_command(label="新增項目…", command=lambda: self._add_item())
        try:
            m.tk_popup(x, y)
        finally:
            m.grab_release()

    def _tree_key(self, name, path):
        if name == "rename":
            self._start_rename(path)
        elif name == "delete":
            self._delete_item(path)

    # 新增、複製 ----------------------------------------------------
    def _add_item(self, group=None, copy_from=None, name=""):
        if not self._can_edit():
            return
        self._store_draft()
        if group is None:
            group = self._group_of(self.current) if self.current else None
        groups = [(g, self.group_names.get(g, g[-1])) for g in self.groups]
        AddItemDialog(self, groups, self._items_by_group(), self._do_add, group=group or self.groups[0],
                      copy_from=copy_from, name=name)

    def _copy_item(self, path):
        g = self._group_of(path)
        names = [p[-1] for p in self._items_by_group().get(g, [])]
        self._add_item(group=g, copy_from=path, name=unique_name(path[-1], names))

    def _do_add(self, group, name, copy_from):
        self._store_draft()
        values = dict(self.values.get(copy_from, {})) if copy_from else None
        old = list(self.tasks)
        ok, msg, tasks = self._call_editor("add", tuple(group), name, values)
        if not ok:
            return False, msg
        new_path = self._diff_new(old, tasks or [], group, name)
        if new_path and values is not None:
            t = next((t for t in tasks if tuple(t["path"]) == new_path), None)
            keys = {p["key"] for p in t["params"]} if t else set(values)
            self.values[new_path] = {k: v for k, v in values.items() if k in keys}
            if copy_from in self.drafts:
                self.drafts[new_path] = {k: v for k, v in self.drafts[copy_from].items() if k in keys}
        self._reload_tasks(tasks, select=new_path)
        self.log.append(msg or f"已新增「{new_path[-1] if new_path else name.strip()}」")
        return True, ""

    # 改名（直接在樹上改）-------------------------------------------
    def _start_rename(self, path):
        if not self._can_edit() or path not in self.tasks or not self.tasks[path].get("editable"):
            return
        self.tree.select(path)
        self.tree.widget.see(self.tree.iid(path))
        self.tree.widget.update_idletasks()
        box = self.tree.bbox(path)
        if not box:
            return
        x, y, w, h = box
        var = tk.StringVar(value=path[-1])
        tw, sc = self.tree.widget, self.scale
        # customtkinter 的大小、位置都用未縮放的單位（它自己會乘上顯示比例）
        e = ctk.CTkEntry(self.tree_card, textvariable=var, font=F.body, fg_color=C["input"],
                         border_color=C["accent"], border_width=2, corner_radius=4, text_color=C["text"],
                         width=max(80, (tw.winfo_width() - x) / sc - 8), height=max(24, (h - 2) / sc))
        e.place(in_=tw, x=x / sc + 4, y=(y + 1) / sc)
        self._rename_entry = e
        state = {"done": False}

        def finish(commit):
            if state["done"]:
                return
            if commit and var.get().strip() != path[-1]:
                siblings = [p[-1] for p in self._items_by_group().get(self._group_of(path), [])]
                new, err = validate_name(var.get(), siblings, keep=path[-1])
                if err:
                    e.configure(border_color=C["err"])
                    self.log.append(f"無法改名：{err}", "warn")
                    return
                ok, msg, tasks = self._call_editor("rename", path, new)
                if not ok:
                    e.configure(border_color=C["err"])
                    self.log.append(f"無法改名：{msg}", "warn")
                    return
                state["done"] = True
                self._close_rename()
                self._store_draft()
                new_path = self._diff_new(list(self.tasks), tasks or [], path[:-1], new)
                if new_path:
                    for d in (self.values, self.drafts):
                        if path in d:
                            d[new_path] = d.pop(path)
                self._reload_tasks(tasks, select=new_path)
                self.log.append(msg or f"已改名為「{new_path[-1] if new_path else new}」")
                return
            state["done"] = True
            self._close_rename()

        e.bind("<Return>", lambda ev: finish(True))
        e.bind("<KP_Enter>", lambda ev: finish(True))
        e.bind("<Escape>", lambda ev: (finish(False), "break")[1])
        e.bind("<FocusOut>", lambda ev: finish(False) if not state["done"] else None)
        e.after(30, lambda: (e.focus_set(), e.select_range(0, "end")))

    def _close_rename(self):
        if self._rename_entry is not None:
            try:
                self._rename_entry.destroy()
            except tk.TclError:
                pass
            self._rename_entry = None

    # 刪除、上下移 --------------------------------------------------
    def _delete_item(self, path):
        if not self._can_edit():
            return
        ConfirmDialog(self, "刪除項目", f"確定要刪除「{path[-1]}」嗎？\n這個項目的出招流程和所有設定會一起刪除，無法復原。",
                      "刪除", lambda: self._do_delete(path))

    def _do_delete(self, path):
        self._store_draft()
        sib = self.tree.siblings(path)
        i = sib.index(path) if path in sib else 0
        nxt = (sib[i + 1] if i + 1 < len(sib) else sib[i - 1] if i > 0 else None)
        ok, msg, tasks = self._call_editor("delete", path)
        if not ok:
            self.log.append(f"無法刪除：{msg}", "warn")
            return
        self._reload_tasks(tasks, select=nxt)
        self.log.append(msg or f"已刪除「{path[-1]}」")

    def _move_item(self, path, delta):
        if not self._can_edit():
            return
        self._store_draft()
        ok, msg, tasks = self._call_editor("move", path, delta)
        if not ok:
            self.log.append(msg, "warn")
            return
        self._reload_tasks(tasks, select=path)

    def _close(self):
        if self.dialog:
            self.dialog.close()
        if self._modal is not None:
            self._modal.close()
        self._remember_window()
        if self.running:
            try:
                self.on_stop()
            except Exception:
                pass
        self._store_draft()
        for job in list(self._jobs.values()) + [self._resize_job, self._stage_job]:
            if job:
                try:
                    self.root.after_cancel(job)
                except Exception:
                    pass
        self.root.destroy()
