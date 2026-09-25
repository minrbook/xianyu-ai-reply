#!/usr/bin/env python3
"""只在首次部署创建随机凭据；绝不覆盖旧密钥或输出密码。"""
import base64
import os
from pathlib import Path
import secrets

root = Path(__file__).resolve().parent.parent
secret_dir = root / ".secrets"

def write_secret(path, content):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(content + "\n")

def main():
    if (root / ".env").exists() and not (secret_dir / "credential_key").exists():
        raise SystemExit("发现已有 .env，但没有加密密钥。旧部署请先备份并按 SECURITY.md 迁移；禁止自动生成替代密钥。")
    secret_dir.mkdir(mode=0o700, exist_ok=True)
    secret_dir.chmod(0o700)
    for name, value in [("credential_key", base64.urlsafe_b64encode(os.urandom(32)).decode()), ("admin_password", secrets.token_urlsafe(24))]:
        path = secret_dir / name
        if not path.exists():
            write_secret(path, value)
        path.chmod(0o600)
    env = root / ".env"
    if not env.exists():
        values = {
            "MYSQL_ROOT_PASSWORD": secrets.token_hex(24),
            "MYSQL_USER": "xianyu", "MYSQL_DATABASE": "xianyu_data",
            "MYSQL_PASSWORD": secrets.token_hex(24), "REDIS_PASSWORD": secrets.token_hex(24),
            "SQL_ECHO": "false", "CORS_ORIGINS": "",
            "ENABLE_REMOTE_ADS": "false", "ENABLE_REMOTE_ANNOUNCEMENTS": "false",
            "ENABLE_REMOTE_POPUP_ANNOUNCEMENTS": "false", "REMOTE_CREDENTIAL_ORIGINS": "",
        }
        write_secret(env, "\n".join(f"{k}={v}" for k,v in values.items()))
    env.chmod(0o600)
    print("配置已准备，原有密钥保持不变。初始管理员密码位于 .secrets/admin_password；请独立备份 .secrets/credential_key。")

if __name__ == "__main__":
    main()
