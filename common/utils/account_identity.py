"""阻止密码登录替换已有账号的闲鱼身份。"""
def require_same_account_identity(existing, unb: str) -> None:
    if not unb or not unb.isdigit():
        raise ValueError("登录结果缺少有效的闲鱼身份")
    if existing is not None:
        expected = str(existing.unb or "").strip()
        if not expected:
            from common.utils.xianyu_utils import trans_cookies
            expected = str(trans_cookies(existing.cookie or "").get("unb") or "").strip()
        if not expected or expected != unb:
            raise ValueError("登录身份与原账号不一致，禁止覆盖，请另建账号")
