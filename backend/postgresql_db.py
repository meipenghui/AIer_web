from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from config import config
from models import User, Agent_Config, Base

# 创建数据库引擎
engine = create_async_engine(
    config.DATABASE_URL,
    echo=False,  # 调试时可以设为 True 查看 SQL 语句
    pool_size=5,  # 连接池中保持的连接数
    max_overflow=15,  # 高负载时额外创建的连接数
    pool_pre_ping=True,  # 每次使用前检查连接是否有效
    pool_recycle=3600,  # 连接回收时间（秒），避免连接过期
)

# 创建异步会话工厂
# expire_on_commit=False 非常重要，避免异步中懒加载报错
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


# 获取数据库会话生成器
async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()  # 异常自动回滚，再抛出错误
            raise


# 初始化数据库建表，一般在应用启动时进行,需要导入定义好的sqlmodel表，以供数据库初始化时创建数据表
async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(
            Base.metadata.create_all
        )  # 只创建"表名不存在"的表；表名已存在的，整张表都不动（字段、索引、约束都不碰）。
        print("数据库初始化成功！")
