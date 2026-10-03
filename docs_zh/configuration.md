# 配置

所有配置均从环境变量中读取。请使用 `.env.development`、`.env.staging` 或 `.env.production`；应用会根据 `APP_ENV` 变量加载正确的文件。

复制 `.env.example` 以开始配置：

```bash
cp .env.example .env.development
```

---

## 应用

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `APP_ENV` | `development` | 环境：`development`、`staging`、`production`、`test` |
| `PROJECT_NAME` | `Fund Agent` | 显示在 API 文档和日志中 |
| `VERSION` | `1.0.0` | API 版本 |
| `DEBUG` | `false` | 启用调试日志和性能分析中间件 |
| `API_V1_STR` | `/api/v1` | API 前缀 |
| `ALLOWED_ORIGINS` | `*` | 以逗号分隔的 CORS 来源列表 |

---

## LLM

| 变量 | 默认值 | 必需 | 说明 |
| --- | --- | --- | --- |
| `OPENAI_API_KEY` | — | 是 | OpenAI API 密钥 |
| `DEFAULT_LLM_MODEL` | `gpt-5-mini` | 否 | 起始模型——回退顺序参见 [LLM 服务](llm-service.md) |
| `DEFAULT_LLM_TEMPERATURE` | `0.2` | 否 | 聊天补全的温度参数 |
| `MAX_TOKENS` | `2000` | 否 | 每次 LLM 响应的最大 token 数 |
| `MAX_LLM_CALL_RETRIES` | `3` | 否 | 切换到回退模型之前，每个模型的重试次数 |
| `LLM_TOTAL_TIMEOUT` | `60` | 否 | 整个回退循环的最大秒数 |
| `SESSION_NAMING_ENABLED` | `true` | 否 | 使用 LLM 后台任务，根据用户的第一条消息自动生成会话标题 |

---

## 长期记忆

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `LONG_TERM_MEMORY_COLLECTION_NAME` | `longterm_memory` | pgvector 集合名称 |
| `LONG_TERM_MEMORY_MODEL` | `gpt-5-nano` | mem0 用于提取记忆的 LLM |
| `LONG_TERM_MEMORY_EMBEDDER_MODEL` | `text-embedding-3-small` | 用于语义搜索的嵌入模型 |

---

## 数据库

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `POSTGRES_HOST` | `localhost` | PostgreSQL 主机 |
| `POSTGRES_PORT` | `5432` | PostgreSQL 端口 |
| `POSTGRES_DB` | `food_order_db` | 数据库名称 |
| `POSTGRES_USER` | `postgres` | 数据库用户 |
| `POSTGRES_PASSWORD` | `postgres` | 数据库密码 |
| `POSTGRES_POOL_SIZE` | `20` | SQLAlchemy 连接池大小 |
| `POSTGRES_MAX_OVERFLOW` | `10` | 超出连接池大小后允许的最大溢出连接数 |

---

## 认证

| 变量 | 默认值 | 必需 | 说明 |
| --- | --- | --- | --- |
| `JWT_SECRET_KEY` | — | 是 | 用于签署 JWT 的密钥——生产环境中应使用较长的随机字符串 |
| `JWT_ALGORITHM` | `HS256` | 否 | JWT 签名算法 |
| `JWT_ACCESS_TOKEN_EXPIRE_DAYS` | `1` | 否 | Access 令牌有效期（天），过期用 `POST /auth/refresh` 换新 |
| `JWT_REFRESH_TOKEN_EXPIRE_DAYS` | `90` | 否 | Refresh 令牌有效期；`POST /auth/logout` 会撤销此前签发的刷新令牌 |

---

## 缓存（Valkey/Redis，可选）

设置 `VALKEY_HOST` 后，应用会使用 Valkey/Redis 缓存记忆搜索结果并执行限流。如果未设置，则回退到内存 TTL 缓存（不同实例之间不共享）。

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `VALKEY_HOST` | ``（禁用） | Valkey/Redis 主机——留空则使用内存回退 |
| `VALKEY_PORT` | `6379` | 端口 |
| `VALKEY_DB` | `0` | 数据库索引 |
| `VALKEY_PASSWORD` | `` | 密码（如需要） |
| `VALKEY_MAX_CONNECTIONS` | `20` | 连接池大小 |
| `CACHE_TTL_SECONDS` | `60` | 记忆搜索结果的缓存 TTL |

---

## 可观测性（Langfuse）

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `LANGFUSE_TRACING_ENABLED` | `true` | 设为 `false` 可完全禁用追踪 |
| `LANGFUSE_PUBLIC_KEY` | — | Langfuse 项目公钥 |
| `LANGFUSE_SECRET_KEY` | — | Langfuse 项目密钥 |
| `LANGFUSE_HOST` | `https://cloud.langfuse.com` | Langfuse 主机（自托管或云端） |

---

## 限流

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `RATE_LIMIT_DEFAULT` | `200 per day, 50 per hour` | 回退限额 |
| `RATE_LIMIT_CHAT` | `30 per minute` | POST /chat |
| `RATE_LIMIT_CHAT_STREAM` | `20 per minute` | POST /chat/stream |
| `RATE_LIMIT_MESSAGES` | `50 per minute` | GET/DELETE /messages |
| `RATE_LIMIT_LOGIN` | `20 per minute` | POST /auth/login |
| `RATE_LIMIT_REGISTER` | `10 per hour` | POST /auth/register |

配置 Valkey 后，限流状态会在所有应用实例之间共享。若未配置，限额按进程分别计算。

---

## 性能分析（仅调试模式）

仅在 `DEBUG=true` 时启用。它会分析每个请求，并在请求耗时超过阈值时保存 JSON 报告。

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `PROFILING_DIR` | `/tmp/fastapi_profiles` | 性能分析 JSON 文件的目录 |
| `PROFILING_THRESHOLD_SECONDS` | `2.0` | 触发保存性能分析报告的最短实际耗时。设为 `0` 可分析每个请求。 |

---

## 日志

| 变量 | 默认值（开发） | 默认值（生产） | 说明 |
| --- | --- | --- | --- |
| `LOG_LEVEL` | `DEBUG` | `WARNING` | 日志级别 |
| `LOG_FORMAT` | `console` | `json` | 开发环境使用 `console` 彩色输出，生产环境使用 `json` 结构化日志 |

---

## 基金域（AKShare、持仓导入、后台任务）

基金事实由 `FundDataProvider` 采集后落库 PostgreSQL，截图导入在 Taskiq worker 中执行。
以下变量都经 `os.getenv` 读取，第三方接口限额可在线调整而无需改代码（规范 7.6、7.7、3.7.2）。

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `AKSHARE_MAX_CONCURRENCY` | `5` | Provider 并发数（信号量） |
| `AKSHARE_TIMEOUT_SECONDS` | `20` | 单次阻塞调用超时 |
| `AKSHARE_MAX_RETRIES` | `2` | tenacity 重试次数 |
| `AKSHARE_MIN_INTERVAL_SECONDS` | `0.2` | 调用间最小间隔（节流） |
| `FUND_NAV_STALE_HOURS` | `24` | 净值超过该小时数视为过期 |
| `FUND_NAV_REFRESH_COOLDOWN_SECONDS` | `120` | 同一用户两次「按需刷新净值」的最小间隔（打开持仓时触发） |
| `FUND_NAV_REFRESH_TIMEOUT_SECONDS` | `15` | 那次刷新等待批量净值表的上限，超时即返回上次数据 |
| `FUND_BUSINESS_TZ` | `Asia/Shanghai` | `trade_date` 与持有天数使用的日历 |
| `FUND_HOT_SYNC_ENABLED` | `false` | 由 API 进程周期入队热基金扫描 |
| `FUND_HOT_SYNC_INTERVAL_MINUTES` | `360` | 扫描间隔 |
| `HOLDING_IMPORT_MAX_IMAGES` | `5` | 单批截图数量上限 |
| `HOLDING_IMPORT_MAX_IMAGE_MB` | `8` | 单文件大小上限 |
| `HOLDING_IMPORT_TEMP_DIR` | `.runtime/holding_imports` | 原图临时目录（用后即删） |
| `HOLDING_IMPORT_STALE_MINUTES` | `30` | 卡在 `PARSING` 的批次回收阈值 |
| `TASKIQ_REDIS_URL` | `` | Broker 地址；留空则复用 `VALKEY_*`，无 Valkey 时退化为进程内执行 |
| `BACKGROUND_TASK_MAX_ATTEMPTS` | `3` | 持久任务总尝试次数（首次 + 重试） |

最新净值与搜索结果的热点缓存 TTL 不是环境变量，而是
`app/services/fund_service.py` 里的常量 `_LATEST_NAV_CACHE_TTL_SECONDS` /
`_SEARCH_CACHE_TTL_SECONDS`（300 秒）。

截图识别没有任何配置项：它在本地跑，PP-OCR 模型 + ONNX Runtime，用
`uv sync --extra ocr` 安装。没装这个 extra 时批次会以 `PARSE_FAILED` 失败并带上
`ocr_runtime_not_installed`，不会静默导入空结果，图片也从不发给第三方。
