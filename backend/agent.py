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
from Middleware import DynamicMemoryMiddleware,CleanDanglingToolCallsMiddleware
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
from deepagents.middleware.filesystem import FilesystemMiddleware, FilesystemBackend
from deepagents.middleware.subagents import SubAgentMiddleware
from langchain_core.callbacks import BaseCallbackHandler
# 1. 实例化底层的文件系统后端，把根路径指向你的工作区
backend = FilesystemBackend(
    root_dir="/app/workspace",  # 👈 严格锁死在这个目录
    virtual_mode=True      # 👈 如果开启，模型看到的就是相对路径，更安全
)

# 2. 实例化中间件（它会自动把 ls, read_file 等工具注入给 Agent）
fs_middleware = FilesystemMiddleware(backend=backend)

class DebugCallback(BaseCallbackHandler):
    def on_chat_model_start(self, serialized, messages, **kwargs):
        # 只在大模型请求发起前打印
        print("\n" + "="*50)
        print("🚀 准备发送给大模型的消息列表：")
        for msg in messages[0]: # messages 通常是二维列表
            msg_type = msg.type
            content = msg.content[:50] if msg.content else ""
            tc_ids = [tc["id"] for tc in msg.tool_calls] if hasattr(msg, "tool_calls") and msg.tool_calls else []
            print(f"[{msg_type.upper()}] content='{content}...', tool_calls={tc_ids}, tool_call_id={getattr(msg, 'tool_call_id', None)}")
        print("="*50 + "\n")
# 默认模型
deepmodel = ChatOpenAI(
    model="deepseek-flash",
    api_key=config.DEEPSEEK_API_KEY,
    base_url=config.DEEPSEEK_URL,  # 👈 必须确保是这个地址，不能多写/v1
    extra_body={"thinking": {"type": "disabled"}},  # 👈 关键：关闭思考模式
    callbacks=[DebugCallback()]
    # 不需要代理
)

# 本地 Ollama 模型（docker 内网访问 ollama 容器的 OpenAI 兼容端点）
ollama_model = ChatOpenAI(
    model="qwen2.5:0.5b",
    api_key="ollama",  # 👈 Ollama 不校验 Key，但 ChatOpenAI 要求非空，占位即可
    base_url=config.OLLAMA_URL,  # http://ollama:11434/v1
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
            bocha_websearch_tool,
        ],
        middleware=[
            CleanDanglingToolCallsMiddleware(),  #上下文断裂处理中间件
            SubAgentMiddleware(
                backend=backend,
                subagents=[
                       {
                           "name": "general_subagent",
                           "description": "专门用于处理耗费大量时间或需要多步操作的后台任务（如发送邮件、大规模搜索）。主 Agent 遇到此类耗时任务时，应调用此工具派发任务。",
                            "system_prompt": "你是一个专门负责后台复杂任务的执行者。请独立、完整地完成主 Agent 派发的任务。任务结束后，请输出一段精炼的总结报告作为返回结果。",
                           "model": deepmodel,
                            "tools": [send_mail,bocha_websearch_tool,],
                        }
                    ],
            ),
            DynamicMemoryMiddleware(),
            fs_middleware,
            HumanInTheLoopMiddleware(
                interrupt_on={
                    # Require approval for sensitive operations
                    "delete_item": True,
                    "edit_file": True,
                    # Auto-approve safe operations
                    "execute_terminal":True,
                }
            ),
            ToolErrorMiddleware(
                on_error  # 工具异常处理函数
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
            bocha_websearch_tool,
        ],
        middleware=[
            SubAgentMiddleware(
                backend=backend,
                subagents=[
                        {
                            "name": "general_subagent",
                            "description": "专门用于处理耗费大量时间或需要多步操作的后台任务（如发送邮件、大规模搜索）。主 Agent 遇到此类耗时任务时，应调用此工具派发任务。",
                            "system_prompt": "你是一个专门负责后台复杂任务的执行者。请独立、完整地完成主 Agent 派发的任务。任务结束后，请输出一段精炼的总结报告作为返回结果。",
                            "model": llm,
                            "tools": [send_mail,bocha_websearch_tool,],
                        }
                    ],
            ),
            fs_middleware,
            CleanDanglingToolCallsMiddleware(),
            DynamicMemoryMiddleware(),
            SummarizationMiddleware(
                model=ollama_model,
                trigger=("tokens", 4000),
                keep=("messages", 20),
            ),
            HumanInTheLoopMiddleware(
                interrupt_on={
                    # Require approval for sensitive operations
                    "delete_item": True,
                    "edit_file": True,
                    # Auto-approve safe operations
                    "execute_terminal": True,
                }
            ),
            ModelCallLimitMiddleware(
                thread_limit=50,  # 会话级限制模型调用次数
                run_limit=15,  # 单次agent调用运行限制模型调用次数
                exit_behavior="end",  # 达到限制条件优雅结束，还可以设置为 "raise_error"（直接抛出异常中断）
            ),
            ToolCallLimitMiddleware(thread_limit=50, run_limit=25),  # 全局工具调用次数限制
            ToolCallLimitMiddleware(
                tool_name="bocha_websearch_tool",
                thread_limit=15,
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
