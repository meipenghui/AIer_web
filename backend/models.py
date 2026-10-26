# 准备数据表结构
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy import (
    String,
    Integer,
    select,
    DateTime,
    func,
    ForeignKey,
    Numeric,
    Boolean,
    Float,
)
from decimal import Decimal
from datetime import datetime
from sqlalchemy.sql import expression
from sqlalchemy.dialects.postgresql import ARRAY
from typing import Optional


# 定义基类，数据表都继承它：所有模型都继承自同一个 Base
class Base(DeclarativeBase):
    pass


# Mapped[int]声明字段的 Python 类型，mapped_column声明字段的数据库属性（类型、约束、默认值等）
class User(Base):
    __tablename__ = "users"  # 表名（必填）

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True, unique=True
    )
    hash_password: Mapped[str] = mapped_column(String(255))
    age: Mapped[int] = mapped_column(Integer, default=0)
    is_verified: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=expression.false()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),  # 数据库侧默认值
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),  # 更新时自动刷新
    )


class Agent_Config(Base):
    """注意:用户智能体配置表对用户表为一对一关系，用户注销后需要连表删除，反之不用"""

    __tablename__ = "user_model_configs"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
    )

    # 核心身份标识
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    api_key_list: Mapped[list[str]] = mapped_column(ARRAY(String(255)), default=[])
    # 鉴权与连接
    base_url: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # 生成参数
    temperature: Mapped[float] = mapped_column(Float, default=0.7)
    max_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # 网络容错
    timeout: Mapped[float] = mapped_column(Float, default=60.0)
    max_retries: Mapped[int] = mapped_column(Integer, default=2)

    # 记录时间戳
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),  # 数据库侧默认值
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),  # 更新时自动刷新
    )