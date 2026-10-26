from pydantic import BaseModel
from typing import List

from pydantic import BaseModel, Field, SecretStr
from typing import Optional, Literal


class UserRegister(BaseModel):
    username: str
    password: str
    age: int


class UserLogin(BaseModel):
    username: str
    password: str


# 支持的 Provider 列表（可以根据你的项目实际支持情况扩展）
ProviderType = Literal[
    "openai",
    "deepseek",
    "anthropic",
    "ollama",
    "google_genai",
    # 👇 新增国内大厂
    "volcengine",  # 字节跳动（火山引擎/豆包）
    "tencent",  # 腾讯（混元）
    "qwen",  # 阿里（通义千问）
    "zhipuai",  # 智谱 AI
    "moonshot",  # 月之暗面（Kimi）
]


class UserModelConfig(BaseModel):
    """用户提交的私有模型配置"""

    # 1. 核心身份标识
    provider: ProviderType = Field(
        ..., description="模型提供商，如 openai, deepseek, ollama"
    )
    model: str = Field(..., description="模型名称，如 gpt-4o, deepseek-chat, qwen2.5")

    # 2. 鉴权与连接
    api_key_list: List[SecretStr] = Field(
        ..., description="用户的多个 API Key（敏感信息，列表内每个元素都会被自动遮蔽）"
    )
    base_url: Optional[str] = Field(
        None,
        description="自定义 API 端点。例如中转站、本地 Ollama 地址 (http://localhost:11434/v1)",
    )

    # 3. 常用生成参数
    temperature: float = Field(
        0.7, ge=0.0, le=2.0, description="温度，控制随机性，0-2 之间"
    )
    max_tokens: Optional[int] = Field(None, gt=0, description="最大输出 Token 数")

    # 4. 高级网络/容错参数（可选）
    timeout: Optional[float] = Field(60.0, description="请求超时时间（秒）")
    max_retries: int = Field(2, description="请求失败重试次数")


class ChatRequest(BaseModel):
    message: str
    thread_id: int


class AgentStatusResponse(BaseModel):
    thread_id: str
    message_count: int          # 历史对话总条数
    human_message_count: int    # 用户发了多少条
    ai_message_count: int       # AI 回复了多少条
    tool_call_count: int        # 历史调用了多少次工具
    estimated_tokens: int       # 当前上下文的 Token 估算占用
    context_window_limit: int   # 模型的上下文上限（用于计算百分比）
    usage_percentage: float     # 占用百分比 (0-100)
    system_message: str         # 模型目前去除基本系统提示词部分的注入系统提示词