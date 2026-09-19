# 可观测性

## 概览

```mermaid
graph LR
    App["FastAPI 应用"]

    App -->|"LLM 追踪\n（每次调用）"| Langfuse
    App -->|"HTTP 指标\n(/metrics)"| Prometheus
    App -->|"结构化日志\n(stdout)"| Logs["日志聚合器\n（或 stdout）"]
    App -->|"慢请求性能分析\n（仅 DEBUG）"| Profiles["JSON 文件\n(PROFILING_DIR)"]
```

---

## Langfuse——LLM 追踪

每次 LLM 调用都通过 LangChain 的 `CallbackHandler` 进行追踪。追踪内容包括：

- 输入消息和输出
- token 用量和费用
- 每次调用及每个会话的延迟
- 模型名称、温度和其他参数

**设置：**

```bash
LANGFUSE_TRACING_ENABLED=true
LANGFUSE_PUBLIC_KEY=pk-...
LANGFUSE_SECRET_KEY=sk-...
LANGFUSE_HOST=https://cloud.langfuse.com   # 或自托管 URL
```

**在本地开发中禁用：**

```bash
LANGFUSE_TRACING_ENABLED=false
```

追踪记录也用作[评估框架](evaluation.md)的数据源。

---

## 结构化日志

所有日志都使用 [structlog](https://www.structlog.org/) 并保持统一格式：

- **开发环境**：彩色控制台输出
- **生产环境**：JSON（通过管道传给日志聚合器）

每条日志在相关信息可用时，都会自动携带 `request_id`、`session_id` 和 `user_id`，这些上下文由 `LoggingContextMiddleware` 绑定。

### 日志格式约定

```python
# 正确示例
logger.info("chat_request_received", session_id=session.id, message_count=5)

# 切勿这样写
logger.info(f"chat request received for {session.id}")  # 不要使用 f-string
logger.error("something failed", error=str(e))          # 异常应使用 logger.exception
```

规则：

- 事件名称采用 `lowercase_with_underscores` 格式
- 变量应作为关键字参数传入，绝不能插值到事件字符串中
- 在 `except` 块内使用 `logger.exception()`（而不是 `.error()`），以保留完整的回溯信息

### 各环境的日志级别

| 环境 | 级别 |
| --- | --- |
| development | DEBUG |
| staging | INFO |
| production | WARNING |

---

## Prometheus 指标

指标通过 `GET /metrics` 暴露，并由 Prometheus 抓取。

| 指标 | 类型 | 说明 |
| --- | --- | --- |
| `http_requests_total` | Counter | 按方法、端点和状态统计请求数 |
| `http_request_duration_seconds` | Histogram | 按方法和端点统计请求延迟 |
| `llm_inference_duration_seconds` | Histogram | 按模型统计 LLM 调用延迟 |
| `llm_stream_duration_seconds` | Histogram | 按模型统计流式调用延迟 |
| `db_connections` | Gauge | 活跃数据库连接数 |

---

## 请求性能分析（仅限调试模式）

当 `DEBUG=true` 时，`ProfilingMiddleware` 使用 [pyinstrument](https://github.com/joerick/pyinstrument) 分析每个请求。当请求耗时超过 `PROFILING_THRESHOLD_SECONDS` 时，会将 JSON 报告保存到 `PROFILING_DIR`。

每个报告文件均命名为 `{request_id}.json`，内容如下：

```json
{
  "request_id": "...",
  "endpoint": "POST /api/v1/chatbot/chat",
  "wall_time_ms": 1842,
  "cpu_time_ms": 145,
  "io_wait_ms": 1697,
  "memory_peak_kb": 4820,
  "top_memory_allocators": [...],
  "call_tree": {...}
}
```

设置 `PROFILING_THRESHOLD_SECONDS=0` 可分析每个请求。

文件名中的 `request_id` 与 `X-Request-ID` 响应头一致，因此可以将性能分析报告与具体日志行关联起来。

---

## 请求 ID 传播

每个请求都会通过 [`asgi-correlation-id`](https://github.com/snok/asgi-correlation-id) 获得唯一的 `X-Request-ID` 标头。此 ID 会：

- 在响应头中返回
- 绑定到该请求的每条日志
- 用作性能分析报告的文件名

使用响应中的 `X-Request-ID`，可以搜索日志、查找性能分析报告，并检索该请求对应的 Langfuse 追踪记录。
