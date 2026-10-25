"""yt-dlp 封装：下载最佳音频流（F4）。

- 临时文件带 uuid，重试/并发互不冲突；
- 支持取消（进度 hook 内检查，取消立即中断下载）；
- 下载后用 glob 匹配实际文件，兼容多流/扩展名差异。
"""

from __future__ import annotations

import glob
import os
import uuid
from typing import Callable

from .errors import TaskError
from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError, ExtractorError


class _CancelledError(Exception):
    """下载中途被取消（内部信号）。"""


def download_bestaudio(url: str, tmp_dir: str, task_id: int,
                       progress_cb: Callable[[int], None] | None = None,
                       cancelled: Callable[[], bool] | None = None) -> str:
    """下载最佳音频到临时目录，返回下载的本地文件路径。

    progress_cb(0-100) 实时回报下载进度；cancelled() 为 True 时立即中断。
    """
    os.makedirs(tmp_dir, exist_ok=True)
    token = uuid.uuid4().hex[:8]
    out_tmpl = os.path.join(tmp_dir, f"task_{task_id}_{token}.%(ext)s")

    def hook(d: dict):
        if cancelled is not None and cancelled():
            raise _CancelledError()
        if progress_cb is None:
            return
        if d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            downloaded = d.get("downloaded_bytes", 0) or 0
            if total:
                progress_cb(min(99, int(downloaded / total * 100)))
        elif d.get("status") == "finished":
            progress_cb(100)

    opts = {
        "format": "bestaudio/best",
        "outtmpl": out_tmpl,
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "noprogress": True,
        "progress_hooks": [hook],
    }

    try:
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            ydl.prepare_filename(info)  # 触发文件名解析（结果用 glob 兜底）
    except _CancelledError:
        raise TaskError("任务已取消。", kind="canceled")
    except (DownloadError, ExtractorError, OSError) as e:
        msg = str(e).lower()
        if "no space" in msg or "disk" in msg:
            raise TaskError("磁盘空间不足，无法下载。", kind="disk_full") from e
        if "timed out" in msg or "network" in msg or "connection" in msg:
            raise TaskError("网络连接失败或超时。", kind="network") from e
        raise TaskError(f"下载失败：{str(e)[:120]}", kind="unknown") from e

    # glob 匹配本 token 的实际输出（兼容 .m4a/.webm/.mp3 等）
    pattern = os.path.join(tmp_dir, f"task_{task_id}_{token}.*")
    matches = [p for p in glob.glob(pattern) if not p.endswith(".part")]
    if not matches:
        raise TaskError("下载完成但未找到文件。", kind="unknown")
    # 去掉 yt-dlp 可能残留的 .part 后缀文件，取最大的实际文件
    matches = sorted(matches, key=os.path.getsize, reverse=True)
    return matches[0]
