from functools import lru_cache  # functools是python标准库
from langchain.agents import create_agent
from langchain.agents.middleware import (
    HumanInTheLoopMiddleware,
    ModelCallLimitMiddleware,
    ToolCallLimitMiddleware,
    ToolErrorMiddleware,
    ContextEditingMiddleware,
    ClearToolUsesEdit,
    TodoListMiddleware,
    SummarizationMiddleware
)
from Middleware import DynamicMemoryMiddleware
from langchain_openai import ChatOpenAI
from config import config
from coding_tools import (
    list_directory,
    read_file,
    edit_file,
    execute_terminal,
    create_file,
    move_file,
    delete_item,
    search_code,
    send_mail,
    bocha_websearch_tool,
)
from models import Agent_Config
from fastapi import Request
from system_prompt import base_sys_prompt
from utils import decrypt_api_key
from langchain.agents.middleware.types import ToolCallRequest
# 默认模型
deepmodel = ChatOpenAI(
    model="deepseek-flash",
    api_key=config.DEEPSEEK_API_KEY,
    base_url=config.DEEPSEEK_URL,  # 👈 必须确保是这个地址，不能多写/v1
    extra_body={"thinking": {"type": "disabled"}},  # 👈 关键：关闭思考模式
    # 不需要代理
)


# 捕获工具错误，返回模型可见并能从中恢复的错误 ToolMessage，而不是终止智能体的运行
def on_error(exc: Exception, request: ToolCallRequest) -> str | None:
    if isinstance(exc, ValueError):
        return f"`{request.tool_call['name']}` failed with {type(exc).__name__}."


# 默认Agent
async def build_default_agent(request: Request, llm=deepmodel):
    return create_agent(
        model=deepmodel,
        system_prompt=base_sys_prompt,
        checkpointer=request.app.state.checkpointer,
        store=request.app.state.store,
        tools=[
            send_mail,
            list_directory,
            read_file,
            execute_terminal,
            create_file,
            edit_file,
            move_file,
            delete_item,
            search_code,
            bocha_websearch_tool,
        ],
        middleware=[
            DynamicMemoryMiddleware(),
            SummarizationMiddleware(
                model=deepmodel,
                trigger=("tokens", 4000),
                keep=("messages", 20),
            ),
            HumanInTheLoopMiddleware(
                interrupt_on={
                    # Require approval for sensitive operations
                    "delete_item": True,
                    "edit_file": True,
                    # Auto-approve safe operations
                    "execute_terminal": False,
                }
            ),
            ModelCallLimitMiddleware(
                thread_limit=10,  # 会话级限制模型调用次数
                run_limit=5,  # 单次agent调用运行限制模型调用次数
                exit_behavior="end",  # 达到限制条件优雅结束，还可以设置为 "raise_error"（直接抛出异常中断）
            ),
            ToolCallLimitMiddleware(thread_limit=20, run_limit=10),  # 全局工具调用次数限制
            ToolCallLimitMiddleware(
                tool_name="bocha_websearch_tool",
                thread_limit=10,
                run_limit=2,
            ),
            ToolErrorMiddleware(
                on_error  # 工具异常处理函数
            ),  # 捕获工具执行期间抛出的异常，并将其转换为模型可见并能从中恢复的错误 ToolMessage，而不是终止智能体的运行。
            ContextEditingMiddleware(
                edits=[
                ClearToolUsesEdit(
                    trigger=100000,
                    keep=3,
                ),
            ],
            ),
            TodoListMiddleware(),
        ],
    )

import hashlib
from typing import Dict, Any


# 私有配置模型
def build_llm_from_config(config: Agent_Config):
    """根据数据库里的配置，动态构建一个大模型实例"""

    # 1. 取出并解密所有 API Key（取第一个可用的）
    api_key_list = [decrypt_api_key(k) for k in config.api_key_list if k]
    if not api_key_list:
        raise ValueError("没有可用的 API Key")

    active_api_key = api_key_list[0]

    # 2. 构建模型实例
    llm = ChatOpenAI(
        model=config.model,
        api_key=active_api_key,
        base_url=config.base_url,
        temperature=config.temperature,
        max_tokens=config.max_tokens,
        timeout=config.timeout,
        max_retries=config.max_retries,
    )

    return llm


# 全局缓存字典：{ user_id: {"hash": xxx, "agent": Agent实例} }
_AGENT_CACHE: Dict[int, Dict[str, Any]] = {}


def generate_config_hash(config: Agent_Config) -> str:
    """根据配置的核心字段生成一个哈希值，用于判断配置是否改变"""
    # 注意：不要把敏感信息（API Key）放进去算哈希，用修改时间或ID即可
    raw_str = f"{config.provider}-{config.model}-{config.base_url}-{config.temperature}-{config.max_tokens}"
    return hashlib.md5(raw_str.encode()).hexdigest()


def get_or_create_agent(request:Request,user_id: int, config: Agent_Config):
    """
    获取缓存的 Agent，如果没有缓存或配置变了，则重新创建
    """
    current_hash = generate_config_hash(config)

    # 1. 检查是否有缓存
    if user_id in _AGENT_CACHE:
        cached_data = _AGENT_CACHE[user_id]
        # 如果哈希值一致，说明配置没变，直接返回缓存的 Agent，速度极快！
        if cached_data["hash"] == current_hash:
            return cached_data["agent"]
        else:
            print(f"🔄 用户 {user_id} 的配置已变更，重新创建 Agent...")
    else:
        print(f"✨ 首次为用户 {user_id} 创建 Agent...")

    # 2. 缓存失效或不存在，重新创建
    llm = build_llm_from_config(config)

    new_agent = create_agent(
        model=llm,
        system_prompt=base_sys_prompt,
        checkpointer=request.app.state.checkpointer,
        store=request.app.state.store,
        tools=[
            send_mail,
            list_directory,
            read_file,
            execute_terminal,
            create_file,
            edit_file,
            move_file,
            delete_item,
            search_code,
            bocha_websearch_tool,
        ],
        middleware=[
            DynamicMemoryMiddleware(),
            SummarizationMiddleware(
                model=deepmodel,
                trigger=("tokens", 4000),
                keep=("messages", 20),
            ),
            HumanInTheLoopMiddleware(
                interrupt_on={
                    # Require approval for sensitive operations
                    "delete_item": True,
                    "edit_file": True,
                    # Auto-approve safe operations
                    "execute_terminal": False,
                }
            ),
            ModelCallLimitMiddleware(
                thread_limit=10,  # 会话级限制模型调用次数
                run_limit=5,  # 单次agent调用运行限制模型调用次数
                exit_behavior="end",  # 达到限制条件优雅结束，还可以设置为 "raise_error"（直接抛出异常中断）
            ),
            ToolCallLimitMiddleware(thread_limit=20, run_limit=10),  # 全局工具调用次数限制
            ToolCallLimitMiddleware(
                tool_name="bocha_websearch_tool",
                thread_limit=10,
                run_limit=2,
            ),
            ToolErrorMiddleware(
                on_error  # 工具异常处理函数
            ),  # 捕获工具执行期间抛出的异常，并将其转换为模型可见并能从中恢复的错误 ToolMessage，而不是终止智能体的运行。
            ContextEditingMiddleware(
                edits=[
                ClearToolUsesEdit(
                    trigger=100000,
                    keep=3,
                ),
            ],
            ),
            TodoListMiddleware(),
        ],
    )

    # 3. 更新缓存
    _AGENT_CACHE[user_id] = {"hash": current_hash, "agent": new_agent}

    return new_agent


def clear_agent_cache(user_id: int):
    """供保存配置的接口调用，主动清理缓存"""
    if user_id in _AGENT_CACHE:
        del _AGENT_CACHE[user_id]
        print(f"🗑️ 已清空用户 {user_id} 的 Agent 缓存")
