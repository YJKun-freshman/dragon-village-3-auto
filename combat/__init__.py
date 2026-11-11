# -*- coding: utf-8 -*-
"""
龍村3 自動腳本 — 戰鬥。

- TEMPLATES：戰鬥類型（討伐戰、公會BOSS），項目由使用者在介面上建立（見 kinds.py）
- TASKS：固定任務「討伐戰巡迴」（tour.py，needs_items="raid"，app v0.5.0 起可以和 TEMPLATES 同時提供）
"""
from .kinds import TEMPLATES, Raid, GuildBoss, make_item, default_tasks
from .tour import RaidTour

__version__ = "0.5.3"

TASKS = [RaidTour]
