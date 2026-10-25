"""精简公共函数：时间解析、裁剪参数、封面下载（手机端后端用）。"""

from __future__ import annotations

import os
import re
import urllib.request

_TIME_RE = re.compile(r"^(?:(\d{1,3}):)?([0-5]?\d):([0-5]\d)$")


def parse_time(text: str) -> float:
    """mm:ss / hh:mm:ss → 秒；空串返回 0；非法返回 -1。"""
    t = (text or "").strip()
    if not t:
        return 0.0
    m = _TIME_RE.match(t)
    if not m:
        return -1.0
    h = int(m.group(1)) if m.group(1) else 0
    return h * 3600 + int(m.group(2)) * 60 + int(m.group(3))


def calc_clip(start_time: str, end_time: str, max_duration: str,
              video_duration: float) -> tuple[float, float]:
    """根据起止/最大时长计算 (start_sec, duration_sec)。duration=0 表示不裁剪。"""
    start = parse_time(start_time)
    if start < 0:
        raise ValueError(f"开始时间「{start_time}」格式不正确。")
    end = parse_time(end_time)
    if end < 0:
        raise ValueError(f"结束时间「{end_time}」格式不正确。")
    max_d = parse_time(max_duration)
    if max_d < 0:
        raise ValueError(f"最大时长「{max_duration}」格式不正确。")
    if end > 0 and end <= start:
        raise ValueError("结束时间应晚于开始时间。")

    durs: list[float] = []
    if end > 0:
        durs.append(end - start)
    if max_d > 0:
        durs.append(max_d)
    dur = min(durs) if durs else 0.0
    if video_duration > 0 and dur > 0:
        dur = max(0.0, min(dur, video_duration - start))
    return start, dur


def _download_cover(url: str, task_id: int, tmp_dir: str) -> str:
    """下载封面到临时目录，失败返回空串（不阻断流程）。"""
    if not url:
        return ""
    try:
        ext = ".png" if url.lower().endswith(".png") else ".jpg"
        path = os.path.join(tmp_dir, f"cover_{task_id}{ext}")
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as r, open(path, "wb") as f:
            f.write(r.read())
        return path if os.path.getsize(path) > 0 else ""
    except OSError:
        return ""
