# 快速开始

## 前置条件

- Python 3.13+
- [uv](https://docs.astral.sh/uv/)——使用 `pip install uv` 安装
- PostgreSQL（本地或远程，应用通过 `POSTGRES_*` 变量连接）
- OpenAI API 密钥
- Langfuse 账户（可选——设置 `LANGFUSE_TRACING_ENABLED=false` 即可跳过）

## 本地部署

```bash
git clone <repo-url> my-agent
cd my-agent/backend

cp .env.example .env.development
# 填写：OPENAI_API_KEY、JWT_SECRET_KEY、POSTGRES_*（指向你的数据库）

make install       # 安装依赖和 pre-commit 钩子
make migrate       # 通过 Alembic 创建数据表
make dev           # 启动支持热重载的服务器，端口为 8000
```

打开 [http://localhost:8000/docs](http://localhost:8000/docs)。

Windows 本地开发可直接使用已有虚拟环境运行兼容启动脚本。该入口会切换到 psycopg
异步连接所需的 Selector 事件循环：

```powershell
cd backend
D:\python\env\fund_agent\Scripts\python.exe scripts\run_local.py --reload
```

## 第一次 API 调用

### 1. 注册用户

```bash
curl -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email": "you@example.com", "password": "Secret123!", "username": "you"}'  # pragma: allowlist secret
```

返回 `user_id` 和 JWT 令牌。

### 2. 创建会话

```bash
curl -X POST http://localhost:8000/api/v1/auth/session \
  -H "Authorization: Bearer <第 1 步获得的令牌>"
```

返回 `session_id` 和仅限该会话使用的 JWT。

### 3. 聊天

```bash
curl -X POST http://localhost:8000/api/v1/chatbot/chat \
  -H "Authorization: Bearer <会话令牌>" \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "你好！"}]}'
```

也可以使用流式端点获取实时响应：

```bash
curl -X POST http://localhost:8000/api/v1/chatbot/chat/stream \
  -H "Authorization: Bearer <会话令牌>" \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "你好！"}]}'
```

## 自定义智能体

你最可能需要修改的部分如下：

| 内容 | 位置 |
|---|---|
| 智能体个性与指令 | `app/core/prompts/system.md` |
| 可用工具 | `app/core/langgraph/tools.py` |
| LLM 模型与回退顺序 | `app/services/llm.py` → `LLMRegistry.LLMS` |
| 记忆集合名称 | `.env` 中的 `LONG_TERM_MEMORY_COLLECTION_NAME` |

## 运行 pre-commit 钩子

执行 `git commit` 时，钩子会自动运行。如需手动运行：

```bash
make pre-commit
```

钩子包括：尾随空格检查、YAML/TOML/JSON 验证、密钥检测、ruff 代码检查与格式化。

## 故障排除

**启动时出现数据库连接错误**

请确保 PostgreSQL 正在运行，且 `.env` 中的 `POSTGRES_*` 变量与实际配置相符。

**`could not translate host name "db"`**

`POSTGRES_HOST=db` 只能在容器网络内部解析（`db` 是 Compose 服务名称）。本地开发请在 `.env` 中将 `POSTGRES_HOST` 设置为 `localhost`。

**`detect-secrets` 阻止提交**

如果是误报，请在被标记的行末添加 `# pragma: allowlist secret`。

**Langfuse 错误**

在开发期间，可在 `.env` 中设置 `LANGFUSE_TRACING_ENABLED=false` 以完全禁用追踪。
