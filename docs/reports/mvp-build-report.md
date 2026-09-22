# MVP 验收对照报告

> 对照 `docs/PROJECT_SPEC.md`（V5）第 20 章 30 项验收标准
> 生成时间：2026-09-22
> 结论口径：**通过** = 本次已实测；**部分** = 已实现但有明确未覆盖条件；**未验证** = 需要外部条件（真机、真实视觉模型、Redis 等）才能确认

## 环境事实（影响判定）

| 项 | 本次环境 |
|---|---|
| PostgreSQL | 本机 5432，已 `alembic upgrade head`（4 个迁移版本） |
| Redis / Valkey | **未运行** → 缓存与锁走进程内兜底，Taskiq 走 InMemoryBroker |
| AKShare | 可用，实网解析成功（011452 → 华泰柏瑞质量成长混合） |
| 视觉模型 | SiliconFlow 返回 `403 Model disabled` → 截图**识别结果**未取到正样本 |
| Android 真机 | 无设备 |
| 检查命令 | `ruff check` / `ruff format --check` / pyright 0 error / `pytest` 49 passed / `tsc --noEmit` / `expo lint` / `expo export --platform web` 全部通过 |

## 第 20 章逐条对照

| # | 验收标准 | 判定 | 依据与说明 |
|---|---|---|---|
| 1 | Android 真机可启动、登录、使用 | **未验证** | 无真机。代码路径已就绪：`npx expo install` 依赖齐全，`app.json` 配好 scheme/插件。**人工步骤**：连上设备后执行 `npx expo run:android --device`，再 `npx expo start --dev-client`；`.env` 里把 `EXPO_PUBLIC_API_BASE_URL` 改成电脑局域网 IP（规范 11.2，`localhost` 指向手机自身） |
| 2 | Web 版共用同一 Expo 前端 | **通过** | `expo export --platform web` 成功；浏览器实测 http://localhost:8081 全流程可用 |
| 3 | 底部四个一级入口 | **通过** | 持有 / 自选 / Agent / 我的，Tab 图标用 expo-symbols（iOS 与 Material 名称分别校验） |
| 4 | 可搜索基金 | **通过** | 代码/名称/模糊均支持。实测：`中欧医疗`→4 条、`白酒`→2 条、`天弘中证`→50 条，均带最新净值与当日涨跌；首次查询约 4.6s（拉取榜单），之后进程内 6 小时复用、同一关键词共享缓存 0.03s。**限制**见「已知剩余缺口」的场内 ETF 一条 |
| 5 | 可加/删自选 | **通过** | 搜索页「+ 自选」、自选页「删除」均实测生效，列表计数同步刷新 |
| 6 | 可创建与切换自选分组 | **通过** | 创建「科技」分组并出现在列表与筛选芯片中；分组内排序 API（`PATCH /watchlist/groups/{id} {fund_codes}`）已在后端冒烟验证，UI 排序按钮未逐一点击 |
| 7 | 自选列表显示最新净值与当日涨跌 | **通过** | 实测 `3.129 / +0.36%` |
| 8 | 自选列表标记是否持仓 | **通过** | 实测显示「持有」徽标与副标题「已持有」 |
| 9 | 可进入基金详情页 | **通过** | 由列表/搜索行点击进入 `/fund/[code]` |
| 10 | 详情可查看基本信息、最新净值、历史走势 | **通过** | 概览 + 净值折线图（react-native-svg）+ 区间切换 1月/3月/6月/1年/3年/成立来；后端 `GET /funds/{code}/nav?range=` 实测 3m=65 点、all=1360 点 |
| 11 | 持有时详情展示金额/份额/成本/收益/占比 | **通过** | 实测：持有金额 ¥900.50、份额 295.1、占比 100.00%、持有收益 -¥137.20、收益率 -13.46%、当日收益 +¥3.24、成本 ¥1,019.19。**未覆盖**：`持仓成本净值`/`持有天数` 在「账户汇总」视图下为 `--`（`holding_days` 依赖具体账户的交易起点，汇总视图无法归属） |
| 12 | 可查看多个持仓账户及汇总 | **通过** | 实测创建账户、芯片切换、汇总卡片 |
| 13 | 可手工录入或修改持仓 | **通过** | 实测 `/position/edit`：预填原值 → 改金额 → 版本 v1→v2；后端 409 分支由单测外的接口冒烟覆盖 |
| 14 | 可查看基础交易/调整记录 | **通过** | `/transactions` 实测显示 `手工修正`、`导入修正`（含批次 ID 前缀） |
| 15 | 统一 `HoldingImportProvider` 接口 | **通过** | `app/integrations/holdings/base.py` Protocol，`parse(payload) -> draft` |
| 16 | `ManualImportProvider` 与 `ScreenshotImportProvider` | **部分** | 手动路径全链路实测；截图路径**机制**实测（202 + 后台解析 + 失败落库 + 原图删除），但**识别正确性**因视觉模型 403 未取到正样本。**人工步骤**：配置可用的 `VISION_*` 或 `SILICONFLOW_API_KEY` 后上传一张真实持仓截图，确认 `items_detected > 0` |
| 17 | 上传多张截图、查看结构化结果、修正后确认导入 | **部分** | 多图/去重/失败隔离在后端已实现并冒烟；确认页的差异预览（当前→识别→导入后）与逐条修正、跳过、确认已在**手动导入**路径实测；截图确认页因上一条只验证到 `PARSE_FAILED` 分支。Web 端图片选择器未做端到端点击验证（需系统文件对话框） |
| 18 | 截图识别不得直接改持仓，确认后写入 | **通过** | `confirm_import` 是唯一写路径；后端与 UI 均验证「确认前持仓不变」 |
| 19 | 导入具备状态、更新时间、错误记录、审计条目 | **通过** | `holding_imports`（状态/started/confirmed/applied/error_message/计数）+ `IMPORT_ADJUSTMENT` 审计行 |
| 20 | 原图默认在识别/确认完成后自动删除 | **通过** | 实测 `.runtime/holding_imports/` 在 `PARSE_FAILED` 后为空目录；确认与取消路径同样清理 |
| 21 | 基金与持仓数据有明确来源和更新时间 | **通过** | 详情返回 `source=akshare`、`source_as_of=2026-09-21`、`updated_at`、`nav_fetched_at`；持仓有 `updated_at`/`version` |
| 22 | 后端按 Service / Repository / Integration 分层 | **通过** | 目录已落位（`repositories/`、`integrations/`、`analytics/`、`workers/`）。**偏差**：规范 7.2 建议的 `domain/`、`core/redis.py`、`core/concurrency.py`、`workers/analytics.py` 未单独建（功能分别在 `core/cache.py`、服务内信号量、无预计算任务） |
| 23 | FastAPI/Repository/PostgreSQL/Redis 在线链路异步 | **部分** | 基金域全部走 SQLAlchemy Async + asyncpg；`cache_service` 异步。**遗留**：`app/services/database.py`（auth/chat 的 user、session 访问）仍在 `async def` 内用同步引擎，会阻塞事件循环，见任务清单第 12 项 |
| 24 | AKShare 阻塞调用不占用事件循环 | **通过** | Provider 内 `asyncio.to_thread` + Semaphore + 超时 + tenacity |
| 25 | 批量同步有界并发 | **通过** | `sync_funds_bounded` Semaphore，`AKSHARE_MAX_CONCURRENCY` 可调 |
| 26 | 截图识别由持久 Worker 执行，上传接口不等待 | **部分** | 接口立即返回 202 + `import_id`；Taskiq + Redis 路径已实现，但本次环境无 Redis，实际走 InMemoryBroker 进程内执行。**人工步骤**：起 Redis 后 `make worker`，再上传确认任务由 worker 消费 |
| 27 | 后台任务支持状态追踪、失败记录、有限重试 | **通过** | `background_job` 账本（job_type/status/retry_count/started_at/finished_at/error_code/error_message）+ `run_job` 有界重试，由 49 项单测覆盖；实测 FUND_SYNC 任务落库 SUCCEEDED |
| 28 | 同一基金同步有幂等控制与 Redis 分布式锁 | **部分** | 锁键 `fund_sync:{code}:{business_date}` 与 upsert 幂等已实现；无 Redis 时降级为进程内锁（跨进程不互斥） |
| 29 | 持仓修改具备乐观锁或等效并发保护 | **通过** | `expected_version` 不匹配返回 409，UI 有专门文案；实测版本递增 |
| 30 | Agent Tab 与后端扩展位保留且不影响业务 | **通过** | `POST /api/v1/agent/chat` 返回 501；`/(tabs)/agent` 支持 `fund_code` 上下文；LangGraph/checkpointer/Langfuse 原样保留 |

**统计**：通过 24 项，部分 4 项（16、17、23、26、28 中 23/26/28 属环境或遗留限制），未验证 1 项（Android 真机）。

搜索链路补充说明：榜单索引在进程内缓存 6 小时（`_RANK_CACHE_TTL_SECONDS`），因此 Web 端首次按名字搜索会慢一次；多用户共享同一份归一化索引，用户私有标记（是否自选/持有）始终实时批量查询，不进缓存。

## 本次修复的阻断级缺陷（否则主链路根本跑不通）

1. `portfolio_repository.upsert_position` 函数体引用已删除的 `**fields` → 任何持仓写入 `NameError`
2. SQLModel 默认表名（`portfolioaccount`）与迁移表名（`portfolio_account`）不一致 → 7 张新表运行时不可达
3. 时间戳混用本地时间与 aware UTC → asyncpg 直接拒绝写入（`can't subtract offset-naive and offset-aware`）
4. `schemas` 与 `integrations` 重复定义 `ManualPositionInput` → 手动录入必然 `ValidationError`
5. 业务路由强依赖聊天会话令牌 → 登录令牌无法访问基金接口；改为 `AuthIdentity` 双令牌兼容
6. 持仓写入未校验账户归属（可向他人账户写入）；refresh token 可当 access token 使用
7. 服务导入 worker 造成的循环依赖（此前用函数内 import 绕过）→ 改为按任务名入队 + 启动时注册
8. CORS 未放行 Expo Web 来源 → 浏览器端所有请求被拒
9. 详情页「空态」回调无条件返回 → 有持仓也显示「未持有」；行内操作按钮嵌在链接里导致点击串味（改为兄弟节点）
10. **按名称搜索基金永远为空**：AKShare 榜单返回中文列名原始行，Provider 却按 `fund_code`/`fund_name` 英文键过滤，条件恒不成立；同时榜单里存在 `日期=NaT` 的脏行，`to_date` 撞上 pandas NaT 直接抛 `TypeError` 把整次搜索打成 500。现改为「先归一化再匹配」的榜单索引 + 解析层统一识别 NaN/NaT/占位符，并补 8 项单测锁定
11. 搜索命中的新基金列表没有净值：榜单携带的 `单位净值/日增长率` 被丢弃，只写了基金主表。现在记录级落库 `fund_nav`，并对历史遗留的无净值行做一次回补（读仍只读 PostgreSQL）

## 已知剩余缺口（建议后续处理）

| 优先级 | 事项 |
|---|---|
| 高 | `app/services/database.py` 迁移到异步引擎（规范 7.5 / 验收 23） |
| 高 | 接入可用视觉模型，补齐截图识别正样本回归（含多图去重、差异预览） |
| 中 | 汇总视图下 `holding_days`/`average_cost_nav` 缺失的展示口径；`profit_loss_rate` 等百分比字段单位在 API 内按字段名区分（`*_return` 为百分数值，`*_rate` 为小数），建议在 schema 层统一 |
| 中 | 场内 ETF/LOF 等不在 AKShare「开放式基金榜单」内的代码搜不到（例：`512888`），且按代码直连抓取也取不到数据；需要接 `fund_etf_spot_em` 等场内接口或换商业数据源 |
| 中 | 基金列表的 `related-sectors` 仍是占位；市场指数简览（规范 2 可选）未做 |
| 中 | 冷基金低频更新策略未单独实现（当前按需 + 热基金扫描） |
| 低 | 网页端 `frontend/` 仍是模板聊天壳，未接入基金业务；如需 Web 版业务界面，建议复用 `mobile/` 的 `api/` + `hooks/` |
| 低 | 规范 7.2 的 `domain/` 目录、`core/redis.py`、`workers/analytics.py` 未单独建档 |

## 可复现的验证步骤

```bash
# 后端
cd backend
cp .env.example .env.development            # 填入 JWT / POSTGRES / LLM / VISION
make migrate                                 # 或 alembic upgrade head
make dev                                     # Windows 走 scripts/run_local.py
make worker                                  # 需要 Redis 时启用 Taskiq worker
uv run pytest -q                             # 49 passed

# 移动端（Web 冒烟）
cd mobile
npm install
cp .env.example .env                          # EXPO_PUBLIC_API_BASE_URL
npx expo start --web                          # http://localhost:8081
npx tsc --noEmit && npx expo lint

# 类型同步（后端启动后）
npm run generate:api
```
