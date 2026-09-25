"""数据库凭据加密。密钥由部署环境单独保管，缺失/错误时拒绝读写。"""
from functools import lru_cache
import json
from pathlib import Path
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import Text, JSON
from sqlalchemy.types import TypeDecorator

PREFIX = "enc:v1:"

@lru_cache(maxsize=1)
def credential_cipher():
    from common.core.config import get_settings
    settings = get_settings()
    if not settings.credential_encryption_key_file:
        raise RuntimeError("必须配置 CREDENTIAL_ENCRYPTION_KEY_FILE，禁止明文存储凭据")
    key = Path(settings.credential_encryption_key_file).read_bytes().strip()
    try:
        return Fernet(key)
    except ValueError:
        raise RuntimeError("凭据加密密钥格式错误") from None

def encrypt_credential(value):
    if value is None or value == "":
        return value
    return PREFIX + credential_cipher().encrypt(value.encode()).decode()

def decrypt_credential(value):
    if value is None or value == "":
        return value
    if not isinstance(value, str) or not value.startswith(PREFIX):
        raise RuntimeError("检测到旧版明文凭据，请停机执行凭据迁移")
    try:
        return credential_cipher().decrypt(value[len(PREFIX):].encode()).decode()
    except InvalidToken:
        raise RuntimeError("凭据解密失败：密钥不匹配或密文被修改") from None

class EncryptedText(TypeDecorator):
    impl = Text
    cache_ok = True
    def process_bind_param(self, value, dialect):
        return encrypt_credential(value)
    def process_result_value(self, value, dialect):
        return decrypt_credential(value)

class AccountMetadata(TypeDecorator):
    """仅加密 JSON 中的浏览器 Cookie 快照，保留其他 metadata 查询语义。"""
    impl = JSON
    cache_ok = True
    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        result = dict(value)
        if result.get("cookies_refresh_snapshot") is not None:
            result["cookies_refresh_snapshot"] = encrypt_credential(json.dumps(result["cookies_refresh_snapshot"]))
        return result
    def process_result_value(self, value, dialect):
        if value is None:
            return None
        result = dict(value)
        if result.get("cookies_refresh_snapshot") is not None:
            result["cookies_refresh_snapshot"] = json.loads(decrypt_credential(result["cookies_refresh_snapshot"]))
        return result


def derive_service_secret(purpose: str) -> str:
    """认证密钥通过独立用途派生，不存入数据库；数据库泄漏不能伪造JWT。"""
    import base64
    import hashlib
    import hmac
    from common.core.config import get_settings
    credential_cipher()  # 严格验证主密钥配置
    key = base64.urlsafe_b64decode(Path(get_settings().credential_encryption_key_file).read_bytes().strip())
    return hmac.new(key, ("xianyu-security-v1:" + purpose).encode(), hashlib.sha256).hexdigest()
