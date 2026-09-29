# Fund Agent

基于 FastAPI + LangGraph 的 AI 智能体项目：后端提供有状态对话、工具调用、长期记忆与完整可观测性，并配套 React 前端。

架构基于社区开源项目 [fastapi-langgraph-agent-production-ready-template](https://github.com/wassim249/fastapi-langgraph-agent-production-ready-template)（MIT License）改造而来，感谢原作者 Wassim EL BAKKOURI。

---

## 功能特性

当前产品形态是**个人基金管理应用**（需求与技术规范见 [docs/PROJECT_SPEC.md](docs/PROJECT_SPEC.md)），在第一阶段闭环之外保留了模板的 Agent 基础设施：

- **基金数据** — AKShare 采集基金净值与持仓披露，个股与指数行情走新浪/腾讯，统一在 `FundDataProvider` 等适配器后面隔离；基金净值（`fund_nav`）与指数收盘（`index_quote`）落库 PostgreSQL + 热点缓存，个股报价、K线/分时与重仓股披露只按需实时抓、不落库，抓不到就留空而不是补假数。区间收益/最大回撤/波动率由后端 Python 计算（`app/analytics`），不由 LLM 计算
- **自选基金** — 搜索、加删、分组与组内排序，列表带最新净值、当日涨跌与持有标识
- **持仓管理** — 多账户与资产汇总；录入分两条互不打架的路径：**同步持仓**记第三方 App 上的快照（按金额或按份额两种口径各配一对数字），**加减仓**记加仓/减仓/定投/转换四笔操作，写进 `transaction` 流水账本。份额与持仓成本是流水的投影（卖出按持仓均价结转成本，不按卖出价），首次动账会先把当时的快照种成期初行；下单按 15:00 cutoff 落到确认日、用确认日净值定价，成交预览与写入同一套算法。派生指标查询时计算不落库；乐观锁 409、当日净值未公布 409、卖出超过持有 422
- **定投计划** — 每天/每周/每两周/每月 + 扣款日，读计划列表时把到期未记的期数补成流水（幂等键去重），净值未出的那一期延后补
- **持仓导入** — 手动录入与第三方 App 截图识别两条来源，统一 `HoldingImportProvider`；一律「解析 → 预览 → 用户确认 → 写入」，原图仅临时保存并在确认/失败后删除
- **行情分析** — 基金详情页的净值走势与指数基准对比（指数收盘按缺口增量补库）、前十大重仓股与行业分布；个股/指数分析页的蜡烛图（日K/周K/月K）与分时/五日，行情侧全部实时抓上游、不落库
- **后台任务** — Taskiq + Redis（无 Redis 时进程内兜底）、有界并发、幂等键与分布式锁、PostgreSQL 侧任务账本（状态/重试/错误）
- **Agent 预留** — LangGraph 图、Checkpointer、LLM 服务、Langfuse 全部保留；`POST /api/v1/agent/chat` 返回 501，App 保留 Agent Tab
- **可观测性与安全** — structlog、Prometheus 指标、JWT（Access + Refresh，登出可撤销）、slowapi 限流、输入清洗、detect-secrets
- **前端** — `mobile/` Expo + React Native + Expo Router + TanStack Query + Zustand + SecureStore（Android / iOS / Web 同一套代码，接口类型由后端 OpenAPI 生成）；`frontend/` 为模板遗留的网页聊天端

## 快速开始

### 后端

所有后端 `make` 命令均在 `backend/` 目录下执行：

```bash
cd backend
cp .env.example .env.development   # 填入 LLM / Embedding / JWT 密钥与 POSTGRES_* 连接
make install                       # 安装依赖 + pre-commit hooks
make migrate                       # 建表（需要本地 PostgreSQL）
make dev                           # 启动开发服务器（端口 8000，Windows 走 run_local.py）
make test                          # pytest 单测
make check                         # ruff + pyright
make worker                        # Taskiq worker（基金同步 + 截图识别，需 Redis）
```

`make` 目标依赖 `uv`。机器上没有 `uv` 时，用已经建好的虚拟环境直接调用等价命令：

```bash
.venv/Scripts/python.exe scripts/run_local.py --host 0.0.0.0 --port 8000   # 启动（手机也能连）
.venv/Scripts/python.exe -m alembic upgrade head                           # 迁移
.venv/Scripts/python.exe -m pytest -q                                      # 单测
```

不要直接跑 `uvicorn app.main:app`：Windows 下 psycopg 的异步驱动需要 Selector 事件循环，`run_local.py` 里已经设好。也别长期依赖 `--reload`，本机 StatReload 会静默漏保存。

打开 [http://localhost:8000/docs](http://localhost:8000/docs) 查看交互式 API 文档。

更多本地开发细节见 [docs_zh/getting-started.md](docs_zh/getting-started.md)。

### 移动端（Expo）

```bash
cd mobile
npm install
cp .env.example .env               # EXPO_PUBLIC_API_BASE_URL
npm run web                        # 浏览器版：http://localhost:8081
npx expo run:android --device      # 真机调试（需 Android 设备与开发构建）
```

真机访问后端必须使用电脑局域网 IP（例如 `http://192.168.1.10:8000/api/v1`），`localhost` 指向手机自身；同时要把该来源加进后端 `ALLOWED_ORIGINS`。`EXPO_PUBLIC_*` 是打包时内联的，改过 `.env` 要用 `npx expo start --web --clear` 重启才生效。

`npm run generate:api` 会从运行中的后端拉取 OpenAPI 并重新生成 `api/schema.ts`，避免前后端类型漂移（改了后端接口就跑一次，需要后端在 8000 上）。

### 网页端（模板聊天界面）

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
| `JWT_ACCESS_TOKEN_EXPIRE_DAYS` / `JWT_REFRESH_TOKEN_EXPIRE_DAYS` | 默认 1 天 / 90 天；登出会撤销刷新令牌 |
| `ALLOWED_ORIGINS` | CORS 白名单，需包含前端来源（如 `http://localhost:8081`） |
| `AKSHARE_MAX_CONCURRENCY` / `_TIMEOUT_SECONDS` / `_MAX_RETRIES` / `_MIN_INTERVAL_SECONDS` | 外部基金数据采集的并发、超时、重试与节流 |
| `FUND_NAV_STALE_HOURS` / `FUND_BUSINESS_TZ` | 净值新鲜度窗口与业务日历（交易日/持有天数口径） |
| `FUND_HOT_SYNC_ENABLED` / `FUND_HOT_SYNC_INTERVAL_MINUTES` | 热基金周期扫描（默认关闭，仅入队，由 worker 执行） |
| `VISION_*` | 持仓截图识别的视觉模型（默认 SiliconFlow Qwen-VL），未配置时批次置 `PARSE_FAILED` |
| `HOLDING_IMPORT_MAX_IMAGES` / `_MAX_IMAGE_MB` / `_TEMP_DIR` / `_STALE_MINUTES` | 截图导入的文件数量/大小/临时目录/僵死批次回收 |
| `TASKIQ_REDIS_URL` / `BACKGROUND_TASK_MAX_ATTEMPTS` | 后台任务队列与重试预算 |
| `LANGFUSE_TRACING_ENABLED` | Langfuse 追踪开关，不需要时设为 `false` |

## 项目结构

```
backend/             # FastAPI + LangGraph 后端（基金域）
  app/
    api/v1/          # auth、chatbot、funds、indexes、markets、watchlist、portfolio、
                     #  accounts、transactions、holding-imports、auto-invest、agent，汇总于 api.py
    core/            # config / cache(Valkey+兜底) / database(异步引擎) / task_queue /
                     #  limiter / logging / metrics / middleware / observability / prompts
    models/          # SQLModel 模型（多词类名需显式 __tablename__）
    schemas/         # Pydantic 请求/响应模型 + 图状态
    repositories/    # 异步数据访问（fund / portfolio / watchlist / import / job /
                     #  index / auto_invest）
    services/        # 领域服务单例（fund / fund_sync / watchlist / portfolio /
                     #  holding_import / auto_invest / market / memory / embeddings /
                     #  session_naming / llm）
    integrations/    # fund_data（AKShare 基金、新浪与腾讯行情 + normalizer）、
                     #  holdings（手动/截图 Provider + Vision Adapter）
    analytics/       # 纯函数金融计算：收益/回撤/波动率、持仓投影与推导、
                     #  15:00 确认日结算、定投到期日（金额一律不交给 LLM）
    workers/         # Taskiq 任务 + run_job 账本包装 + 周期调度
    utils/           # clock.py（时间口径唯一入口）、auth、sanitization…
    core/langgraph/  # Agent 图与工具
  alembic/           # 数据库迁移
  tests/             # pytest 单测（分析计算、结算与到期日程、各源 normalizer、任务账本）
  evals/             # LLM 评估框架（基于 Langfuse）
mobile/              # Expo + React Native 客户端（四 Tab：持有/自选/Agent/我的）
  api/               # client + 由 OpenAPI 生成的 schema.ts
  hooks/ stores/ components/ utils/  # 查询 hooks、Zustand、UI 原语、格式化
  app/               # Expo Router 路由文件（持仓编辑、下单、定投计划、流水、
                     #  重仓股、行情分析、导入等）
frontend/            # 模板遗留网页聊天端（React 19 + Vinext）
docs/ docs_zh/       # 项目文档（英/中）；docs/PROJECT_SPEC.md 为需求权威来源
```

## 文档

| 指南 | 内容 |
|---|---|
| [需求与技术规范](docs/PROJECT_SPEC.md) | **权威需求**（V5）：功能范围、架构、数据模型、验收标准 |
| [MVP 验收对照报告](docs/reports/mvp-build-report.md) | 逐条对照规范第 20 章的实测结果与剩余缺口 |
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

**App 里所有请求都失败？**
先看浏览器/设备的网络错误。CORS 未放行前端来源时后端返回 `400 Disallowed CORS origin`；把前端地址加进 `ALLOWED_ORIGINS` 并重启后端。真机请用局域网 IP。

**持仓截图识别一直是「识别失败」？**
检查 `VISION_*` 与 `SILICONFLOW_API_KEY`：账号未开通该模型时上游会返回 `403 Model disabled`，批次会落到 `PARSE_FAILED` 并带上错误信息，原图仍会被清理，不影响已有持仓。

**持仓份额和三方 App 上显示的对不上？**
用「同步持仓 · 按金额填」时，份额是按 `持有金额 ÷ 最新净值` 推出来的，而金额是截图那一天的数，净值一动推算份额就会跟着偏。要准就用「按份额填」直接报份额；一旦记过加减仓流水，份额与持仓成本就以账本投影为准，快照改不动它们。

**净值或行情一直不更新？**
落库的基金净值由 worker 同步（`make worker`，或把 `FUND_HOT_SYNC_ENABLED` 打开做周期扫描）；没 Redis 时队列只在进程内执行，进程一退就不再更新。指数收盘在读取时按缺口增量补库，前十大重仓股、行业分布与个股分时/K 线每次进页面实时抓，不依赖 worker。

**没有 Redis 能跑吗？**
可以。缓存与锁退化为进程内实现，后台任务由 InMemoryBroker 在进程内执行；但跨进程互斥与「不随进程死亡的持久队列」需要 Redis + `make worker`。

**如何添加自定义工具？**
在 `app/core/langgraph/tools/` 中添加 `@tool` 装饰的函数，并注册到该包导出的 `tools` 列表。Agent 下次启动自动加载，无需修改图结构。工具只能经 Service 访问数据（规范 4.4）。

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
