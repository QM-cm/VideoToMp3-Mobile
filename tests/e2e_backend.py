"""手机端后端端到端验证：parse → convert（裁剪+自定义标题）→ 轮询 → 下载。"""
import json
import os
import time
import urllib.request

BASE = "http://127.0.0.1:8000"
URL = "https://b23.tv/bdxIc7A"


def post(path, data):
    req = urllib.request.Request(
        BASE + path, data=json.dumps(data).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def get(path):
    with urllib.request.urlopen(BASE + path, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


# 1) 解析
info = post("/api/parse", {"url": URL})
assert info["ok"], info
print("[1] 解析:", info["info"]["title"], "| 时长:", info["info"]["duration"], "s | 作者:", info["info"]["artist"])

# 2) 转换：裁剪前 60s + 自定义标题
d = post("/api/convert", {
    "urls": [URL],
    "quality": "high",
    "start_time": "00:00",
    "max_duration": "01:00",
    "custom_title": "手机端测试歌",
})
assert d["ok"], d
jid = d["jobs"][0]["jid"]
print("[2] 任务已创建:", jid)

# 3) 轮询
deadline = time.time() + 240
last = ""
while time.time() < deadline:
    st = get(f"/api/status/{jid}")
    line = f"status={st['status']} progress={st['progress']}%"
    if st.get("error"):
        line += f" error={st['error']}"
    if line != last:
        print("   ", line)
        last = line
    if st["status"] in ("done", "failed", "canceled"):
        break
    time.sleep(1.5)

assert st["status"] == "done", f"任务失败: {st}"
out = st["output_path"]
print("[3] 完成, 文件:", out)
print("    存在:", os.path.exists(out), "| 大小:", os.path.getsize(out), "bytes")

# 4) 读回标签验证（APIC 用 getall 判断，ID3 帧键是 "APIC:"）
from mutagen.id3 import ID3
tags = ID3(out)
has_cover = len(tags.getall("APIC")) > 0
print("[4] 标签:", tags.get("TIT2").text, "|", tags.get("TPE1").text,
      "| 封面:", has_cover)
assert tags.get("TIT2").text[0] == "手机端测试歌"
assert tags.get("TPE1").text[0] == "是一天day"
assert has_cover, "应写入封面"

# 5) 时长验证（裁剪 60s）
import mutagen
au = mutagen.File(out)
print("[5] 时长:", round(au.info.length, 1), "s (期望约 60s)")

# 6) 下载接口
req = urllib.request.Request(f"{BASE}/api/download/{jid}")
with urllib.request.urlopen(req, timeout=30) as r:
    data = r.read()
print("[6] 下载接口:", len(data), "bytes")

# 7) 历史记录
h = get("/api/history")
print("[7] 历史条数:", len(h["records"]), "| 最新:", h["records"][0]["title"])

# 8) 设置读写
s = get("/api/settings")
print("[8] 设置:", s["settings"]["quality"], "| 并发:", s["settings"]["concurrency"])
post("/api/settings", {"concurrency": 2, "quality": "lossless"})
s2 = get("/api/settings")
assert s2["settings"]["concurrency"] == 2 and s2["settings"]["quality"] == "lossless"
post("/api/settings", {"concurrency": 1, "quality": "high"})
print("    设置保存+回读 OK")

print("\nE2E_ALL_OK")
