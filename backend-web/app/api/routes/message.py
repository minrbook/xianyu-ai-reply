"""
消息发送路由
外部系统发送消息接口
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import get_current_active_user, get_db_session
from common.models.user import User
from common.models.xy_account import XYAccount
from common.db.redis_client import get_redis_client
from pydantic import BaseModel, Field
from loguru import logger

router = APIRouter(tags=["消息"])


# ==================== 请求/响应模型 ====================

class SendMessageRequest(BaseModel):
    """发送消息请求"""
    cookie_id: str = Field(min_length=1, max_length=80, pattern=r"^[\w-]+$")
    chat_id: str = Field(min_length=1, max_length=200)
    to_user_id: str = Field(min_length=1, max_length=80)
    message: str = Field(min_length=1, max_length=10000)


class SendMessageResponse(BaseModel):
    """发送消息响应"""
    success: bool
    message: str


# ==================== 工具函数 ====================

def clean_param(param_str: str) -> str:
    """清理参数中的换行符"""
    if isinstance(param_str, str):
        return param_str.replace("\\n", "").replace("\n", "")
    return param_str


# ==================== 路由 ====================

@router.post("/send", response_model=SendMessageResponse)
async def send_message(
    request: SendMessageRequest,
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
):
    """
    发送消息API接口（Bearer 登录令牌，仅限本人账号）
    
    用于外部系统（如QQ机器人）向闲鱼发送消息
    """
    account = (await session.execute(select(XYAccount).where(
        XYAccount.account_id == request.cookie_id,
        XYAccount.owner_id == current_user.id,
    ))).scalar_one_or_none()
    if account is None or account.status != "active":
        raise HTTPException(status_code=403, detail="账号不存在、已禁用或无权操作")
    # 固定窗口由 Redis 原子执行；Redis 故障时拒绝调用，不绕过限流。
    try:
        redis = await get_redis_client()
        count = await redis.eval(
            "local n=redis.call('INCR',KEYS[1]); if n==1 then redis.call('EXPIRE',KEYS[1],60) end; return n",
            1, f"rate:external-message:{current_user.id}",
        )
    except Exception:
        raise HTTPException(status_code=503, detail="限流服务不可用") from None
    if count > 30:
        raise HTTPException(status_code=429, detail="每分钟最多发送30条消息")
    try:
        # 清理参数
        cleaned_cookie_id = account.account_id
        cleaned_chat_id = clean_param(request.chat_id)
        cleaned_to_user_id = clean_param(request.to_user_id)
        cleaned_message = clean_param(request.message)
        
        # 验证必需参数
        required_params = {
            "cookie_id": cleaned_cookie_id,
            "chat_id": cleaned_chat_id,
            "to_user_id": cleaned_to_user_id,
            "message": cleaned_message,
        }
        
        for param_name, param_value in required_params.items():
            if not param_value:
                logger.warning(f"必需参数 {param_name} 为空")
                return SendMessageResponse(
                    success=False,
                    message=f"参数 {param_name} 不能为空"
                )
        
        # 通过WebSocket服务发送消息
        from app.services.websocket_client import websocket_client
        
        result = await websocket_client.send_message(
            account_id=cleaned_cookie_id,
            chat_id=cleaned_chat_id,
            content=cleaned_message,
            message_type="text",
            to_user_id=cleaned_to_user_id,
        )

        send_data = result.get('data') or {}
        if result.get('success') and send_data.get('send_status') == 'failed':
            reason = send_data.get('send_fail_reason') or '闲鱼服务端拒绝'
            logger.error(f"消息被闲鱼服务端拦截: {cleaned_cookie_id} -> {cleaned_to_user_id}: {reason}")
            return SendMessageResponse(success=False, message=f"消息被闲鱼拦截: {reason}")

        if result.get('success'):
            logger.info(f"消息发送成功: {cleaned_cookie_id} -> {cleaned_to_user_id}")
            return SendMessageResponse(
                success=True,
                message="消息发送成功"
            )
        else:
            error_msg = result.get('message', '发送失败')
            logger.error(f"发送消息失败: {error_msg}")
            return SendMessageResponse(
                success=False,
                message=error_msg
            )
        
    except Exception as e:
        logger.error(f"发送消息异常: {e}")
        return SendMessageResponse(
            success=False,
            message=f"发送消息失败: {str(e)}"
        )
