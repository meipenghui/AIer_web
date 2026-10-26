import json
import traceback
import time
from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.runnables import Runnable

#添加花费单次用时与tokens消耗的流式输出调用
async def sse_generator(user_agent:Runnable, message: str, config: RunnableConfig):
    start_time = time.time()
    total_tokens = 0
    has_thought = False # 👈 新增：标记是否已经发过思考提示
    try:
        print("🚀 [SSE] 生成器已启动，准备调用 Agent...")
        async for event in user_agent.astream_events(
            {"messages": [HumanMessage(content=message.strip())]},
            version="v2",
            config=config,
        ):  
            tool_name = event.get("name", "")
            # 👇 1. 监听模型开始新一轮思考，发送提示，提升用户体验
            if event["event"] == "on_chat_model_start":
                if has_thought ==False:
                # 当模型开始新一轮思考时，可以先给前端发个信号
                    yield f"data: {json.dumps({'status': '🧠 正在思考下一步行动...'}, ensure_ascii=False)}\n\n"
                    has_thought =True
            # 👇 2. 监听模型输出文本与思考（思维链）过程
            elif event["event"] == "on_chat_model_stream":
                chunk = event["data"]["chunk"]
                # 👇 提取模型输出文本
                if chunk.content:
                    # 👇 直接把内容拼到 data: 后面，不要 json.dumps！
                    # 注意：如果大模型生成的内容里自带换行符 \n，会导致 SSE 格式断裂。
                    # 所以最安全的做法是把内容转义或者用 JSON。
                    yield f"data: {json.dumps({'status': ''}, ensure_ascii=False)}\n\n"
                    yield f"data: {json.dumps({'text': chunk.content}, ensure_ascii=False)}\n\n"
                # 👇 提取推理过程 (针对 DeepSeek-R1 等支持思维链的模型)，模型关闭或不支持思考模式也不会报错,思维链没有独立的事件钩子
                if hasattr(chunk, "additional_kwargs"):
                    reasoning = chunk.additional_kwargs.get("reasoning_content")
                    if reasoning:
                        # 用 type="reasoning" 标记，前端收到后显示在折叠面板里
                        yield f"data: {json.dumps({'type': 'reasoning', 'text': reasoning}, ensure_ascii=False)}\n\n"
            # 👇 3. 监听工具开始执行  
            elif event["event"] == "on_tool_start":
                # 👇  监听 TodoList中间件工具（write_todos）的更新事件,对于特定工具的流式打印，没有特定钩子
                if tool_name == "write_todos":
                    tool_input = event["data"].get("input", {})
                    # 获取 Agent 刚刚生成的待办列表参数
                    if isinstance(tool_input, str):
                        try: tool_input = json.loads(tool_input)
                        except: tool_input = {}
                    todos = tool_input.get("todos", [])
                    if todos:
                        yield f"data: {json.dumps({'type': 'todos', 'todos': todos}, ensure_ascii=False)}\n\n"
                else:
                    yield f"data: {json.dumps({'status': f'🔧 正在执行工具: {tool_name}...'}, ensure_ascii=False)}\n\n"
            # 👇 4. 监听工具执行结束（可选）
            elif event["event"] == "on_tool_end":
                # 工具执行完，前端清空状态
                yield f"data: {json.dumps({'status': ''}, ensure_ascii=False)}\n\n"
                yield f"data: {json.dumps({'status': '✅ 工具执行完毕'}, ensure_ascii=False)}\n\n"
            # 👇 5. 获取单次大模型调用的 Token 消耗
            elif event["event"] == "on_chat_model_end":
                output = event["data"].get("output")
                if output and hasattr(output, "usage_metadata"):
                    usage = output.usage_metadata
                    if usage:  
                        total_tokens += usage.get("total_tokens", 0)  # 累加 Token         
    except Exception as e:
        # 这一行会在终端打印完整的、极其详细的红色报错堆栈！
        traceback.print_exc()
        # 把错误也发给前端，防止前端黑屏
        yield f"data: {json.dumps({'error': str(e)}, ensure_ascii=False)}\n\n"
    finally:
            # 3. 任务结束，计算总用时
            end_time = time.time()
            duration = round(end_time - start_time, 2)  #内置函数round：用来对浮点数（小数）进行四舍五入,这里保留两位。
            
            # 推送最终汇总数据
            summary = {
                "type": "task_summary",
                "total_tokens": total_tokens,
                "duration_seconds": duration
            }
            yield f"data: {json.dumps(summary, ensure_ascii=False)}\n\n"  # \n\n 标识一个事件（Event）结束
            yield "data: [DONE]\n\n"  # [DONE]\n\n 标识整个流式任务彻底全部结束