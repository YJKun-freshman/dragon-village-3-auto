# -*- coding: utf-8 -*-
"""
出招流程：玩家自訂的一串步驟。

文字格式（介面上的文字欄位用這個）：用 > 分隔，例如

    技能1 > 替換2 > 必殺技 > 替換3 > 必殺技 > 自動

可用的步驟（括號裡是也看得懂的別名）：

    技能1            寶珠技能第 1 格（技1、寶珠1）
    技能2            寶珠技能第 2 格（技2、寶珠2）
    必殺技           （必殺、大招）
    普攻             一般攻擊（普通攻擊、一般攻擊、攻擊）
    替換1～替換3     換成隊伍第 1～3 隻（換2、替換→2；「替換 > 替換2」也可以）
    自動             開自動，打到戰鬥結束
    自動5            開自動 5 回合，之後關掉自動，繼續下一步（實驗功能）
    回到3            跳回第 3 步（用來做循環）

每個出招步驟（技能、必殺、普攻、替換）都會用掉一回合。
寶珠不夠、按鈕是暗的時候：這回合改放普攻，下一回合再補放原本的技能（最多補 3 次）。

給 ui 的資料格式（之後做流程編輯器用）：步驟清單，每步一個 dict

    [{"action": "skill1"}, {"action": "swap", "slot": 2}, {"action": "ult"},
     {"action": "auto", "rounds": 0}, {"action": "goto", "step": 3}]

`parse()` 文字 → 清單、`to_text()` 清單 → 文字、`validate()` 檢查。
"""
import re

# action → 介面顯示名稱
ACTIONS = {
    "skill1": "技能1",
    "skill2": "技能2",
    "ult": "必殺技",
    "attack": "普攻",
    "swap": "替換",
    "auto": "自動",
    "goto": "回到",
}
TURN_ACTIONS = ("skill1", "skill2", "ult", "attack", "swap")   # 會用掉一回合的
SWAP_SLOTS = (1, 2, 3)

_SEP = re.compile(r"\s*(?:>|＞|→|➜|》|,|，|、|;|；|\n)\s*")
_ALIASES = [
    (re.compile(r"^(?:技能|技|寶珠技能|寶珠)\s*([12１２])$"), lambda m: {"action": "skill" + _num(m.group(1))}),
    (re.compile(r"^(?:必殺技|必殺|大招|ult)$", re.I), lambda m: {"action": "ult"}),
    (re.compile(r"^(?:普攻|普通攻擊|一般攻擊|攻擊|普)$"), lambda m: {"action": "attack"}),
    (re.compile(r"^(?:替換|換)\s*(?:→|->|-)?\s*([1-3１-３])$"), lambda m: {"action": "swap", "slot": int(_num(m.group(1)))}),
    (re.compile(r"^(?:自動|auto)$", re.I), lambda m: {"action": "auto", "rounds": 0}),
    (re.compile(r"^(?:自動|auto)\s*(\d+)\s*(?:回合)?$", re.I), lambda m: {"action": "auto", "rounds": int(m.group(1))}),
    (re.compile(r"^(?:回到|跳到|跳回|重複|goto)\s*(?:第)?\s*(\d+)\s*(?:步)?$", re.I), lambda m: {"action": "goto", "step": int(m.group(1))}),
]


def _num(s):
    return s.translate(str.maketrans("１２３", "123"))


class SequenceError(ValueError):
    """流程寫錯。訊息是給使用者看的中文。"""


def parse(text):
    """文字 → 步驟清單。寫錯丟 SequenceError。"""
    tokens = [t.strip() for t in _SEP.split(text or "") if t.strip()]
    steps, i = [], 0
    while i < len(tokens):
        tok = tokens[i]
        # 「替換 > 替換2」或「替換 > 2」→ 合成一步
        if tok in ("替換", "換"):
            nxt = tokens[i + 1] if i + 1 < len(tokens) else ""
            m = re.match(r"^(?:替換|換)?\s*([1-3１-３])$", nxt)
            if not m:
                raise SequenceError(f"第 {len(steps) + 1} 步「替換」要寫換成第幾隻，例如「替換2」")
            steps.append({"action": "swap", "slot": int(_num(m.group(1)))})
            i += 2
            continue
        for rx, make in _ALIASES:
            m = rx.match(tok)
            if m:
                steps.append(make(m))
                break
        else:
            raise SequenceError(f"第 {len(steps) + 1} 步「{tok}」看不懂。"
                                "可用：技能1、技能2、必殺技、普攻、替換1～3、自動、自動5、回到3")
        i += 1
    validate(steps)
    return steps


def validate(steps):
    """檢查步驟清單，有問題丟 SequenceError。"""
    if not steps:
        raise SequenceError("出招流程是空的")
    for n, s in enumerate(steps, 1):
        a = s.get("action")
        if a not in ACTIONS:
            raise SequenceError(f"第 {n} 步：不認得的動作 {a!r}")
        if a == "swap" and s.get("slot") not in SWAP_SLOTS:
            raise SequenceError(f"第 {n} 步：替換要選第 1～3 隻")
        if a == "auto" and int(s.get("rounds", 0)) < 0:
            raise SequenceError(f"第 {n} 步：自動回合數不能是負的")
        if a == "goto":
            k = s.get("step")
            if n == 1:
                raise SequenceError("第 1 步不能是「回到」")
            if not isinstance(k, int) or not 1 <= k < n:
                raise SequenceError(f"第 {n} 步「回到{k}」：只能跳回前面的步驟（1～{n - 1}）")
            if not any(t["action"] in TURN_ACTIONS or (t["action"] == "auto" and t.get("rounds"))
                       for t in steps[k - 1:n - 1]):
                raise SequenceError(f"第 {n} 步「回到{k}」：循環裡至少要有一個出招或「自動N」")
        if a == "auto" and not s.get("rounds") and n < len(steps):
            raise SequenceError(f"第 {n} 步「自動」會一直打到結束，後面的步驟不會執行。"
                                "要中途切回手動請寫「自動5」這種有回合數的")
    return steps


def step_text(s):
    a = s["action"]
    if a == "swap":
        return f"替換{s['slot']}"
    if a == "auto":
        return f"自動{s['rounds']}" if s.get("rounds") else "自動"
    if a == "goto":
        return f"回到{s['step']}"
    return ACTIONS[a]


def to_text(steps):
    """步驟清單 → 文字。"""
    return " > ".join(step_text(s) for s in steps)
