# 架构

## 系统概览

```mermaid
graph TB
    Client["客户端\n(HTTP / SSE)"]

    subgraph FastAPI["FastAPI 应用"]
        MW["中间件\n（限流、指标、\n日志上下文、性能分析）"]
        Auth["认证\n(JWT)"]
        API["API 路由\n/chat, /chat/stream\n/auth/*, /health"]
    end

    subgraph Agent["LangGraph 智能体"]
        Graph["StateGraph\n(chat → tool_call → chat)"]
        Checkpointer["AsyncPostgresSaver\n（对话状态）"]
    end

    subgraph Services["服务"]
        LLM["LLM 服务\n（回退 + 重试）"]
        Memory["记忆服务\n(mem0 + 缓存)"]
        Tools["工具\n（并发执行）"]
    end

    subgraph Storage["存储"]
        PG[("PostgreSQL\n+ pgvector")]
        Cache["Valkey/Redis\n（可选）"]
    end

    subgraph Observability["可观测性"]
        Langfuse["Langfuse\n（LLM 追踪）"]
        Prometheus["Prometheus"]
        Logs["structlog\n(JSON / 控制台)"]
    end

    Client --> MW --> Auth --> API
    API --> Graph
    Graph --> LLM --> Langfuse
    Graph --> Tools
    Graph --> Memory --> Cache
    Graph <--> Checkpointer
    Memory --> PG
    Checkpointer --> PG
    API --> Prometheus
    API --> Logs
```

## 请求生命周期

```mermaid
sequenceDiagram
    participant C as 客户端
    participant MW as 中间件
    participant A as 认证
    participant G as LangGraph
    participant Mem as 记忆
    participant L as LLM
    participant T as 工具

    C->>MW: POST /chat（Bearer 令牌）
    MW->>MW: 限流、指标、请求 ID
    MW->>A: 验证 JWT → 会话
    A->>G: 调用图

    par 并发执行
        G->>G: aget_state（检查是否恢复）
        G->>Mem: 搜索相关记忆
    end

    G->>L: chat 节点——系统提示词 + 上下文 + 消息
    L-->>G: 带有 tool_calls 的响应？

    alt 包含工具调用
        G->>T: 并发执行工具
        T-->>G: 工具结果
        G->>L: 携带工具结果再次进入 chat 节点
        L-->>G: 最终响应
    end

    G-->>A: 响应消息
    G-)Mem: 添加记忆（后台任务）
    A-->>C: JSON 响应
```

## 智能体图

智能体是一个双节点 `StateGraph`：

```mermaid
graph LR
    START --> chat
    chat -->|存在 tool_calls| tool_call
    tool_call --> chat
    chat -->|不存在 tool_calls| END
```

- **`chat` 节点**——构建系统提示词，调用 LLM，并返回一个路由至 `tool_call` 或 `END` 的 `Command`
- **`tool_call` 节点**——并发执行所有工具调用，并将结果传回 `chat`
- **检查点存储器**——`AsyncPostgresSaver` 按 `thread_id`（会话）持久化完整的 `GraphState`，从而支持中断后恢复和多轮记忆

## 关键设计决策

**记忆搜索与状态检查并发运行。** 对每个非恢复请求，`aget_state`（检查中断）和 `memory.search`（获取相关记忆）通过 `asyncio.gather` 并行运行，每个请求可节省 200–500 毫秒。

**工具调用并发执行。** 当 LLM 在一次响应中返回多个工具调用时，它们都会通过 `asyncio.gather` 并行执行。

**系统提示词在模块加载时缓存。** `system.md` 只在启动时读取一次。每个请求的开销仅是使用用户姓名、当前日期时间和检索到的记忆执行 `.format()`，不发生文件 I/O。

**LLM 回退受总时限约束。** 每次调用以 300 秒总预算覆盖重试和回退；首段进度等待 120 秒，出现有效流式进度后按 60 秒无进展时限控制。部分输出不会通过自动重试或回退再次播放。配置见 [LLM 服务](llm-service.md)。

**用户名通过会话传递，而不是随请求查询数据库。** 创建会话时，用户显示名会复制到 `Session.username`。聊天请求直接从已加载的会话对象读取该值，不会产生额外查询。

**生成会话标题不会增加响应延迟。** 对于未命名会话的第一条消息，API 会以占位名称（用户消息的截断版本）原子地认领该会话，然后启动后台 `asyncio.Task`，调用快速 nano 模型并获取结构化输出。主聊天响应会立即返回，标题生成则并发进行。Postgres 中的原子操作 `UPDATE … WHERE name = ''` 可确保即使存在并发请求，也只有一个工作进程能够成功认领。

## 组件职责

| 组件 | 文件 | 职责 |
|---|---|---|
| LangGraph 智能体 | `app/core/langgraph/graph.py` | 编排对话循环 |
| LLM 服务 | `app/services/llm/` | 模型注册、重试、循环回退和结构化输出 |
| 记忆服务 | `app/services/memory.py` | mem0 语义记忆与缓存 |
| 会话命名 | `app/services/session_naming.py` | 在后台为新会话生成 LLM 标题 |
| 数据库服务 | `app/services/database.py` | 用户/会话 CRUD |
| 缓存服务 | `app/core/cache.py` | Valkey/Redis，并提供内存回退 |
| 中间件 | `app/core/middleware.py` | 指标、日志上下文和性能分析 |
| 认证 | `app/api/v1/auth.py` | JWT 创建和会话管理 |
