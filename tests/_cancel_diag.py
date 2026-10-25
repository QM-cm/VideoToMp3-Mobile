# -*- coding: utf-8 -*-
"""诊断：cancel 是否真正生效"""
import json, time, urllib.request
from urllib.error import HTTPError

BASE = "http://127.0.0.1:8000"

def call(path, data=None, timeout=30):
    req = urllib.request.Request(BASE + path)
    if data is not None:
        req = urllib.request.Request(BASE + path, json.dumps(data).encode(),
                                     {"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except HTTPError as e:
        try:
            return json.loads(e.read().decode("utf-8", "ignore"))
        except Exception:
            return {"ok": False, "error": f"HTTP {e.code}"}

# 用一个较长的公开视频（BV1GJ411x7h7 是《[4K修复] 亮剑》片段类长视频）
u = "https://www.bilibili.com/video/BV1GJ411x7h7"
r = call("/api/convert", {"urls": [u], "quality": "high", "max_duration": "58:00"}, timeout=60)
print("add:", json.dumps(r, ensure_ascii=False)[:150])
if not r.get("ok"):
    raise SystemExit("add failed")
jid = r["jobs"][0]["jid"]

# 立即取消（尽可能早）
time.sleep(0.5)
cr = call("/api/cancel/" + jid)
print("cancel resp:", json.dumps(cr, ensure_ascii=False))

# 打印状态轨迹
for i in range(25):
    s = call("/api/status/" + jid)
    print(f"[{i}] {s['status']} progress={s.get('progress')} err={str(s.get('error',''))[:60]}")
    if s["status"] in ("done", "failed", "canceled"):
        break
    time.sleep(1.0)
