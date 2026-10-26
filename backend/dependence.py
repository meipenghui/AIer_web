from redis_db import get_redis
from jose import jwt
from fastapi.security import (
    HTTPBearer,
    HTTPAuthorizationCredentials,
)  # HTTPBearer 就是一个帮你从 Authorization: Bearer xxx 请求头里自动取出 Token 字符串的便捷工具
from fastapi import Request, HTTPException, Depends
from utils import verify_access_token, ac_token_was_blocked
from postgresql_db import get_db
from sqlalchemy.ext.asyncio import AsyncSession
from models import User


# 重写HTTPBearer类的__call__方法
class HTTP_access_Bearer(HTTPBearer):
    def __init__(self, auto_error: bool = True):
        super().__init__(auto_error=auto_error)

    async def __call__(self, request: Request):  # HTTPBearer.__call__ 本身是 async 的
        # 取出Authorization头数据
        creds = await super().__call__(request)
        access_token = creds.credentials
        # 验证access token是否有效，被阻塞
        async for redis in get_redis():
            payload = verify_access_token(access_token)
            if await ac_token_was_blocked(access_token, redis):
                raise HTTPException(
                    detail="接入令牌被阻塞",
                    status_code=401,
                )
            return payload


# 负责根据解码的paylaod返回对应用户对象
async def get_current_user(
    payload: HTTPAuthorizationCredentials = Depends(
        HTTP_access_Bearer()
    ),  # 具有两个属性
    db: AsyncSession = Depends(get_db),
) -> User:
    # 取出属性
    id = payload["id"]
    user_orm = await db.get(User, id)
    return user_orm  # 返回access token对应的用户对象
