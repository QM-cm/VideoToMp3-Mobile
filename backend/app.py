"""手机端同款「视频转 MP3」后端 API（Flask）。

功能与 Windows 版一致：
- 批量解析 / 批量转换（三档音质：普通 128k / 高频 320k / 无损 FLAC）
- 每任务独立裁剪（开始/结束/最大时长）+ 自定义标题
- 并发数限制、任务取消、进度轮询
- SQLite 历史记录（搜索/删除/清空）
- JSON 设置（音质/并发数/命名模板/嵌入封面）
- 写 ID3v2.3 标签 + 封面（复用 core）

部署：python app.py   （监听 0.0.0.0:8000）
"""

from __future__ import annotations

import json
import os
import queue
import sys
import threading
import time
import uuid

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_BACKEND = os.path.join(_ROOT, "backend")
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

from flask import (Flask, jsonify, request, send_from_directory,  # noqa: E402
                   abort)

from core import converter, downloader, metadata, tagger  # noqa: E402
from core.errors import TaskError  # noqa: E402
from core.filename import (claim_filename, release_claim, render_template,  # noqa: E402
                           sanitize_filename)
from core.pipeline import calc_clip, parse_time, _download_cover  # noqa: E402

APP = Flask(__name__, static_folder=None)

TMP = os.path.join(_ROOT, "data", "tmp")
OUT = os.path.join(_ROOT, "data", "output")
DB_PATH = os.path.join(_ROOT, "data", "history.db")
CFG_PATH = os.path.join(_ROOT, "data", "config.json")
os.makedirs(TMP, exist_ok=True)
os.makedirs(OUT, exist_ok=True)

DEFAULT_CFG = {
    "quality": "high",          # standard / high / lossless
    "concurrency": 1,           # 并发任务数（1-5）
    "name_template": "{artist} - {title}.mp3",
    "embed_cover": True,
    "sample_rate": 44100,
    "normalize_loudness": False,
}

# ── 配置 ──────────────────────────────────────────────
CFG_LOCK = threading.Lock()


def _load_cfg() -> dict:
    try:
        with open(CFG_PATH, "r", encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d, dict):
            merged = dict(DEFAULT_CFG)
            merged.update(d)
            return merged
    except (OSError, json.JSONDecodeError):
        pass
    return dict(DEFAULT_CFG)


def _save_cfg(cfg: dict) -> None:
    try:
        with open(CFG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


cfg = _load_cfg()

# ── 任务表 ────────────────────────────────────────────
# jid -> {status, progress, title, artist, error, output_path,
#         cancel: threading.Event, url, custom_title}
JOBS: dict[str, dict] = {}
JOBS_LOCK = threading.Lock()
# 并发控制
_sem: threading.BoundedSemaphore | None = None


def _set(jid: str, **kw) -> None:
    with JOBS_LOCK:
        if jid in JOBS:
            JOBS[jid].update(kw)


def _get(jid: str) -> dict | None:
    with JOBS_LOCK:
        return JOBS.get(jid)


def _new_job(url: str, quality: str) -> dict:
    jid = uuid.uuid4().hex[:12]
    with JOBS_LOCK:
        JOBS[jid] = {
            "status": "queued", "progress": 0, "error": "",
            "output_path": "", "title": "", "artist": "", "url": url,
            "quality": quality, "thumbnail": "", "cancel": threading.Event(),
        }
    return jid


def _semaphore() -> threading.BoundedSemaphore:
    global _sem
    n = max(1, min(5, int(cfg.get("concurrency", 1))))
    if _sem is None or _sem._initial_value != n:  # noqa: SLF001
        _sem = threading.BoundedSemaphore(n)
    return _sem


# ── 历史记录（SQLite） ───────────────────────────────
_db_init_lock = threading.Lock()


def _init_db() -> None:
    with _db_init_lock:
        if os.path.exists(DB_PATH):
            return
        import sqlite3
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    url TEXT NOT NULL,
                    title TEXT DEFAULT '',
                    artist TEXT DEFAULT '',
                    output_path TEXT DEFAULT '',
                    status TEXT DEFAULT 'done',
                    quality TEXT DEFAULT 'high',
                    created_at TEXT DEFAULT (datetime('now', 'localtime'))
                )""")


def _db_add(url, title, artist, output_path, status, quality) -> None:
    import sqlite3
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute(
                "INSERT INTO history (url,title,artist,output_path,status,quality)"
                " VALUES (?,?,?,?,?,?)",
                (url, title, artist, output_path, status, quality))
    except sqlite3.Error:
        pass


def _db_query(q: str = "") -> list[dict]:
    import sqlite3
    try:
        with sqlite3.connect(DB_PATH) as conn:
            if q:
                like = f"%{q}%"
                rows = conn.execute(
                    "SELECT * FROM history WHERE title LIKE ? OR artist LIKE ?"
                    " OR url LIKE ? ORDER BY id DESC LIMIT 200",
                    (like, like, like)).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM history ORDER BY id DESC LIMIT 200").fetchall()
        keys = ("id", "url", "title", "artist", "output_path", "status",
                "quality", "created_at")
        return [dict(zip(keys, r)) for r in rows]
    except sqlite3.Error:
        return []


def _db_delete(rid: int) -> bool:
    import sqlite3
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cur = conn.execute("DELETE FROM history WHERE id=?", (rid,))
            return cur.rowcount > 0
    except sqlite3.Error:
        return False


def _db_clear() -> int:
    import sqlite3
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cur = conn.execute("DELETE FROM history")
            return cur.rowcount
    except sqlite3.Error:
        return 0


_init_db()

# ── 路由：静态前端 ────────────────────────────────────
FRONT = os.path.join(_ROOT, "frontend")


@APP.route("/")
def index():
    return send_from_directory(FRONT, "index.html")


@APP.route("/manifest.json")
def manifest():
    return send_from_directory(FRONT, "manifest.json")


@APP.route("/sw.js")
def sw():
    return send_from_directory(FRONT, "sw.js", mimetype="application/javascript")


@APP.route("/css/<path:name>")
def css(name):
    return send_from_directory(os.path.join(FRONT, "css"), name)


@APP.route("/js/<path:name>")
def js(name):
    return send_from_directory(os.path.join(FRONT, "js"), name)


@APP.route("/icons/<path:name>")
def icons(name):
    return send_from_directory(os.path.join(FRONT, "icons"), name)


# ── 路由：API ─────────────────────────────────────────
@APP.route("/api/health")
def api_health():
    return jsonify({"ok": True, "app": "视频转MP3", "time": time.strftime("%H:%M:%S")})


@APP.route("/api/parse", methods=["POST"])
def api_parse():
    data = request.get_json(force=True, silent=True) or {}
    url = (data.get("url") or "").strip()
    if not url:
        return jsonify({"ok": False, "error": "请输入链接"}), 400
    try:
        info = metadata.extract_metadata(url)
        return jsonify({"ok": True, "info": info})
    except TaskError as e:
        return jsonify({"ok": False, "error": e.zh, "kind": e.kind})


@APP.route("/api/convert", methods=["POST"])
def api_convert():
    """批量添加任务。body: {urls:[...], quality, start_time, end_time,
    max_duration, custom_title}。立即返回全部任务 jid。"""
    data = request.get_json(force=True, silent=True) or {}
    urls = data.get("urls") or []
    if isinstance(urls, str):
        urls = [urls]
    urls = [u.strip() for u in urls if u and u.strip()]
    if not urls:
        return jsonify({"ok": False, "error": "请输入链接"}), 400

    quality = data.get("quality", cfg.get("quality", "high"))
    if quality not in ("standard", "high", "lossless"):
        quality = "high"
    start_t = (data.get("start_time") or "").strip()
    end_t = (data.get("end_time") or "").strip()
    max_t = (data.get("max_duration") or "").strip()
    custom = (data.get("custom_title") or "").strip()
    # 预校验长度格式，全部任务统一参数
    for name, val in (("开始时间", start_t), ("结束时间", end_t), ("最大时长", max_t)):
        if val:
            p = parse_time(val)
            if p < 0:
                return jsonify({"ok": False, "error": f"{name}「{val}」格式不正确，请用 mm:ss 或 hh:mm:ss"}), 400
    if start_t and end_t and parse_time(end_t) <= parse_time(start_t):
        return jsonify({"ok": False, "error": "结束时间应晚于开始时间"}), 400

    jobs = []
    for url in urls:
        jid = _new_job(url, quality)
        jobs.append({"jid": jid, "url": url})
        threading.Thread(
            target=_work, daemon=True,
            args=(jid, url, quality, start_t, end_t, max_t, custom),
        ).start()
    return jsonify({"ok": True, "jobs": jobs, "quality": quality})


def _work(jid, url, quality, start_t, end_t, max_t, custom_title) -> None:
    job = _get(jid)
    sem = _semaphore()
    sem.acquire()
    try:
        if job is None or job["cancel"].is_set():
            return
        _set(jid, status="parsing", progress=2)
        info = metadata.extract_metadata(url)
        title = info["title"] or ""
        artist = info["artist"] or ""
        _set(jid, title=title, artist=artist, progress=5,
             thumbnail=info.get("thumbnail", ""),
             duration=info.get("duration", 0))

        tid = hash(jid) % 100000
        cover = _download_cover(info.get("thumbnail", ""), tid, TMP)
        if job["cancel"].is_set():
            _set(jid, status="canceled", progress=0)
            return

        start_sec, dur = _calc(start_t, end_t, max_t, info.get("duration", 0))
        _set(jid, status="downloading", progress=8)
        try:
            src = downloader.download_bestaudio(
                url, TMP, tid,
                progress_cb=lambda p: _set(jid, progress=8 + int(p * 0.4)),
                cancelled=job["cancel"].is_set)
        except TaskError as e:
            if e.kind == "canceled":
                _set(jid, status="canceled", progress=0)
                return
            raise

        _set(jid, status="converting", progress=55)
        if quality == "lossless":
            fmt, ext, bitrate = "flac", ".flac", 0
        elif quality == "standard":
            fmt, ext, bitrate = "mp3", ".mp3", 128
        else:
            fmt, ext, bitrate = "mp3", ".mp3", 320

        final_title = custom_title or title
        template = cfg.get("name_template", "{artist} - {title}.mp3")
        if "." in template:
            template = template[:template.rfind(".")] + ext
        fname = render_template(template, artist=artist, title=final_title)
        final_path = claim_filename(OUT, fname)
        part_path = final_path + f".part{tid}"
        try:
            converter.convert_to_mp3(
                src, part_path,
                bitrate_kbps=bitrate or 192,
                sample_rate=int(cfg.get("sample_rate", 44100)),
                start_sec=start_sec, duration_sec=dur,
                normalize_loudness=bool(cfg.get("normalize_loudness", False)),
                ffmpeg_path="", fmt=fmt)
            if cfg.get("embed_cover", True):
                tagger.write_tags(part_path, fmt=fmt, title=final_title,
                                  artist=artist, album="", cover_path=cover)
            os.replace(part_path, final_path)
        except Exception:
            if os.path.exists(part_path):
                try:
                    os.remove(part_path)
                except OSError:
                    pass
            release_claim(final_path)
            raise
        if job["cancel"].is_set():
            release_claim(final_path)
            if os.path.exists(final_path):
                try:
                    os.remove(final_path)
                except OSError:
                    pass
            _set(jid, status="canceled", progress=0)
            return

        _set(jid, status="done", progress=100, output_path=final_path)
        _db_add(url, final_title, artist, final_path, "done", quality)
    except TaskError as e:
        _set(jid, status="failed", error=e.zh)
        _db_add(url, "", "", "", "failed", quality)
    except Exception as e:  # noqa: BLE001
        _set(jid, status="failed", error=f"未知错误：{str(e)[:200]}")
        _db_add(url, "", "", "", "failed", quality)
    finally:
        sem.release()


def _calc(start_t: str, end_t: str, max_t: str, video_duration: float) -> tuple[float, float]:
    """裁剪参数 → (start_sec, duration_sec)。与 Windows 版 calc_clip 一致。"""
    start = parse_time(start_t)
    if start < 0:
        raise TaskError(f"开始时间「{start_t}」格式不正确。")
    end = parse_time(end_t)
    if end < 0:
        raise TaskError(f"结束时间「{end_t}」格式不正确。")
    max_d = parse_time(max_t)
    if max_d < 0:
        raise TaskError(f"最大时长「{max_t}」格式不正确。")
    if end > 0 and end <= start:
        raise TaskError("结束时间应晚于开始时间。")
    durs: list[float] = []
    if end > 0:
        durs.append(end - start)
    if max_d > 0:
        durs.append(max_d)
    dur = min(durs) if durs else 0.0
    if video_duration > 0 and dur > 0:
        dur = max(0.0, min(dur, video_duration - start))
    return start, dur


@APP.route("/api/status/<jid>")
def api_status(jid):
    j = _get(jid)
    if j is None:
        return jsonify({"ok": False, "error": "任务不存在"}), 404
    # 不返回 cancel Event（不可序列化）
    out = {k: v for k, v in j.items() if k != "cancel"}
    return jsonify({"ok": True, **out})


@APP.route("/api/cancel/<jid>", methods=["POST"])
def api_cancel(jid):
    j = _get(jid)
    if j is None:
        return jsonify({"ok": False, "error": "任务不存在"}), 404
    if j["status"] in ("done", "failed", "canceled"):
        return jsonify({"ok": True, "status": j["status"]})
    j["cancel"].set()
    _set(jid, status="canceling")
    return jsonify({"ok": True, "status": "canceling"})


@APP.route("/api/download/<jid>")
def api_download(jid):
    j = _get(jid)
    if not j or j.get("status") != "done" or not j.get("output_path"):
        return jsonify({"ok": False, "error": "文件还没准备好"}), 404
    path = j["output_path"]
    if not os.path.exists(path):
        return jsonify({"ok": False, "error": "文件已被清理"}), 404
    return send_from_directory(
        os.path.dirname(path), os.path.basename(path),
        as_attachment=True, download_name=os.path.basename(path))


# ── 历史记录 API ──────────────────────────────────────
@APP.route("/api/history")
def api_history():
    q = (request.args.get("q") or "").strip()
    return jsonify({"ok": True, "records": _db_query(q)})


@APP.route("/api/history/<int:rid>", methods=["DELETE"])
def api_history_delete(rid):
    ok = _db_delete(rid)
    return jsonify({"ok": ok})


@APP.route("/api/history/clear", methods=["POST"])
def api_history_clear():
    n = _db_clear()
    return jsonify({"ok": True, "deleted": n})


# ── 设置 API ──────────────────────────────────────────
@APP.route("/api/settings")
def api_settings():
    with CFG_LOCK:
        safe = {k: v for k, v in cfg.items()}
    return jsonify({"ok": True, "settings": safe})


@APP.route("/api/settings", methods=["POST"])
def api_settings_save():
    global cfg
    data = request.get_json(force=True, silent=True) or {}
    with CFG_LOCK:
        for k in ("quality", "concurrency", "name_template", "embed_cover",
                  "sample_rate", "normalize_loudness"):
            if k in data:
                cfg[k] = data[k]
        # 简单校验
        if cfg.get("quality") not in ("standard", "high", "lossless"):
            cfg["quality"] = "high"
        try:
            cfg["concurrency"] = max(1, min(5, int(cfg.get("concurrency", 1))))
        except (TypeError, ValueError):
            cfg["concurrency"] = 1
        try:
            cfg["sample_rate"] = int(cfg.get("sample_rate", 44100))
        except (TypeError, ValueError):
            cfg["sample_rate"] = 44100
        cfg["normalize_loudness"] = bool(cfg.get("normalize_loudness", False))
        _save_cfg(cfg)
        safe = {k: v for k, v in cfg.items()}
    return jsonify({"ok": True, "settings": safe})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    print("\n  手机端「视频转 MP3」服务已启动")
    print(f"  本机访问:  http://127.0.0.1:{port}")
    print(f"  手机访问:  http://<公网IP或域名>:{port}  （部署到公网后）\n")
    APP.run(host="0.0.0.0", port=port, debug=False, threaded=True)
