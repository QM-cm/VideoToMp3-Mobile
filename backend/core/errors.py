"""统一错误类型与中文提示。"""

from __future__ import annotations


class TaskError(Exception):
    """任务可预期错误：带中文提示与错误类别。"""

    def __init__(self, zh_message: str, kind: str = "unknown"):
        super().__init__(zh_message)
        self.zh = zh_message
        self.kind = kind  # invalid_url/network/platform_blocked/login_required/
                          # not_found/ffmpeg_missing/disk_full/permission/unknown


# 常见错误类别 → 建议（F8 错误处理清单）
ERROR_SUGGESTIONS = {
    "invalid_url": "链接格式不正确或该站点不受支持，请检查链接是否完整。",
    "network": "网络连接失败或超时，请检查网络后重试。",
    "platform_blocked": "该视频受平台限制（地区/版权/会员），按合规要求不绕过，已停止。",
    "login_required": "该视频需要登录或为会员内容，按合规要求不自动登录，已停止。",
    "not_found": "未找到该视频（可能已删除或私密）。",
    "ffmpeg_missing": "未找到 ffmpeg，请在设置中指定 ffmpeg 路径或安装 ffmpeg。",
    "disk_full": "磁盘空间不足，请清理磁盘或更换输出目录。",
    "permission": "权限不足，无法写入目标目录。",
    "unknown": "发生未知错误，可单独重试。",
}
