from cryptography.fernet import Fernet
import os
from jose import jwt, ExpiredSignatureError, JWTError
import secrets
import hashlib
from fastapi import Depends
from redis.asyncio import Redis
from datetime import timedelta, timezone
import uuid
from cryptography.fernet import Fernet
from config import config
from datetime import datetime
from fastapi import HTTPException
from passlib.context import CryptContext

# 用户 API KEY 加密参数
# 1. 初始化密码器
cipher = Fernet(config.MASTER_KEY.encode())
# 2. 加密（用户提交时）
def encrypt_api_key(api_key: str) -> str:
    return cipher.encrypt(api_key.encode()).decode()
# 3. 解密（后端调用大模型时）
def decrypt_api_key(encrypted_key: str) -> str:
    return cipher.decrypt(encrypted_key.encode()).decode()


# 用户密码加密
SECRET_KEY = config.SECRET_KEY
ALGORITHM = config.ALGORITHM
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
# oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/login")


# JWT加密
JWT_SECRET = config.JWT_SECRET
JWT_ALGORITHM = config.JWT_ALGORITHM
ACCESS_TOKEN_EXPIRE_MINUTES =config.ACCESS_TOKEN_EXPIRE_MINUTES
REFRESH_TOKEN_EXPIRE_DAYS =config.REFRESH_TOKEN_EXPIRE_DAYS


# 编码access token
def encode_access_token(id: int, username: str, now=None):
    if now is None:
        now = datetime.now(timezone.utc)  # 👈 每次调用时重新获取
    payload = {
        "id": id,
        "iat": now,
        "exp": now + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(
        claims=payload,
        key=JWT_SECRET,
        algorithm=JWT_ALGORITHM,  # 注意：python-jose 用的是 claims，PyJWT 用的是 payload
    )  # 返回str类型


# 解码access token
def decode_access_token(access_token: str):
    return jwt.decode(access_token, JWT_SECRET, algorithms=[JWT_ALGORITHM])


# 生成refresh token
def generate_refresh_token() -> str:
    return secrets.token_urlsafe(
        32
    )  # .token_urlsafe(32) 生成 32 字节随机数据，编码成URL安全的字符串，可以通过URL传输，random模块伪随机，可预测


# 哈希refresh token
def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(
        token.encode()
    ).hexdigest()  # 哈希refresh token，技术上选择hashlib.sha256（）算法更合适，不用哈希密码的bcrypt


# access_token加redis黑名单
async def block_ac_token(  # 涉及I/O操作用协程
    access_token: str, redis: Redis
) -> None:  # 添加jti到阻塞列表，被用于注销token功能
    payload = decode_access_token(access_token)
    jti = payload["jti"]
    exp = payload["exp"]  # 获取过期时间
    ttl = exp - int(
        datetime.now(timezone.utc).timestamp()
    )  # access_token剩余有限期，.timestamp()：将datetime对象转换成Unix时间戳
    if ttl > 0:  # 如果access_token尚未过期
        await redis.setex(
            f"blacklist:{jti}", ttl, "1"
        )  # 设置 与access_token剩余有限期 等长的阻塞时长
    # 异步写入键值对，jti被记录在键上，值为空（none),ttl指定过期时间，单位秒，过期redis自动删除


# 验证access token
def verify_access_token(access_token: str) -> dict:
    try:
        payload = decode_access_token(access_token)
    except ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="接入令牌过期")
    except JWTError:  # python-jose 的基类异常
        raise HTTPException(status_code=401, detail="接入令牌无效")
    return payload


# 验证access_token是否在redis黑名单
async def ac_token_was_blocked(
    access_token: str, redis: Redis
) -> bool:  # 涉及I/O操作用协程
    payload = decode_access_token(access_token)
    jti = payload["jti"]
    jti = await redis.get(
        jti
    )  # 查询键名为jti的值，若存在则返回值为""空字符串,若不存在则返回值为None
    return jti is not None  # Ture代表token在阻塞列表内，反之不在
