# -*- coding: utf-8 -*-
"""
收集各模組的任務，檢查格式，整理成給 ui 的資料。

兩種來源：
  TASKS      固定任務（釣魚、開發測試）
  TEMPLATES  類型範本（戰鬥：討伐戰、公會BOSS），項目由使用者在介面上新增／改名／刪除／排序，
             清單存在 config.json 的 "custom_tasks"：{template_id: [名稱, ...]}
同一個模組可以同時提供 TEMPLATES 和 TASKS（例：戰鬥的「討伐戰巡迴」是一般任務）；路徑重複時略過並警告。
任務類別宣告 needs_items = "raid"（template_id）時，Runner 開始前會設定 task.items = {項目名稱: 參數}。
規格見 02_Tkinter外型.md「📝 提案：自訂戰鬥項目」。
"""
import importlib
import logging

from core.task import Task

from .config import path_key

log = logging.getLogger("app")

# 依序載入；之後新增模組加在這裡（順序就是功能樹上的順序）
TASK_MODULES = ["combat", "fishing"]
DEMO_MODULE = "app.demo"
NAME_MAX = 20


def _import(module_name):
    try:
        return importlib.import_module(module_name)
    except ModuleNotFoundError as e:
        if e.name == module_name:          # 模組還不存在（還沒開發）→ 略過
            log.debug("模組 %s 還沒有，略過", module_name)
        else:
            log.exception("載入 %s 失敗：缺少 %s", module_name, e.name)
    except Exception:
        log.exception("載入 %s 失敗", module_name)
    return None


def _ok_task(t, where):
    if not (isinstance(t, type) and issubclass(t, Task)):
        log.warning("%s 裡的 %r 不是 Task 子類別，略過", where, t)
        return False
    return True


class Catalog:
    """所有任務（固定＋自訂項目），以及編輯自訂項目。"""

    def __init__(self, config, include_demo=False):
        self.config = config
        self.static = []            # [(模組名, Task 類別)]
        self.templates = []         # [(模組, 範本類別)]
        for name in TASK_MODULES:
            mod = _import(name)
            if mod is None:
                continue
            tpls = getattr(mod, "TEMPLATES", None)
            if tpls:
                for t in tpls:
                    if _ok_task(t, f"{name}.TEMPLATES") and getattr(t, "template_id", None) and getattr(t, "group", None):
                        self.templates.append((mod, t))
                    else:
                        log.warning("%s.TEMPLATES 裡的 %r 缺少 template_id 或 group，略過", name, t)
            tasks = getattr(mod, "TASKS", None)
            if tasks is None:
                if not tpls:
                    log.warning("%s 沒有提供 TASKS", name)
                continue
            self.static += [(name, t) for t in tasks if _ok_task(t, f"{name}.TASKS")]
        if include_demo or not (self.static or self.templates):
            mod = _import(DEMO_MODULE)
            self.static += [(DEMO_MODULE, t) for t in getattr(mod, "TASKS", [])] if mod else []
        self._init_custom()
        self.classes = []
        self.rebuild()

    # ------------------------------------------------------------ 自訂項目清單
    def _init_custom(self):
        """某個類型還沒有紀錄 → 用 default_items 建立，並把預設值寫進 values（已有值的不覆蓋）。"""
        custom = self.config.data.setdefault("custom_tasks", {})
        changed = False
        for _, t in self.templates:
            if t.template_id in custom:
                continue
            names = []
            for name, vals in getattr(t, "default_items", []) or []:
                names.append(name)
                key = path_key(tuple(t.group) + (name,))
                if key not in self.config["values"]:
                    base = {p.key: p.default for p in t.params}
                    base.update({k: v for k, v in (vals or {}).items() if k in base})
                    self.config["values"][key] = base
            custom[t.template_id] = names
            changed = True
        if changed:
            self.config.save()

    def _names(self, t):
        return self.config["custom_tasks"].setdefault(t.template_id, [])

    def _template_for_group(self, group):
        group = tuple(group or ())
        return next((t for _, t in self.templates if tuple(t.group) == group), None)

    def _item(self, path):
        """path 是自訂項目 → (範本, 名稱)；不是 → (None, None)"""
        path = tuple(path or ())
        t = self._template_for_group(path[:-1]) if len(path) > 1 else None
        if t and path[-1] in self._names(t):
            return t, path[-1]
        return None, None

    # ------------------------------------------------------------ 產生任務類別
    @staticmethod
    def _make(mod, t, name):
        mk = getattr(mod, "make_item", None)
        if mk:
            return mk(t, name)
        return type(name, (t,), {"path": tuple(t.group) + (name,), "__module__": t.__module__})

    def rebuild(self):
        # 順序：照 TASK_MODULES；同一個模組裡固定任務在前、自訂項目在後
        # （例：戰鬥 › 討伐戰巡迴、討伐戰…、公會BOSS…；由「戰鬥」對話修改，使用者要求巡迴排在討伐戰上面）
        out, seen, done = [], set(), set()
        for mname in list(TASK_MODULES) + [DEMO_MODULE]:
            out += [t for m, t in self.static if m == mname]
            for mod, t in self.templates:
                if mod.__name__ == mname:
                    done.add(id(t))
                    for name in self._names(t):
                        out.append(self._make(mod, t, name))
        out += [t for m, t in self.static if m not in TASK_MODULES and m != DEMO_MODULE]
        for mod, t in self.templates:                      # 理論上不會有，保險
            if id(t) not in done:
                for name in self._names(t):
                    out.append(self._make(mod, t, name))
        result = []
        for t in out:
            path = tuple(t.path or ())
            if not path:
                log.warning("%s 沒有設定 path，略過", t.__name__)
                continue
            if path in seen:
                log.warning("任務路徑重複：%s，略過", " / ".join(path))
                continue
            seen.add(path)
            result.append(t)
        self.classes = result
        return result

    # ------------------------------------------------------------ 給任務（needs_items）
    def items_values(self, template_id):
        """{項目名稱: 已轉好型別的參數 dict}，順序 = 功能樹順序。找不到類型回傳 {}。"""
        t = next((t for _, t in self.templates if t.template_id == template_id), None)
        if t is None:
            return {}
        out = {}
        for name in self._names(t):
            saved = self.config.task_values(tuple(t.group) + (name,))
            out[name] = {p.key: p.coerce(saved.get(p.key)) for p in t.params}
        return out

    # ------------------------------------------------------------ 給 ui
    def groups(self):
        return [{"path": tuple(t.group), "id": t.template_id,
                 "name": getattr(t, "type_name", t.group[-1])} for _, t in self.templates]

    def to_ui(self):
        items = []
        for t in self.classes:
            d = {
                "path": tuple(t.path),
                "description": t.description or "",
                "params": [{
                    "key": p.key, "label": p.label, "type": p.type, "default": p.default,
                    "min": p.min, "max": p.max, "choices": p.choices, "help": p.help,
                    "widget": getattr(p, "widget", None),
                } for p in t.params],
            }
            tpl, _ = self._item(t.path)
            if tpl:
                d["editable"] = True
                d["group"] = tuple(tpl.group)
            items.append(d)
        return items

    # ------------------------------------------------------------ 編輯（ui 的 task_editor）
    def check_name(self, t, name, exclude=None):
        name = (name or "").strip()
        if not name:
            return None, "名稱不能空白"
        if len(name) > NAME_MAX:
            return None, f"名稱最多 {NAME_MAX} 個字"
        if "/" in name or "\\" in name:
            return None, "名稱不能有 / 或 \\"
        if name != exclude and name in self._names(t):
            return None, f"「{t.group[-1]}」裡已經有「{name}」了"
        return name, None

    def add(self, group, name, values=None):
        t = self._template_for_group(group)
        if t is None:
            return False, "找不到這個類型", None
        name, err = self.check_name(t, name)
        if err:
            return False, err, None
        base = {p.key: p.default for p in t.params}
        if values:                                    # 複製：只留這個類型有的參數
            src = {p.key: p for p in t.params}
            base.update({k: src[k].coerce(v) for k, v in values.items() if k in src})
        self._names(t).append(name)
        self.config["values"][path_key(tuple(t.group) + (name,))] = base
        return True, f"已新增「{name}」", None

    def rename(self, path, new_name):
        t, old = self._item(path)
        if t is None:
            return False, "這個項目不能改名", None
        new, err = self.check_name(t, new_name, exclude=old)
        if err:
            return False, err, None
        if new == old:
            return True, "名稱沒有變", None
        names = self._names(t)
        names[names.index(old)] = new
        vals = self.config["values"]
        ok_, nk = path_key(tuple(path)), path_key(tuple(t.group) + (new,))
        if ok_ in vals:
            vals[nk] = vals.pop(ok_)
        if tuple(self.config["last_task"] or ()) == tuple(path):
            self.config["last_task"] = list(tuple(t.group) + (new,))
        return True, f"已改名為「{new}」", None

    def delete(self, path):
        t, name = self._item(path)
        if t is None:
            return False, "這個項目不能刪除", None
        self._names(t).remove(name)
        self.config["values"].pop(path_key(tuple(path)), None)
        if tuple(self.config["last_task"] or ()) == tuple(path):
            self.config["last_task"] = None
        return True, f"已刪除「{name}」", None

    def move(self, path, delta):
        t, name = self._item(path)
        if t is None:
            return False, "這個項目不能移動", None
        names = self._names(t)
        i = names.index(name)
        j = i + (1 if delta > 0 else -1)
        if not 0 <= j < len(names):
            return False, "已經在最上面了" if delta < 0 else "已經在最下面了", None
        names[i], names[j] = names[j], names[i]
        return True, "已移動", None

