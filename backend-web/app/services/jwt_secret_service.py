"""从独立部署密钥派生 JWT 密钥。禁止数据库托管或弱默认值回退。"""
from common.utils.credential_crypto import derive_service_secret

async def ensure_jwt_secret_key(settings) -> None:
    settings.jwt_secret_key = derive_service_secret("jwt:backend-web")
