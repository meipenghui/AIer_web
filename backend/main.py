from fastapi import FastAPI, HTTPException, Depends,Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import datetime, timedelta, timezone
from langchain.messages import HumanMessage, SystemMessage, AIMessage
from fastapi.responses import StreamingResponse
from agent import build_default_agent, get_or_create_agent
from langchain_core.runnables import RunnableConfig
from contextlib import asynccontextmanager
from postgresql_db import init_db, get_db
from sqlalchemy.ext.asyncio import AsyncSession
from models import User, Agent_Config
from dependence import get_current_user
from utils import (
    encode_access_token,
    generate_refresh_token,
    hash_refresh_token,
    REFRESH_TOKEN_EXPIRE_DAYS,
    encrypt_api_key,
    decrypt_api_key,
    pwd_context
)
from redis_db import get_redis, init_redis, redis_pool
from redis.asyncio import Redis
from schemas import UserRegister, UserLogin, ChatRequest, UserModelConfig, AgentStatusResponse
from SSE import sse_generator
from sqlalchemy import select
from langchain_core.runnables import Runnable
import os
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.store.postgres.aio import AsyncPostgresStore
from system_prompt import base_sys_prompt
from config import config
# from fastapi.security import OAuth2PasswordBearer

# 全局变量，初始为 None
checkpointer = None
store = None
DB_URI = config.MOMERY_DATABASE_URL
@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    await init_redis()
    global checkpointer, store
    print("⏳ 正在初始化 Checkpointer 与 Store...")
    async with AsyncPostgresStore.from_conn_string(DB_URI) as _store:
        await _store.setup()
        store = _store
        app.state.store=store
        # 2. 初始化 Checkpointer
        async with AsyncPostgresSaver.from_conn_string(DB_URI) as _checkpointer:
            await _checkpointer.setup()
            checkpointer = _checkpointer
            app.state.checkpointer=checkpointer
            
            # 👇 重点：yield 必须放在两个 async with 内部，保证应用运行期间连接一直打开
            print("✅ 存储与检查点初始化完成，应用启动！")
            yield 
    print("🛑 存储与检查点连接已关闭")
    await redis_pool.disconnect()
    print("🛑 Redis 连接池已关闭")

app = FastAPI(lifespan=lifespan)

# 跨域配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==========================================
# 注册接口（用持久化数据库 + 密码哈希）
# ==========================================
@app.post("/api/register")
async def register(user: UserRegister, db_session: AsyncSession = Depends(get_db)):
    # 验证用户名是否被注册
    stmt = select(User).where(User.username == user.username)
    result = await db_session.execute(stmt)
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="该用户名已被注册，请更换")
    # 加密密码，新建用户记录
    hash_pwd = pwd_context.hash(user.password)
    user_dict = user.model_dump()
    del user_dict["password"]
    user_dict["hash_password"] = hash_pwd
    user_orm = User(**user_dict)
    db_session.add(user_orm)  # 把对象加入会话（此时还没真正写入数据库）
    await db_session.commit()  # 提交事务，把 INSERT 真正写入数据库
    return {"msg": "注册成功，请登录"}


# ==========================================
# 登录接口（数据库验证）
# ==========================================
@app.post("/api/login")
async def login(
    user: UserLogin,
    db_session: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
):
    # 1. 查数据用户表，验证用户名与密码
    stmt = select(User).where(User.username == user.username)  # 列对象放在前面
    result = await db_session.execute(stmt)
    user_orm = result.scalar_one_or_none()
    if user_orm == None or not pwd_context.verify(
        user.password, user_orm.hash_password
    ):
        raise HTTPException(404, "用户或密码错误")
    # 2. 分发接入token与刷新token
    access_token = encode_access_token(user_orm.id, user_orm.username)
    refresh_token = generate_refresh_token()
    refresh_hash = hash_refresh_token(refresh_token)
    await redis.set(
        refresh_hash, str(user_orm.id), ex=REFRESH_TOKEN_EXPIRE_DAYS * 24 * 3600
    )
    return {
        "msg": "登录成功",
        "access_token": access_token,
        "refresh_hash": refresh_hash,
        "refresh_token_expires_days": REFRESH_TOKEN_EXPIRE_DAYS,
    }


# ==========================================
# Agent 配置接口：api_key列表，模型配置，用户偏好，提示词，skills等（必须通过 Token 鉴权才能访问）
# ==========================================


@app.post("/api/agent_config")
async def set_agent_config(
    config: UserModelConfig,
    user_orm: User = Depends(get_current_user),
    db_session: AsyncSession = Depends(get_db),
):
    stmt = select(Agent_Config).where(Agent_Config.id == user_orm.id)
    result = await db_session.execute(stmt)
    config_orm = result.scalar_one_or_none()
    api_key_list = []
    for api_key in config.api_key_list:
        plain_key = api_key.get_secret_value()
        secret_key = encrypt_api_key(plain_key)
        api_key_list.append(secret_key)
    if not config_orm:
        # 构造配置字典
        new_config = Agent_Config(
            provider=config.provider,
            model=config.model,
            base_url=config.base_url,
            temperature=config.temperature,
            max_tokens=config.max_tokens,
            timeout=config.timeout,
            max_retries=config.max_retries,
            api_key_list=api_key_list,
            id=user_orm.id,  # 👈 关联当前用户（外键）
        )
        db_session.add(new_config)
        msg = "模型配置创建成功"
    else:
        # 构造配置字典
        config_orm.provider = config.provider
        config_orm.model = config.model
        config_orm.base_url = config.base_url
        config_orm.temperature = config.temperature
        config_orm.max_tokens = config.max_tokens
        config_orm.timeout = config.timeout
        config_orm.max_retries = config.max_retries
        config_orm.api_key_list = api_key_list  # 替换旧的 Key 列表
        db_session.add(config_orm)  # 标记为已修改
        msg = "模型配置已更新"
    await db_session.commit()
    return {"msg": msg}


# ==========================================
# AI 对话接口（必须通过 Token 鉴权才能访问）
# ==========================================

@app.post("/api/chat")
async def chat_with_agent(
    req: ChatRequest,
    request:Request,
    user_orm: User = Depends(get_current_user),
    db_session: AsyncSession = Depends(get_db),
):

    # 用户与会话隔离
    username = user_orm.username
    thread_id = req.thread_id 
    config: RunnableConfig = {"configurable": {"thread_id": f"{username}_{thread_id}"}}
    

    # 查询用户模型配置，初始化配置
    result = await db_session.execute(
        select(Agent_Config).where(Agent_Config.id == user_orm.id)
    )
    user_config = result.scalar_one_or_none()
    if not user_config:
        # 如果不存在配置，就用默认配置：AIer_agent
        AIer_agent=await build_default_agent(request)
        return StreamingResponse(
            sse_generator(AIer_agent, req.message, config),
            media_type="text/event-stream",
        )
    else:
        # 如果存在配置，就用配置取出agent：user_agent
        user_agent = get_or_create_agent(user_orm.id, user_config,request)
        return StreamingResponse(
            sse_generator(user_agent, req.message, config),
            media_type="text/event-stream",
        )


# ===================================================
# Agent 状态查询接口（必须通过 Token 鉴权才能访问）
# ===================================================


@app.get("/api/agent/status", response_model=AgentStatusResponse)
async def get_agent_status(
    thread_id: str,
    request:Request,
    user_orm: User = Depends(get_current_user)
):
    # 1. 拼接完整的隔离 ID
    full_thread_id = f"{user_orm.username}_{thread_id}"
    
    # 2. 使用 LangGraph 的底层接口获取当前线程的最新状态
    # aget_state 会直接从 PostgreSQL 里读取该 thread_id 最新的 checkpoint
    config:RunnableConfig = {"configurable": {"thread_id": full_thread_id}}
    checkpointer=request.app.state.checkpointer
    state_snapshot = await checkpointer.aget_tuple(config)   #会话id对象检查点状态快照
    if not state_snapshot:
        raise HTTPException(status_code=404, detail="未找到该会话的状态记录")

    # 3. 从快照中提取消息列表 (LangGraph 默认将对话存在 'messages' 字段)
    messages = state_snapshot.checkpoint.get("channel_values", {}).get("messages", [])

    if not messages:
        return AgentStatusResponse(
            thread_id=thread_id, message_count=0, human_message_count=0,
            ai_message_count=0, tool_call_count=0, estimated_tokens=0,
            context_window_limit=128000, usage_percentage=0.0
        )

    # 4. 遍历消息，统计各项指标
    human_count = 0
    ai_count = 0
    tool_count = 0
    total_chars = 0 # 所有消息内容字符数量，用于粗略估算 Token
    sys_msg=""
    for msg in messages:
        # 粗略估算 Token：中文大概 1 个字符 ≈ 0.5-1 个 Token，这里用简单的字符数估算
        if hasattr(msg, "content") and isinstance(msg.content, str):
            total_chars += len(msg.content)

        if isinstance(msg, HumanMessage):
            human_count += 1
        elif isinstance(msg, AIMessage):
            ai_count += 1
            # 统计 AI 决定调用工具的次数
            if getattr(msg, "tool_calls", None):
                tool_count += len(msg.tool_calls)
        elif isinstance(msg,SystemMessage):
            # 提示词注入后，提示词消息变为列表形式，确保它是我们规定的列表格式，并且长度至少为 2
            if isinstance(msg.content, list) and len(msg.content) > 1:
                sys_msg = msg.content[1]["text"].strip()
            # 兜底：如果会话刚开始还没有提示词注入，用户就查询智能体状态
            elif isinstance(msg.content, str):  
                sys_msg = msg.content.replace(base_sys_prompt,"").strip()
            # 3. 最后一道保险：如果抓取到的还是空，给个默认提示语
            if not sys_msg:
                sys_msg = "暂无注入的项目长期记忆（当前处于基础对话模式）。"
    # 5. 估算 Token 与 上下文占用
    # 注意：这里只能粗略估算，因为大模型不仅算 text，还算 system prompt 和 tools schema
    estimated_tokens = int(total_chars * 1.2) + (len(messages) * 4) # 加上消息自身的框架开销
    
    # 默认上下文上限
    context_limit = 1000000  #主流前沿大模型的上下文已经来到 1M(1000K)
    
    # 计算百分比并保留两位小数
    usage_percentage = min(round((estimated_tokens / context_limit) * 100, 2), 100.0)

    return AgentStatusResponse(
        thread_id=thread_id,
        message_count=len(messages),
        human_message_count=human_count,
        ai_message_count=ai_count,
        tool_call_count=tool_count,
        estimated_tokens=estimated_tokens,
        context_window_limit=context_limit,
        usage_percentage=usage_percentage,
        system_message=sys_msg
    )