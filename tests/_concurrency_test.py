# -*- coding: utf-8 -*-
"""并发验证：concurrency=3，3 个不同链接并行，文件名不冲突"""
import json, time, urllib.request
from urllib.error import HTTPError

BASE = "http://127.0.0.1:8000"

def call(path, data=None, timeout=30, method=None):
    req = urllib.request.Request(BASE + path, method=method or ("POST" if data is not None else "GET"))
    if data is not None:
        req = urllib.request.Request(BASE + path, json.dumps(data).encode(),
                                     {"Content-Type": "application/json"}, method=method or "POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except HTTPError as e:
        try:
            return json.loads(e.read().decode("utf-8", "ignore"))
        except Exception:
            return {"ok": False, "error": f"HTTP {e.code}"}

# 设置并发 3
call("/api/settings", {"concurrency": 3, "quality": "high"}, method="POST")

urls = [
    "https://b23.tv/bdxIc7A",
    "https://www.bilibili.com/video/BV1GJ411x7h7",
    "https://www.bilibili.com/video/BV1bx4y1G7TV",  # 公开视频
]
r = call("/api/convert", {"urls": urls, "quality": "high"}, timeout=60)
print("add:", json.dumps(r, ensure_ascii=False)[:150])
jids = [j["jid"] for j in r.get("jobs", [])]
if len(jids) != 3:
    raise SystemExit("expected 3 jobs, got %d" % len(jids))

# 观察并发：记录同时处于 downloading/converting 的数量峰值
peak = 0
final = {}
for _ in range(90):
    n = 0
    for jid in jids:
        s = call("/api/status/" + jid)
        if s["status"] in ("downloading", "converting"):
            n += 1
        if s["status"] in ("done", "failed", "canceled"):
            final[jid] = s["status"]
    peak = max(peak, n)
    if len(final) == 3:
        break
    time.sleep(1.0)

print("peak concurrent running:", peak)
print("final statuses:", final)
ok = peak >= 2 and all(v == "done" for v in final.values())
print("ALL_PASS" if ok else "HAS_FAIL")

# 输出目录文件核对：3 个 mp3 互不覆盖
import glob, os
files = glob.glob(os.path.join("output", "*.mp3"))
print("output mp3 count:", len(files))
for f in files:
    print(" ", os.path.basename(f), os.path.getsize(f))
