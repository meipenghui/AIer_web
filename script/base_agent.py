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
                    "execute_terminal":True,
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
                    keep=10,
                ),
            ],
            ),
            TodoListMiddleware(),
        ],
    )