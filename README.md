# Fund Agent

基于 FastAPI + LangGraph 的 AI 智能体项目：后端提供有状态对话、工具调用、长期记忆与完整可观测性，并配套 React 前端。

架构基于社区开源项目 [fastapi-langgraph-agent-production-ready-template](https://github.com/wassim249/fastapi-langgraph-agent-production-ready-template)（MIT License）改造而来，感谢原作者 Wassim EL BAKKOURI。

---

## 功能特性

- **LangGraph 智能体** — `chat ↔ tool_call` 循环图，Postgres checkpoint 持久化会话历史，支持 human-in-the-loop（`ask_human` 工具中断/恢复）
- **长期记忆** — mem0 + pgvector，自托管于项目 PostgreSQL，按用户语义检索，带缓存层
- **LLM 服务** — OpenAI 兼容端点（默认 DeepSeek），tenacity 指数退避重试、循环模型回退、总超时预算兜底
- **可观测性** — Langfuse 全链路追踪（可关闭）、Prometheus 指标、structlog 结构化日志
- **安全** — JWT 认证 + 会话管理、slowapi 限流、输入清洗、detect-secrets 预提交检查
- **基础设施** — Alembic 迁移、可选 Valkey/Redis 缓存
- **前端**（`frontend/`）— React 19 + Vinext + Tailwind 4，连接本后端 API

## 快速开始

### 后端

所有后端 `make` 命令均在 `backend/` 目录下执行：

```bash
cd backend
cp .env.example .env.development   # 填入 LLM / Embedding / JWT 密钥与 POSTGRES_* 连接
make install                       # 安装依赖 + pre-commit hooks
make migrate                       # 建表（需要本地 PostgreSQL）
make dev                           # 启动开发服务器（端口 8000）
```

打开 [http://localhost:8000/docs](http://localhost:8000/docs) 查看交互式 API 文档。

更多本地开发细节见 [docs_zh/getting-started.md](docs_zh/getting-started.md)。

### 前端

```bash
cd frontend
npm install
npm run dev        # http://localhost:3000
```

默认连接 `http://localhost:8000/api/v1`，可在 `frontend/.env.local` 中用 `NEXT_PUBLIC_API_BASE_URL` 覆盖，详见 [frontend/README.md](frontend/README.md)。

## 关键配置

在 `backend/.env.development` 中配置（完整变量及默认值见 [docs_zh/configuration.md](docs_zh/configuration.md)）：

| 变量 | 用途 |
|---|---|
| `FUND_LLM_*` | LLM 端点、密钥、模型（OpenAI 兼容，默认 DeepSeek） |
| `FUND_EMBEDDING_*` / `SILICONFLOW_API_KEY` | mem0 长期记忆的 embedding 服务（默认 SiliconFlow Qwen3-Embedding） |
| `JWT_SECRET_KEY` | 32 位以上强随机字符串 |
| `LANGFUSE_TRACING_ENABLED` | Langfuse 追踪开关，不需要时设为 `false` |

## 项目结构

```
backend/             # FastAPI + LangGraph 后端
  app/
    api/v1/          # 路由（auth.py、chatbot.py、api.py）
    core/
      config.py      # 配置（os.getenv 实现，FUND_* 前缀变量可覆盖默认值）
      cache.py       # Valkey/Redis 缓存 + 内存兜底
      langgraph/     # Agent 图 + 工具
      limiter.py     # 限流（slowapi）
      logging.py     # structlog
      metrics.py     # Prometheus 指标
      middleware.py    # ASGI 中间件
      observability.py # Langfuse 初始化与回调
      prompts/       # 系统提示词（markdown 模板）
    models/          # SQLModel ORM 模型
    schemas/         # Pydantic 请求/响应模型 + 图状态
    services/        # LLM、数据库、记忆、embedding、会话命名等服务
  alembic/           # 数据库迁移
  evals/             # LLM 评估框架（基于 Langfuse）
frontend/            # React 前端
```

## 文档

| 指南 | 内容 |
|---|---|
| [快速开始](docs_zh/getting-started.md) | 前置条件、本地搭建、第一个 API 调用 |
| [架构](docs_zh/architecture.md) | 系统设计、请求流程、组件图 |
| [配置](docs_zh/configuration.md) | 所有环境变量及默认值 |
| [认证](docs_zh/authentication.md) | JWT 流程、会话、端点参考 |
| [数据库与迁移](docs_zh/database.md) | Schema、Alembic、pgvector |
| [LLM 服务](docs_zh/llm-service.md) | 模型、重试、回退、超时预算 |
| [记忆](docs_zh/memory.md) | mem0 长期记忆、缓存层 |
| [可观测性](docs_zh/observability.md) | Langfuse、日志、Prometheus、profiling |
| [评估](docs_zh/evaluation.md) | 评估框架、自定义指标、报告 |

> 以上指南另有英文版，位于 [docs/](docs/)。

## 常见问题

**如何添加自定义工具？**
在 `app/core/langgraph/tools/` 中添加 `@tool` 装饰的函数，并注册到该包导出的 `tools` 列表。Agent 下次启动自动加载，无需修改图结构。

**LLM 调用失败怎么处理？**
两层容错：单模型内 tenacity 指数退避重试；重试耗尽后循环切换到 `LLMRegistry` 中下一个模型。总超时预算（`FUND_LLM_TIMEOUT_SECONDS`）保证延迟有界。

**可以不用 Langfuse 吗？**
可以。设置 `LANGFUSE_TRACING_ENABLED=false`，Agent 行为不变，结构化日志仍记录 request/session/user 上下文。

**API 启动失败？**
- 确认 PostgreSQL 已启动，且 `POSTGRES_*` 配置正确
- 确认 `backend/.env.development` 存在，且 `JWT_SECRET_KEY` 至少 32 字符
- 在 `backend/` 下执行迁移：`make migrate`

**长期记忆搜索无结果？**
- 确认 PostgreSQL 启用了 `pgvector` 扩展
- 确认 embedding 配置有效（`FUND_EMBEDDING_*`、`SILICONFLOW_API_KEY`）

## 许可证与安全

- 本项目基于 MIT 许可证发布，上游版权声明见 [LICENSE](LICENSE)
- 安全问题请勿公开提交 issue，参见 [SECURITY.md](SECURITY.md)
- 开发规范与代码约定见 [AGENTS.md](AGENTS.md)
