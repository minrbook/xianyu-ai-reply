"""服务间鉴权令牌由独立部署密钥派生，不接受数据库中的旧令牌。"""
from common.core.config import get_settings as get_common_settings
from common.utils.credential_crypto import derive_service_secret

async def ensure_internal_api_token(settings) -> str:
    token = derive_service_secret("internal-api")
    settings.internal_api_token = token
    get_common_settings().internal_api_token = token
    return token

async def load_internal_api_token(settings) -> str:
    return await ensure_internal_api_token(settings)
