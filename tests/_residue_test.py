# -*- coding: utf-8 -*-
"""取消后无残留验证：转码中取消 → tmp/output 无 .part 残留"""
import glob, json, os, time, urllib.request
from urllib.error import HTTPError

BASE = "http://127.0.0.1:8000"
TMP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "tmp")
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "output")

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

before_tmp = set(os.listdir(TMP)) if os.path.isdir(TMP) else set()

# 加 FLAC 任务（转码较久），进入 converting 后取消
r = call("/api/convert", {"urls": ["https://b23.tv/bdxIc7A"], "quality": "lossless"}, timeout=60)
jid = r["jobs"][0]["jid"] if r.get("ok") else None
check("FLAC任务添加", jid is not None, str(r)[:120])
if jid:
    s = wait_status(jid, ("converting", "done", "failed", "canceled"))
    if s["status"] in ("converting", "downloading"):
        call("/api/cancel/" + jid, method="POST")
        sf = wait_status(jid, ("canceled", "done", "failed"), limit=40)
        check("FLAC取消成功", sf["status"] == "canceled", "final=" + sf["status"])
    else:
        check("FLAC取消成功", False, "unexpected=" + s["status"])
    time.sleep(2)

# 检查残留：tmp 下新增的 .part / 大文件；output 下新增 .part
new_tmp = [f for f in os.listdir(TMP) if f not in before_tmp] if os.path.isdir(TMP) else []
residuals = [f for f in new_tmp if f.endswith(".part") or f.startswith("cover_")]
out_parts = glob.glob(os.path.join(OUT, "*.part*"))
print("new tmp files:", new_tmp)
print("output part residuals:", out_parts)
check("无 .part / cover 残留", not residuals and not out_parts,
      "resid=" + str(residuals) + " out=" + str([os.path.basename(x) for x in out_parts]))

print("ALL_PASS" if ok else "HAS_FAIL")
