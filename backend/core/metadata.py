"""yt-dlp 封装：解析视频元数据（F2）。"""

from __future__ import annotations

from .errors import TaskError
from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError, ExtractorError


def _classify(exc: Exception) -> tuple[str, str]:
    """把 yt-dlp 异常映射为 (kind, 中文提示)。"""
    msg = str(exc).lower()
    zh = str(exc)

    if "unsupported url" in msg or "no supported" in msg or "not a valid url" in msg:
        return "invalid_url", "链接格式不正确或该站点不受支持。"
    if "private" in msg or "login" in msg or "sign in" in msg or "member" in msg:
        return "login_required", "该视频需要登录或为会员内容，按合规要求不自动登录。"
    if "not available" in msg or "geo" in msg or "region" in msg or "copyright" in msg:
        return "platform_blocked", "该视频受平台限制（地区/版权/会员），按合规要求不绕过。"
    if "timed out" in msg or "timedout" in msg or "network" in msg or "connection" in msg:
        return "network", "网络连接失败或超时，请检查网络后重试。"
    if "404" in msg or "not found" in msg or "removed" in msg or "deleted" in msg:
        return "not_found", "未找到该视频（可能已删除或为私密视频）。"

    # 兜底：截取最后一行有效信息
    short = zh.splitlines()[-1] if zh.splitlines() else zh
    return "unknown", f"解析失败：{short[:120]}"


def extract_metadata(url: str) -> dict:
    """解析视频元数据，返回 {title, artist, duration, thumbnail, extractor, webpage_url}。

    失败抛 TaskError（含中文提示）。
    """
    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": True,
        "default_search": "never",
    }
    try:
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except (DownloadError, ExtractorError) as e:
        kind, zh = _classify(e)
        raise TaskError(zh, kind=kind) from e

    if not info:
        raise TaskError("未能解析该链接的视频信息。", kind="not_found")

    artist = (info.get("uploader") or info.get("creator")
              or info.get("channel") or "")
    return {
        "title": info.get("title") or "未命名",
        "artist": artist,
        "duration": float(info.get("duration") or 0),
        "thumbnail": info.get("thumbnail") or "",
        "extractor": info.get("extractor_key") or "",
        "webpage_url": info.get("webpage_url") or url,
    }
