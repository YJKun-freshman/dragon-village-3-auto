# -*- coding: utf-8 -*-
"""找圖（OpenCV 樣板比對）。所有影像都是「正規化畫面」（高度 1000）。"""
import os
import threading
from dataclasses import dataclass

import numpy as np

from . import paths


@dataclass
class Match:
    x: float        # 中心點（比例 0～1）
    y: float
    w: float        # 寬高（比例）
    h: float
    score: float

    def __repr__(self):
        return f"Match(x={self.x:.3f}, y={self.y:.3f}, w={self.w:.3f}, h={self.h:.3f}, score={self.score:.3f})"


# ---------------------------------------------------------------- 讀寫圖檔（支援中文路徑）
def imread(path, keep_alpha=False):
    import cv2
    data = np.fromfile(str(path), np.uint8)
    flag = cv2.IMREAD_UNCHANGED if keep_alpha else cv2.IMREAD_COLOR
    img = cv2.imdecode(data, flag)
    if img is None:
        raise FileNotFoundError(f"讀不到圖片：{path}")
    if keep_alpha and img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    return img


def imwrite(path, img):
    import cv2
    path = str(path)
    ext = os.path.splitext(path)[1] or ".png"
    ok, buf = cv2.imencode(ext, img)
    if not ok:
        raise IOError(f"無法編碼圖片：{path}")
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    buf.tofile(path)
    return path


# ---------------------------------------------------------------- 樣板
class Template:
    def __init__(self, img, name=""):
        self.name = name
        if img.ndim == 3 and img.shape[2] == 4:
            alpha = img[:, :, 3]
            self.image = np.ascontiguousarray(img[:, :, :3])
            self.mask = None if alpha.min() == 255 else np.ascontiguousarray(
                np.where(alpha > 0, 255, 0).astype(np.uint8))
        else:
            self.image = img if img.ndim == 3 else np.stack([img] * 3, axis=2)
            self.mask = None
        self.h, self.w = self.image.shape[:2]


_cache = {}
_cache_lock = threading.Lock()


def load_template(template):
    """template 可以是：路徑（相對路徑以專案根目錄為準）、Template、ndarray。"""
    if isinstance(template, Template):
        return template
    if isinstance(template, np.ndarray):
        return Template(template, "<ndarray>")
    path = paths.resource(template)
    key = os.path.normcase(os.path.abspath(path))
    with _cache_lock:
        t = _cache.get(key)
    if t is None:
        t = Template(imread(path, keep_alpha=True), os.path.basename(path))
        with _cache_lock:
            _cache[key] = t
    return t


_variants = {}
_blur_frames = []          # [(frame, blur, blurred)]，只留最近幾張


def clear_cache():
    with _cache_lock:
        _cache.clear()
        _variants.clear()
        _blur_frames.clear()


def variant(template, scale=1.0, blur=0):
    """樣板縮放 scale 倍、再模糊（blur = 高斯核大小，0 = 不模糊）。結果會快取。"""
    import cv2
    t = load_template(template)
    if scale == 1.0 and not blur:
        return t
    key = (id(t), round(scale, 4), int(blur))
    with _cache_lock:
        v = _variants.get(key)
    if v is None:
        img, mask = t.image, t.mask
        if scale != 1.0:
            interp = cv2.INTER_LINEAR if scale > 1 else cv2.INTER_AREA
            img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=interp)
            if mask is not None:
                mask = cv2.resize(mask, (img.shape[1], img.shape[0]), interpolation=cv2.INTER_NEAREST)
        if blur:
            img = cv2.GaussianBlur(img, (blur, blur), 0)
        v = Template(img, f"{t.name}@{scale:g}" + (f"~{blur}" if blur else ""))
        v.mask = mask
        with _cache_lock:
            if len(_variants) > 2000:          # ndarray 樣板每次都是新物件，避免無限長大
                _variants.clear()
            _variants[key] = v
            # 防止 id 重複使用：同時保留原樣板的參考
            v._src = t
    return v


def blurred(frame, blur):
    """畫面模糊（同一張畫面重複找圖時只算一次）。"""
    import cv2
    if not blur:
        return frame
    with _cache_lock:
        for f, b, out in _blur_frames:
            if f is frame and b == blur:
                return out
    out = cv2.GaussianBlur(frame, (blur, blur), 0)
    with _cache_lock:
        _blur_frames.append((frame, blur, out))
        del _blur_frames[:-4]
    return out


# ---------------------------------------------------------------- 比對
def _region_px(frame, region):
    fh, fw = frame.shape[:2]
    if region is None:
        return 0, 0, fw, fh
    x0, y0, x1, y1 = region
    px0, py0 = int(max(0.0, min(x0, x1)) * fw), int(max(0.0, min(y0, y1)) * fh)
    px1, py1 = int(np.ceil(min(1.0, max(x0, x1)) * fw)), int(np.ceil(min(1.0, max(y0, y1)) * fh))
    return px0, py0, px1, py1


def _score_map(frame, t, region):
    import cv2
    px0, py0, px1, py1 = _region_px(frame, region)
    roi = frame[py0:py1, px0:px1]
    if roi.shape[0] < t.h or roi.shape[1] < t.w:
        return None, px0, py0
    if t.mask is not None:
        res = cv2.matchTemplate(roi, t.image, cv2.TM_CCOEFF_NORMED, mask=t.mask)
        res = np.nan_to_num(res, nan=0.0, posinf=0.0, neginf=0.0)
        np.clip(res, -1.0, 1.0, out=res)
    else:
        res = cv2.matchTemplate(roi, t.image, cv2.TM_CCOEFF_NORMED)
    return res, px0, py0


def _to_match(frame, t, px, py, score):
    fh, fw = frame.shape[:2]
    return Match(x=(px + t.w / 2) / fw, y=(py + t.h / 2) / fh,
                 w=t.w / fw, h=t.h / fh, score=float(score))


def _scales(scales):
    return (1.0,) if not scales else tuple(scales)


def find(frame, template, region=None, threshold=0.85, scales=None, blur=0):
    """
    找最像的一個；分數低於 threshold 回傳 None。
    scales  倍率清單，例 (1.0, 1.08, 1.16)：依序試，第一個達到門檻的就回傳（預設只試 1.0）
    blur    先把畫面和樣板都模糊（高斯核大小，奇數，例 5）；視窗大小不同、清晰度不同時比較穩（預設 0 = 不模糊）
    """
    import cv2
    f = blurred(frame, blur)
    for sc in _scales(scales):
        t = variant(template, sc, blur)
        res, ox, oy = _score_map(f, t, region)
        if res is None:
            continue
        _, mx, _, loc = cv2.minMaxLoc(res)
        if mx >= threshold:
            return _to_match(frame, t, ox + loc[0], oy + loc[1], mx)
    return None


def best_score(frame, template, region=None, scales=None, blur=0):
    """不管門檻，回傳最高分（調整 threshold 時好用；有 scales 時取所有倍率的最高分）。"""
    import cv2
    f = blurred(frame, blur)
    best = 0.0
    for sc in _scales(scales):
        res, _, _ = _score_map(f, variant(template, sc, blur), region)
        if res is not None:
            best = max(best, float(cv2.minMaxLoc(res)[1]))
    return best


def find_all(frame, template, region=None, threshold=0.85, max_results=50, scales=None, blur=0):
    """找全部（重疊的只留分數最高的），依分數由高到低排序。有 scales 時用第一個找得到東西的倍率。"""
    for sc in _scales(scales):
        out = _find_all_one(frame, variant(template, sc, blur), region, threshold, max_results, blur)
        if out:
            return out
    return []


def _find_all_one(frame, t, region, threshold, max_results, blur):
    import cv2
    res, ox, oy = _score_map(blurred(frame, blur), t, region)
    if res is None:
        return []
    res = res.copy()
    out = []
    hw, hh = max(1, t.w // 2), max(1, t.h // 2)
    while len(out) < max_results:
        _, mx, _, (lx, ly) = cv2.minMaxLoc(res)
        if mx < threshold:
            break
        out.append(_to_match(frame, t, ox + lx, oy + ly, mx))
        res[max(0, ly - hh):ly + hh + 1, max(0, lx - hw):lx + hw + 1] = -1.0
    return out
