from langchain.messages import SystemMessage
import os
from typing import Callable
from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
# 工作区路径
WORKSPACE_DIR = "/app/workspace"
MEMORY_FILE = os.path.join(WORKSPACE_DIR, ".agent", "memory.md")


def ensure_memory_file_exists(workspace_path: str):
    """
    检查并初始化项目记忆文件。
    如果文件不存在或为空，则自动创建带模板的 memory.md。
    """
    memory_dir = os.path.join(workspace_path, ".agent")
    memory_file = os.path.join(memory_dir, "memory.md")

    # 1. 确保 .agent 文件夹存在
    os.makedirs(memory_dir, exist_ok=True)  #创建记忆目录。若存在则不创建，跳过

    # 2. 检查文件是否存在且不为空
    need_init = False
    if not os.path.exists(memory_file):
        need_init = True
    else:
        # 如果文件存在，但全是空白字符，也视为需要初始化
        with open(memory_file, "r", encoding="utf-8") as f:
            if not f.read().strip():
                need_init = True

    # 3. 如果不需要初始化，直接返回
    if not need_init:
        return

    # 4. 写入写死的标准模板
    template = f"""# 🧠 项目长期记忆库 (当前项目)
    > ⚠️ 本文件由系统自动维护。Agent 在执行任务时，请通过工具将新的项目规范、踩坑记录**追加**到本文件末尾。禁止重写覆盖此文件。
    ## 1. 项目概览
    - **架构说明**：(待补充)
    - **核心技术栈**：(待补充)
    ## 2. 编码与规范约束
    - (待补充)
    ## 3. 历史踩坑与经验
    """
    with open(memory_file, "w", encoding="utf-8") as f:
        f.write(template)
    print(f"✅ 已自动初始化项目记忆文件: {memory_file}")

class DynamicMemoryMiddleware(AgentMiddleware):
    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        """每次调用大模型前，拦截请求并动态注入项目记忆"""
        # 1. 先调用记忆文件初始化函数初始化记忆文件
        ensure_memory_file_exists(WORKSPACE_DIR)

        # 2. 读取本地的记忆文件内容 memory.md
        try:
            with open(MEMORY_FILE, "r", encoding="utf-8") as f:
                memory_text = f.read()
        except Exception as e:
            print(f"读取记忆文件失败: {e}")
        # 3. 记忆文件内容追加到系统提示词
        memory_instruction = """
        【项目长期记忆系统】
        你拥有一个专属的长期记忆文件：`.agent/memory.md`。
        - 如果该文件有内容，我已在下方附上，请务必遵守其中的规范和踩坑经验。
        - 如果该文件为空或不存在（下方显示“暂无历史记忆”），说明这是一个新项目。请你在初步探索项目（如使用 list_directory, read_file 阅读核心文件）后，主动使用 `create_file` 工具创建 `.agent/memory.md`，并将你了解到的项目架构、技术栈、核心配置记录下来。
        - 在你执行任务的过程中，如果发现了新的重要规范或解决了复杂的 Bug，请使用 `edit_file` 将经验追加写入该文件。
        - 当你更新 .agent/memory.md 时，必须使用追加模式（Append），绝对禁止修改文件头部的标题和已有的历史条目。
        【当前项目记忆】
        - 测试提示词
        """
        injected_text = f"{memory_instruction}\n{memory_text}"

        original_blocks = request.system_message.content_blocks
        new_blocks = list(original_blocks) + [
            {
                "type": "text", 
                "text": f"\n\n{injected_text}"
            }
        ]
        
        new_system_message = SystemMessage(content=new_blocks)
        
        # 4. 替换请求提示词并继续
        return await handler(request.override(system_message=new_system_message))

from typing import Any

from langchain_core.messages import AIMessage, ToolMessage

""" class CleanDanglingToolCallsMiddleware(AgentMiddleware):
    
    防御性中间件：防止因为历史消息中断（如死循环、超时）导致 
    AIMessage 有 tool_calls 但缺失对应的 ToolMessage，从而引发 OpenAI 400 报错。
    Agent 是同步调用的，就走同步方法；是异步调用的，就走异步方法。
   

    def before_model(self, state: dict, runtime: Any = None) -> dict | None:
        同步版本（在调用大模型前执行）
        messages = state.get("messages", [])
        if not messages:
            return None

        # 1. 找出所有已经成功响应的 tool_call_id
        responded_tool_call_ids = {
            msg.tool_call_id 
            for msg in messages 
            if isinstance(msg, ToolMessage)
        }

        # 2. 过滤消息列表，修复悬空的 AI 消息
        clean_messages = []
        for msg in messages:
            if isinstance(msg, AIMessage) and msg.tool_calls:
                # 找出这个 AI 消息里，没有被响应的 tool_calls
                dangling_calls = [
                    tc for tc in msg.tool_calls 
                    if tc["id"] not in responded_tool_call_ids
                ]
                
                if dangling_calls:
                    # 如果存在悬空的调用，我们就构造一个替代的 ToolMessage 来“顶包”
                    # 因为直接删掉 AI 消息或清空 tool_calls 会改变上下文逻辑
                    clean_messages.append(msg)
                    for tc in dangling_calls:
                        clean_messages.append(
                            ToolMessage(
                                tool_call_id=tc["id"],
                                content="❌ 工具执行被中断或超时（系统自动修复了断裂的上下文）。",
                                name=tc["name"]
                            )
                        )
                    continue # 已经处理过这条 AI 消息，跳过默认追加

            clean_messages.append(msg)

        # 返回更新后的 state
        return {"messages": clean_messages}
    async def abefore_model(self, state: dict, runtime: Any = None) -> dict | None:
        异步版本（FastAPI 和 astream_events 走这个）
        # 逻辑与同步版本完全一致，直接调用同步方法即可（因为是纯内存操作，没有 await）
        return self.before_model(state, runtime) """

class CleanDanglingToolCallsMiddleware(AgentMiddleware):
    """
    暴力修复中间件：确保历史中所有 AIMessage 的 tool_calls 都有对应的 ToolMessage。
    如果缺失，直接伪造一个报错 ToolMessage 补齐，彻底杜绝 400 报错。
    """
    def before_model(self, state: dict, runtime: Any = None) -> dict | None:
        messages = state.get("messages", [])
        if not messages:
            return None

        fixed_messages = []
        # 记录当前已经被满足的 tool_call_id
        satisfied_tool_ids = set()
        
        # 第一遍遍历：收集所有存在的 ToolMessage 的 ID
        for msg in messages:
            if isinstance(msg, ToolMessage):
                satisfied_tool_ids.add(msg.tool_call_id)

        # 第二遍遍历：重写消息列表
        for msg in messages:
            fixed_messages.append(msg)
            
            # 如果遇到了 AI 发的 tool_calls
            if isinstance(msg, AIMessage) and getattr(msg, "tool_calls", None):
                for tc in msg.tool_calls:
                    tc_id = tc.get("id") or tc.get("tool_call_id")
                    
                    # 如果这个 ID 没有被任何 ToolMessage 满足
                    if tc_id and tc_id not in satisfied_tool_ids:
                        # 立刻伪造一个 ToolMessage 塞进去！
                        fake_tool_msg = ToolMessage(
                            tool_call_id=tc_id,
                            name=tc.get("name", "unknown_tool"),
                            content="❌ 错误：该工具执行被意外中断或超时（系统已自动补齐上下文）。请勿重复尝试，请重新规划步骤或告诉用户发生错误。"
                        )
                        fixed_messages.append(fake_tool_msg)
                        # 标记为已满足，防止重复补
                        satisfied_tool_ids.add(tc_id)

        return {"messages": fixed_messages}

    async def abefore_model(self, state: dict, runtime: Any = None) -> dict | None:
        return self.before_model(state, runtime)