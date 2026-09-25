"""
极验验证码配置

从环境变量读取部署者自己的服务配置
"""
import os


class GeetestConfig:
    """极验验证码配置类"""
    
    # 极验分配的captcha_id（从环境变量读取，无预置凭据）
    CAPTCHA_ID = os.getenv("GEETEST_CAPTCHA_ID", "")
    
    # 极验分配的私钥（从环境变量读取，无预置凭据）
    PRIVATE_KEY = os.getenv("GEETEST_PRIVATE_KEY", "")
    
    # 用户标识（可选）
    USER_ID = os.getenv("GEETEST_USER_ID", "xianyu_system")
    
    # 客户端类型：web, h5, native, unknown
    CLIENT_TYPE = "web"
    
    # API地址
    API_URL = "http://api.geetest.com"
    REGISTER_URL = "/register.php"
    VALIDATE_URL = "/validate.php"
    
    # SDK版本
    VERSION = "python-fastapi:3.1.1"
    
    # 请求超时时间（秒）- 优化为3秒以提升响应速度
    TIMEOUT = 3.0
