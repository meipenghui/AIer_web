#前端（Flet 或 Web）该怎么配合你这段 SSE 代码,在你的前端解析 SSE 的地方，你需要维护一个非常简单的状态机。
# 前端收到不同 SSE 事件时的 UI 更新逻辑

if data.get("type") == "reasoning":
    # 1. 显示“深度思考中”的状态条
    status_text.value = "💭 正在深度思考..."
    status_text.color = "gray"
    
    # 2. 把思维链追加到折叠面板
    reasoning_panel.value += data["text"]

elif "text" in data:
    # 1. 清空并隐藏状态条（因为正式答案开始输出了！）
    status_text.value = ""
    
    # 2. 如果折叠面板是展开的，自动收起来（把屏幕留给答案）
    reasoning_panel.visible = False 
    
    # 3. 打字机追加到主气泡
    chat_bubble.value += data["text"]

elif "status" in data:
    # 处理工具执行等状态
    if data["status"]:
        status_text.value = data["status"]
        status_text.visible = True
    else:
        status_text.visible = False # 收到空字符串，就隐藏状态栏