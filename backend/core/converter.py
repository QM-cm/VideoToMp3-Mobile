"""ffmpeg 封装：转 MP3、裁剪（F3）、比特率/采样率、响度标准化。"""

from __future__ import annotations

import os
import subprocess
import re

from .errors import TaskError

# 项目内置 ffmpeg（tools/ 下便携版）
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BUNDLED_FFMPEG = os.path.join(_PROJECT_ROOT, "tools", "ffmpeg", "bin", "ffmpeg.exe")


def find_ffmpeg(explicit_path: str = "") -> str:
    """定位 ffmpeg 可执行文件：配置路径 > imageio-ffmpeg 包 > 项目内置 > PATH。
    找不到抛 TaskError。"""
    candidates = []
    if explicit_path:
        candidates.append(explicit_path)
    # imageio-ffmpeg 包自带 ffmpeg（pip 安装，最省事）
    try:
        import imageio_ffmpeg
        candidates.append(imageio_ffmpeg.get_ffmpeg_exe())
    except ImportError:
        pass
    candidates.append(BUNDLED_FFMPEG)
    candidates.append("ffmpeg")  # PATH

    for c in candidates:
        try:
            r = subprocess.run(
                [c, "-version"], capture_output=True, timeout=8,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if r.returncode == 0:
                return c
        except (OSError, subprocess.SubprocessError):
            continue
    raise TaskError("未找到 ffmpeg，请安装 imageio-ffmpeg 或在设置中指定路径。",
                    kind="ffmpeg_missing")


def convert_to_mp3(input_path: str, output_path: str, *,
                   bitrate_kbps: int = 192,
                   sample_rate: int = 44100,
                   start_sec: float = 0.0,
                   duration_sec: float = 0.0,
                   normalize_loudness: bool = False,
                   ffmpeg_path: str = "",
                   fmt: str = "mp3") -> None:
    """把任意音频输入转成指定格式（mp3 或 flac 无损）。

    fmt="mp3"：用 bitrate_kbps 有损压缩；
    fmt="flac"：无损压缩，忽略比特率。
    start_sec>0 时从该时间点裁剪；duration_sec>0 时只取该长度。
    """
    ffmpeg = find_ffmpeg(ffmpeg_path)

    cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error"]
    if start_sec and start_sec > 0:
        cmd += ["-ss", f"{start_sec:.3f}"]
    cmd += ["-i", input_path]
    if duration_sec and duration_sec > 0:
        cmd += ["-t", f"{duration_sec:.3f}"]
    cmd += ["-vn", "-ar", str(sample_rate)]
    if fmt == "flac":
        cmd += ["-c:a", "flac", "-f", "flac"]
    else:
        cmd += ["-b:a", f"{bitrate_kbps}k", "-f", "mp3"]
    if normalize_loudness:
        cmd += ["-af", "loudnorm=I=-14:TP=-1.5:LRA=11"]
    cmd.append(output_path)

    try:
        r = subprocess.run(
            cmd, capture_output=True, timeout=600,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except subprocess.TimeoutExpired:
        raise TaskError("转码超时（超过 10 分钟）。", kind="unknown")
    except OSError as e:
        raise TaskError(f"调用 ffmpeg 失败：{e}", kind="ffmpeg_missing")

    if r.returncode != 0:
        err = (r.stderr or b"").decode("utf-8", "ignore").strip()
        raise TaskError(f"转码失败：{err[-200:] or '未知错误'}", kind="unknown")

    if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
        raise TaskError("转码后文件为空。", kind="unknown")


def probe_duration(path: str) -> float:
    """用 mutagen 读 MP3 时长（秒）；失败返回 0。"""
    try:
        from mutagen.mp3 import MP3
        return float(MP3(path).info.length or 0)
    except Exception:
        return 0.0
