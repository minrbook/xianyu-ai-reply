"""
在线更新模块

功能：
1. 从服务器获取最新版本信息（version.json）
2. 对比本地版本号，判断是否需要更新
3. 下载新版本压缩包到临时目录
4. 生成更新脚本（bat），等待当前进程退出后覆盖并重启

服务器端需要提供：
- {UPDATE_URL}/version.json  版本信息文件
- {UPDATE_URL}/app-vX.X.X.zip  完整程序压缩包

version.json 格式示例：
{
    "version": "1.1.0",
    "description": "1. 修复xxx\\n2. 新增xxx",
    "filename": "app-v1.1.0.zip"
}
"""
import json
import os
import sys
import tempfile
import urllib.request
import urllib.error
from pathlib import Path

from launcher.version import CURRENT_VERSION

# 更新服务器地址（从 data/update_config.json 读取）
_DEFAULT_UPDATE_URL = "https://xy-update.zhinianboke.com"


def _get_update_url() -> str:
    """
    获取更新服务器地址

    优先从 data/update_config.json 读取，否则使用默认值。
    Returns:
        更新服务器基础URL（不含尾部斜杠）
    """
    try:
        from launcher.frozen_detect import get_project_root
        base_dir = get_project_root()
        config_path = base_dir / "data" / "update_config.json"
        if config_path.exists():
            data = json.loads(config_path.read_text(encoding="utf-8"))
            url = data.get("update_url", "").rstrip("/")
            if url:
                return url
    except Exception:
        pass
    return _DEFAULT_UPDATE_URL


def _compare_versions(local: str, remote: str) -> bool:
    """
    比较版本号，判断远程版本是否比本地新

    Args:
        local: 本地版本号，如 "1.0.0"
        remote: 远程版本号，如 "1.1.0"
    Returns:
        True表示远程版本更新，需要升级
    """
    try:
        local_parts = [int(x) for x in local.split(".")]
        remote_parts = [int(x) for x in remote.split(".")]
        return remote_parts > local_parts
    except (ValueError, AttributeError):
        return False


def check_update() -> dict:
    """
    检查是否有新版本可用

    从服务器获取 version.json 并与本地版本对比。

    Returns:
        字典包含:
        - has_update: bool 是否有新版本
        - current_version: str 当前版本号
        - remote_version: str 远程版本号（无更新时为空）
        - description: str 更新说明
        - filename: str 下载文件名
        - md5: str 文件MD5校验值
        - error: str 错误信息（正常时为空）
    """
    result = {
        "has_update": False,
        "current_version": CURRENT_VERSION,
        "remote_version": "",
        "description": "",
        "filename": "",
        "error": "",
    }

    update_url = _get_update_url()
    version_url = f"{update_url}/version.json"

    try:
        req = urllib.request.Request(version_url, method="GET")
        req.add_header("User-Agent", "XianyuAutoReply-Updater")
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as e:
        result["error"] = f"无法连接更新服务器: {e.reason}"
        return result
    except Exception as e:
        result["error"] = f"检查更新失败: {str(e)}"
        return result

    remote_ver = data.get("version", "")
    if not remote_ver:
        result["error"] = "服务器返回的版本信息无效"
        return result

    result["remote_version"] = remote_ver
    result["description"] = data.get("description", "无更新说明")
    result["filename"] = data.get("filename", "")

    if _compare_versions(CURRENT_VERSION, remote_ver):
        result["has_update"] = True

    return result


def download_update(filename: str,
                    progress_callback=None) -> dict:
    """未引入独立签名验证前，禁止下载和执行远程更新。"""
    return {"success": False, "file_path": "", "error": "安全加固版禁用未签名更新，请审查源码后重新构建"}


def apply_update(zip_path: str) -> dict:
    """未引入独立签名验证前，禁止下载和执行远程更新。"""
    return {"success": False, "file_path": "", "error": "安全加固版禁用未签名更新，请审查源码后重新构建"}
