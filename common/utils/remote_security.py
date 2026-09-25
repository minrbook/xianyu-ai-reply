"""远程凭据交互默认禁用，只允许部署者列出的 HTTPS origin。"""
from urllib.parse import urlsplit
from common.core.config import get_settings

def require_trusted_remote(url: str) -> None:
    target = urlsplit(url)
    if target.scheme != "https" or not target.hostname or target.username or target.password or target.fragment:
        raise ValueError("远程凭据接口必须使用无用户信息的 HTTPS 地址")
    origin = f"https://{target.netloc.lower()}"
    allowed = {s.strip().rstrip("/").lower() for s in get_settings().remote_credential_origins.split(",") if s.strip()}
    if origin not in allowed:
        raise ValueError("远程凭据传输已禁止：需在 REMOTE_CREDENTIAL_ORIGINS 显式允许此 HTTPS origin")
