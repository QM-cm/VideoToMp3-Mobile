"""mutagen 封装：写 ID3v2.3 标签（兼容老 MP4 播放器）。"""

from __future__ import annotations

import os

from .errors import TaskError
from mutagen.id3 import (APIC, ID3, TALB, TIT2, TPE1, ID3NoHeaderError)


def write_mp3_tags(mp3_path: str, *, title: str = "", artist: str = "",
                   album: str = "", cover_path: str = "") -> None:
    """写入标题/艺术家/专辑/封面；ID3v2.3 版本（兼容老设备）。"""
    try:
        try:
            tags = ID3(mp3_path)
        except ID3NoHeaderError:
            tags = ID3()

        if title:
            tags.setall("TIT2", [TIT2(encoding=3, text=title)])
        if artist:
            tags.setall("TPE1", [TPE1(encoding=3, text=artist)])
        if album:
            tags.setall("TALB", [TALB(encoding=3, text=album)])

        if cover_path and os.path.exists(cover_path):
            with open(cover_path, "rb") as f:
                data = f.read()
            mime = "image/png" if cover_path.lower().endswith(".png") else "image/jpeg"
            # type=3 为封面（front cover）
            tags.setall("APIC:", [APIC(encoding=3, mime=mime, type=3, data=data)])

        # v2_version=3 → ID3v2.3，老 MP4/MP3 设备可读
        tags.save(mp3_path, v2_version=3)
    except TaskError:
        raise
    except Exception as e:  # mutagen 各类异常
        raise TaskError(f"写入歌曲信息失败：{e}", kind="unknown") from e


def read_mp3_tags(mp3_path: str) -> dict:
    """读取标签（验证用）。"""
    out = {"title": "", "artist": "", "album": "", "has_cover": False}
    try:
        tags = ID3(mp3_path)
    except ID3NoHeaderError:
        return out
    if "TIT2" in tags:
        out["title"] = str(tags["TIT2"])
    if "TPE1" in tags:
        out["artist"] = str(tags["TPE1"])
    if "TALB" in tags:
        out["album"] = str(tags["TALB"])
    out["has_cover"] = any(k.startswith("APIC") for k in tags.keys())
    return out


def write_tags(path: str, fmt: str = "mp3", *, title: str = "",
               artist: str = "", album: str = "", cover_path: str = "") -> None:
    """按格式写标签：mp3 → ID3v2.3；flac → Vorbis comment。"""
    if fmt == "flac":
        _write_flac_tags(path, title=title, artist=artist, album=album,
                         cover_path=cover_path)
    else:
        write_mp3_tags(path, title=title, artist=artist, album=album,
                       cover_path=cover_path)


def _write_flac_tags(path: str, *, title: str, artist: str, album: str,
                      cover_path: str) -> None:
    """FLAC 用 mutagen.flac。"""
    try:
        from mutagen.flac import FLAC, Picture
        audio = FLAC(path)
    except Exception as e:  # noqa: BLE001
        raise TaskError(f"打开 FLAC 失败：{e}", kind="unknown") from e

    if title:
        audio["title"] = title
    if artist:
        audio["artist"] = artist
    if album:
        audio["album"] = album
    if cover_path and os.path.exists(cover_path):
        pic = Picture()
        with open(cover_path, "rb") as f:
            pic.data = f.read()
        pic.type = 3
        pic.mime = "image/png" if cover_path.lower().endswith(".png") else "image/jpeg"
        audio.clear_pictures()
        audio.add_picture(pic)
    audio.save()
