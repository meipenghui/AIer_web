# AIer - 智能编程中枢

一个基于 **FastAPI + LangChain/LangGraph** 的全栈 AI 编程智能体（Coding Agent）项目。前端为 Nginx 托管的单页应用，后端通过 SSE 流式推送 Agent 的思考、工具调用与回答过程，支持多用户隔离、用户自定义模型配置、项目级长期记忆与人机回环（Human-in-the-Loop）安全护栏。整套服务通过 Docker Compose 一键编排部署。

## 技术栈

| 层 | 技术 |
|---|---|
| 后端 | FastAPI、Uvicorn、SQLAlchemy 2.0（async）、Pydantic Settings |
| Agent 框架 | LangChain 1.3 + LangGraph 1.2（create_agent + 中间件体系） |
| 数据库 | PostgreSQL 15（业务数据 + LangGraph Checkpoint/Store 记忆持久化） |
| 缓存/令牌 | Redis 7（刷新令牌存储） |
| 本地模型 | Ollama（本地大模型推理，OpenAI 兼容端点） |
| 前端 | 原生 HTML/JS 单页应用（marked + highlight.js + DOMPurify） |
| 部署 | Docker Compose + Nginx 反向代理 |

## 项目结构

```
9-CI-CD-nginx-docker/
├── backend/                # FastAPI 后端
│   ├── main.py             # 应用入口：注册/登录/Agent配置/对话/状态查询等 API
│   ├── agent.py            # Agent 构建：默认 Agent + 按用户配置动态创建（带缓存）
│   ├── Middleware.py       # 自定义中间件：项目长期记忆动态注入（.agent/memory.md）
│   ├── coding_tools.py     # Agent 工具集：文件读写/终端执行/代码搜索/邮件/联网搜索
│   ├── SSE.py              # SSE 流式生成器：思维链、工具调用、Todos、token 统计推送
│   ├── models.py           # SQLAlchemy 模型：users / user_model_configs 表
│   ├── schemas.py          # Pydantic 请求/响应模型
│   ├── postgresql_db.py    # PostgreSQL 异步会话与初始化
│   ├── redis_db.py         # Redis 连接池
│   ├── dependence.py       # JWT 鉴权依赖（get_current_user）
│   ├── utils.py            # Token 编解码、API Key 加解密、密码哈希
│   ├── config.py           # 环境变量配置加载（.env）
│   ├── system_prompt.py    # Agent 基础系统提示词
│   ├── dockerfile          # 后端镜像（python:3.11-slim，非 root 运行）
│   └── requirements.txt
├── frontend/
│   └── index.html          # 深色主题聊天 IDE 界面（登录/注册/对话/Agent 状态面板）
├── nginx/
│   └── default.conf        # 静态页面托管 + /api/ 反向代理到 backend:8000
├── script/
│   └── files_system_tools.py
└── docker-compose.yml      # 五服务编排：backend / frontend(nginx) / db(postgres) / redis / ollama
```

## 核心功能

- **用户体系**：注册 / 登录，密码 bcrypt 哈希；JWT Access Token + Refresh Token（Redis 存储，支持过期刷新）。
- **多用户隔离**：会话 thread_id 以 `用户名_会话ID` 拼接隔离；每个用户可配置自己的模型（provider / model / base_url / temperature 等），API Key 加密落库。
- **Agent 对话（SSE 流式）**：实时推送思考状态、思维链（reasoning）、工具调用进度、TodoList 更新、token 消耗与用时统计。
- **Coding 工具集**：目录遍历、文件读/写/改/移动/删除（带路径穿越防护与读取截断保护）、终端命令执行、代码搜索、邮件发送、博查联网搜索。
- **Agent 中间件体系**：
  - `DynamicMemoryMiddleware`：项目级长期记忆，自动维护工作区 `.agent/memory.md` 并动态注入系统提示词；
  - `SummarizationMiddleware`：上下文超长自动总结压缩；
  - `HumanInTheLoopMiddleware`：删除文件、修改文件等敏感操作需人工审批；
  - `ModelCallLimit / ToolCallLimit`：模型与工具调用次数熔断，防无限套娃；
  - `ContextEditingMiddleware / TodoListMiddleware`：上下文清理与任务清单管理。
- **状态持久化**：LangGraph `AsyncPostgresSaver`（对话检查点）+ `AsyncPostgresStore`（长期存储），重启不丢会话；提供 `/api/agent/status` 查询会话消息数、工具调用数、上下文占用率等。

## 快速开始

### 1. 配置环境变量

在 `backend/.env` 中配置（参考 `backend/config.py` 所需字段）：

```env
DEEPSEEK_API_KEY=xxx
DEEPSEEK_URL=https://api.deepseek.com
DATABASE_URL=postgresql+asyncpg://postgres:122122@db:5432/AIer_Agent
MOMERY_DATABASE_URL=postgresql://postgres:122122@db:5432/AIer_Agent_Momery
REDIS_URL=redis://redis:6379/0
OLLAMA_URL=http://ollama:11434/v1
JWT_SECRET=xxx
JWT_ALGORITHM=HS256
MASTER_KEY=xxx
SECRET_KEY=xxx
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=10080
REFRESH_TOKEN_EXPIRE_DAYS=14
MAIL_USERNAME=xxx
MAIL_PASSWORD=xxx
MAIL_PORT=465
MAIL_SERVER=smtp.xxx.com
MAIL_FROM=xxx
```

### 2. 启动服务

```bash
docker-compose up --build
```

首次启动后需在数据库中创建记忆库（容器内执行）：

```bash
docker exec -it my_postgres psql -U postgres -c 'CREATE DATABASE "AIer_Agent_Momery";'
```

如需使用本地 Ollama 模型，先拉取模型（以 qwen2.5:0.5b 为例）：

```bash
docker exec -it my_ollama ollama pull qwen2.5:0.5b
```

然后在前端「模型配置」中选择 `ollama`，Base URL 填 `http://ollama:11434/v1`（容器间内网地址）即可。

### 3. 访问

| 服务 | 地址 |
|---|---|
| 前端页面 | http://localhost:8080 |
| 后端 API（直连） | http://localhost:8081/docs |
| PostgreSQL（宿主机调试） | localhost:5433 |
| Redis（宿主机调试） | localhost:6378 |
| Ollama（宿主机调试） | localhost:11434 |

## API 概览

| 接口 | 方法 | 说明 |
|---|---|---|
| `/api/register` | POST | 用户注册 |
| `/api/login` | POST | 登录，返回 access_token + refresh_hash |
| `/api/agent_config` | POST | 创建/更新当前用户的模型配置（需鉴权） |
| `/api/chat` | POST | 与 Agent 对话，SSE 流式返回（需鉴权） |
| `/api/agent/status` | GET | 查询指定会话的消息/工具/上下文占用统计（需鉴权） |

## 待完善方向

参见 [backend/readme.md](backend/readme.md)：RAG/AST 按需检索缓解大文件上下文爆炸、执行日志记录、动态工具调用、动态模型路由（本地小模型）、权限管理、Skills 机制、多模态等。
