"""文件名处理：模板渲染、非法字符清理、重名解决（并发安全）。"""

from __future__ import annotations

import os
import re
import threading

# Windows 文件名非法字符
_ILLEGAL_CHARS = re.compile(r'[\\/:*?"<>|\r\n\t]+')
# 首尾禁止的字符
_TRAIL_BAD = " ."

# 进程内已分配（被占位）的文件名集合 + 锁：保证并发任务不撞名
_CLAIM_LOCK = threading.Lock()
_CLAIMED: set[str] = set()


def sanitize_filename(name: str, max_len: int = 120) -> str:
    """清理非法字符与首尾空格/点，限制长度。"""
    if not name:
        return "未命名"
    cleaned = _ILLEGAL_CHARS.sub(" ", str(name))
    cleaned = cleaned.strip().strip(_TRAIL_BAD)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned:
        return "未命名"
    if len(cleaned) > max_len:
        cleaned = cleaned[:max_len].rstrip()
    return cleaned


def render_template(template: str, *, artist: str = "", title: str = "",
                    album: str = "") -> str:
    """渲染命名模板，如 {artist} - {title}.mp3。

    缺 artist 时回退为 title.mp3；缺 title 用占位。
    """
    template = (template or "{artist} - {title}.mp3").strip()
    artist = sanitize_filename(artist) if artist else ""
    title = sanitize_filename(title) if title else "未命名"
    album = sanitize_filename(album) if album else ""

    if "{artist}" in template and not artist:
        # 没有作者：退化为 {title}.mp3
        template = "{title}.mp3"

    name = template.format(artist=artist, title=title, album=album)
    name = sanitize_filename(name, max_len=180)
    return name


def resolve_conflict(directory: str, filename: str) -> str:
    """若目标已存在，自动追加 (1)(2)… 直到不冲突。"""
    if not os.path.exists(os.path.join(directory, filename)):
        return filename
    stem, ext = os.path.splitext(filename)
    i = 1
    while True:
        candidate = f"{stem} ({i}){ext}"
        if not os.path.exists(os.path.join(directory, candidate)):
            return candidate
        i += 1


def claim_filename(directory: str, filename: str) -> str:
    """并发安全地分配一个输出文件名，并立刻在磁盘占位。

    锁内检查「磁盘已存在 + 进程内已分配」，保证两个并发任务即使
    标题/作者完全相同，也会得到 "歌名.mp3" 和 "歌名 (1).mp3" 两个
    互不冲突的路径；占位文件由调用方在成功后用 os.replace 原子替换。
    返回最终路径（绝对路径）。
    """
    directory = os.path.abspath(directory)
    with _CLAIM_LOCK:
        base = filename
        stem, ext = os.path.splitext(base)
        candidate = base
        i = 1
        while (os.path.exists(os.path.join(directory, candidate))
               or candidate in _CLAIMED):
            candidate = f"{stem} ({i}){ext}"
            i += 1
        _CLAIMED.add(candidate)
        path = os.path.join(directory, candidate)
        # 占位：0 字节文件，之后原子替换，避免崩溃时留下半成品
        with open(path, "w", encoding="utf-8"):
            pass
        return path


def release_claim(path: str) -> None:
    """释放占位（转换失败时调用），并清理空占位文件。"""
    name = os.path.basename(path)
    with _CLAIM_LOCK:
        _CLAIMED.discard(name)
    if os.path.exists(path):
        try:
            os.remove(path)
        except OSError:
            pass
