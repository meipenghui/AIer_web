import redis.asyncio as aioredis
from redis.asyncio import Redis
from config import config


redis_pool = aioredis.ConnectionPool.from_url(
    config.REDIS_URL,
    decode_responses=True,  # 自动解码字节为字符串
    max_connections=20,
)

async def get_redis():  # yeild返回，为异步生成器(async_generator)，要用 <async for item in get_redis：>使用
    """
    每次请求时，从连接池里借一个连接。
    请求结束后，自动归还连接（千万不要在这里调用 client.aclose()）
    """
    # 直接实例化，不要用 async with，因为它会自动 close 连接，导致连接池失效
    client = Redis(connection_pool=redis_pool)
    try:
        yield client
    finally:
        # 释放连接回连接池（把借来的东西还回去）
        await client.close()


async def init_redis():
    """应用启动时，测试 Redis 是否可用"""
    client = Redis(connection_pool=redis_pool)
    try:
        await client.ping()
        print("✅ Redis 连接成功！")
    except Exception as e:
        print(f"❌ Redis 连接失败: {e}")
        raise e
    finally:
        await client.close()
