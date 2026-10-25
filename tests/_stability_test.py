# -*- coding: utf-8 -*-
"""稳定性回归 v2：去重 / 完成 / 下载中取消 / 转码中取消"""
import json, time, urllib.request
from urllib.error import HTTPError

BASE = "http://127.0.0.1:8000"

def call(path, data=None, timeout=30, method=None):
    req = urllib.request.Request(BASE + path)
    if data is not None:
        req = urllib.request.Request(BASE + path, json.dumps(data).encode(),
                                     {"Content-Type": "application/json"})
    if method:
        req = urllib.request.Request(BASE + path, method=method)
        if data is not None:
            req = urllib.request.Request(BASE + path, json.dumps(data).encode(),
                                         {"Content-Type": "application/json"},
                                         method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except HTTPError as e:
        try:
            return json.loads(e.read().decode("utf-8", "ignore"))
        except Exception:
            return {"ok": False, "error": f"HTTP {e.code}"}

def wait_status(jid, targets, limit=120, interval=0.6):
    for _ in range(int(limit / interval)):
        s = call("/api/status/" + jid)
        if s["status"] in targets:
            return s
        time.sleep(interval)
    return call("/api/status/" + jid)

ok = True
def check(name, cond, extra=""):
    global ok
    print(("PASS" if cond else "FAIL") + " | " + name + (" | " + extra if extra else ""))
    if not cond:
        ok = False

# 1. 重复添加去重
u = "https://b23.tv/bdxIc7A"
r1 = call("/api/convert", {"urls": [u], "quality": "high"}, timeout=60)
check("首次添加", r1.get("ok") and len(r1.get("jobs", [])) == 1, str(r1)[:120])
jid = r1["jobs"][0]["jid"]
r2 = call("/api/convert", {"urls": [u], "quality": "high"}, timeout=30)
check("重复添加被拒绝", r2.get("ok") is False and "已在任务列表" in r2.get("error", ""), str(r2)[:120])

# 2. 任务完成
s = wait_status(jid, ("done", "failed", "canceled"), limit=180)
check("任务完成(done)", s["status"] == "done", "status=" + s["status"])

# 3. 转码中取消：等任务进入 converting 立即取消
u3 = "https://b23.tv/bdxIc7A"
r3 = call("/api/convert", {"urls": [u3], "quality": "lossless"}, timeout=60)
jid3 = r3["jobs"][0]["jid"] if r3.get("ok") else None
check("FLAC任务添加", jid3 is not None, str(r3)[:120])
if jid3:
    s3 = wait_status(jid3, ("converting", "done", "failed", "canceled"), limit=120)
    if s3["status"] in ("converting", "downloading"):
        call("/api/cancel/" + jid3, method="POST")
        s3f = wait_status(jid3, ("canceled", "done", "failed"), limit=40)
        check("转码中取消生效", s3f["status"] == "canceled", "final=" + s3f["status"])
    elif s3["status"] == "done":
        print("SKIP | 转码中取消（视频太短，未捕捉到转换窗口）")
    else:
        check("转码中取消生效", False, "unexpected=" + s3["status"] + " err=" + str(s3.get("error", ""))[:100])

# 4. 下载中取消：长视频
u4 = "https://www.bilibili.com/video/BV1GJ411x7h7"
r4 = call("/api/convert", {"urls": [u4], "quality": "high", "max_duration": "59:00"}, timeout=60)
jid4 = r4["jobs"][0]["jid"] if r4.get("ok") else None
check("长视频任务添加", jid4 is not None, str(r4)[:120])
if jid4:
    s4 = wait_status(jid4, ("downloading", "converting", "done", "failed", "canceled"), limit=90)
    if s4["status"] in ("downloading", "converting", "parsing"):
        call("/api/cancel/" + jid4, method="POST")
        s4f = wait_status(jid4, ("canceled", "done", "failed"), limit=40)
        check("下载/解析中取消生效", s4f["status"] == "canceled", "final=" + s4f["status"])
    elif s4["status"] == "done":
        print("SKIP | 下载中取消（视频下载过快，已直接完成）")
    else:
        check("下载中取消生效", False, "unexpected=" + s4["status"] + " err=" + str(s4.get("error", ""))[:100])

print("ALL_PASS" if ok else "HAS_FAIL")
