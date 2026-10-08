# Agent 图片持仓导入：后端接入协议

本阶段完成后端。网页端和移动端共用下述接口，下一阶段再添加选图、上传、识别进度和人工复核界面。现有聊天界面尚不能直接操作这些新增能力。

流程为：选定自己的账户 → 上传截图 → 后台 OCR 识别 → Agent 查询草稿 → LangGraph 暂停等待人工复核 → 人工确认或取消 → 恢复 Agent。上传和工具调用均不直接写正式持仓；只有认证后的人工决策请求可以应用草稿。已有持仓页面的导入流程仍可使用。

## 两个客户端的调用顺序

所有路径都以 `/api/v1` 为前缀，并携带**当前聊天会话的 access token**，不能用用户 token 或 refresh token 代替。账户可以通过现有账户接口选择。

| 操作 | 方法与路径 | 关键参数 / 返回值 |
| --- | --- | --- |
| 上传截图 | `POST /chatbot/holding-imports/screenshots?account_id=7` | multipart 字段 `files`，返回 202、`import_id`、`image_count`、`status=PARSING` |
| 查询进度和完整草稿 | `GET /chatbot/holding-imports/{import_id}` | `import_batch.status` 和 `items` |
| 发给 Agent | `POST /chatbot/chat` 或 `/chatbot/chat/stream` | 用户消息 + `holding_import_ids` |
| 恢复待确认卡片 | `GET /chatbot/pending-action` | `pending_action`，没有待确认时为 null |
| 确认 / 取消 | `POST /chatbot/holding-imports/{import_id}/decision` | `decision`、`interrupt_id`、`review_digest` |

默认允许 1～5 张 PNG/JPEG/WEBP，每张最多 8 MiB，沿用 `HOLDING_IMPORT_MAX_IMAGES` 和 `HOLDING_IMPORT_MAX_IMAGE_MB`。识别任务复用现有 Taskiq 队列和本地 OCR；原图不会作为 base64 或 URL 发给聊天模型。配置 Redis broker 时需要现有截图识别 worker；未配置时使用进程内 broker。

客户端应轮询进度，待 `REVIEW_REQUIRED` 后发起 Agent 请求。若提前发送，Agent 可以告知仍在识别，之后需再次查询；本版本不在识别完成后自动唤醒聊天。

```json
{
  "messages": [{"role": "user", "content": "帮我同步这些截图里的持仓，并让我确认"}],
  "holding_import_ids": ["aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"]
}
```

将示例 ID 替换为上传接口返回的 ID。后端验证每个批次的用户和会话归属，再把 ID 放入本轮动态上下文。模型工具仅接受批次 ID，不能提交图片路径、用户 ID、识别金额或基金代码。

## 工具与人工复核

- `get_holding_import(import_id)`：查询进度和最多 20 条草稿预览，完整草稿由 HTTP 接口提供。不会更新持仓。
- `request_holding_import_confirmation(import_id)`：对 `REVIEW_REQUIRED` 批次生成真实草稿的复核卡，通过 LangGraph `interrupt()` 暂停。不会调用持仓确认服务。

普通聊天响应 `ChatResponse.pending_action`、`GET /messages` 和流式最后一条 `done=true` 事件均可携带结构化复核卡。客户端应渲染 `items` 中的基金、金额、份额、识别置信度、校验问题、用户裁决和当前持仓对比，并显示 `notice` 中的覆盖语义。

复核卡提供 `kind=holding_import_review`、`import_id`、`account_id`、`image_count`、`interrupt_id`、`review_digest` 和完整 `items`。图 checkpoint 保存中断，重连或重启后通过 `/pending-action` 恢复。其正文仅提示打开复核面板，不以 Python 字典字符串展示卡片。

人工点击确认或取消时，从卡片复制两个标识，提交：

```json
{
  "decision": "confirm",
  "interrupt_id": "复制卡片的 interrupt_id",
  "review_digest": "复制卡片的 review_digest"
}
```

`decision` 为 `confirm` 或 `cancel`。成功响应包含确定的 `import_id`、`status`（`APPLIED` / `CANCELLED`）、`applied`、`skipped`、恢复后的 `messages` 和可能的下一张 `pending_action`。客户端应依赖这些结构化字段确认结果，不根据模型措辞推测写入成功。

普通聊天中的“确认”不会批准导入。存在待复核卡时普通聊天接口返回 409 `holding_import_review_pending`，客户端需先处理复核面板。确认接口核验实际中断 ID 和批次，模型无法伪造人工决策。

## 编辑、时效和失败恢复

已有 `PATCH /holding-imports/{import_id}/items/{item_id}` 用于修正草稿或设置 UPDATE / EDIT / SKIP。编辑后重新获取 `/chatbot/pending-action`，显示最新草稿和新指纹；旧指纹确认返回 409 `import_review_changed`，不写持仓。指纹覆盖全部条目、用户裁决及当前持仓对比，排除会变化的基金候选列表。

确认保持现有快照导入语义：按基金覆盖选定账户中本次采纳的字段，不删除截图中未出现的其他持仓，不制造买卖交易；每条生效持仓记录一条 IMPORT_ADJUSTMENT 调整流水。既有持仓保留原持有日期。

持仓、调整流水、账户导入时间和批次 APPLIED 状态在同一数据库事务内提交。批次确认、编辑及取消共用行锁。已应用批次重复确认返回原数量，不重复写入流水；失败事务完整回滚，回滚前不清理原图。确认或取消后清理临时图片，识别失败沿用原流程清理。

决策和图恢复按会话串行处理。配置 Valkey 时锁获取失败不会放行人工决策；单进程开发环境使用内存锁。多 API worker 部署应配置可用的 Valkey/Redis 缓存。并发决策返回 409 `holding_import_decision_in_progress`。

如果返回 503 `holding_import_decision_failed_check_status` 或 504 `holding_import_decision_timeout_check_status`，先查询批次状态，再重试同一决策。持仓应用可能已经提交而模型恢复失败；已应用状态不会重复导入。取消与已应用状态冲突会返回 409。跨用户、跨会话或非聊天上传的批次返回 404。

## 迁移和验证

迁移 `a62d8b409e15` 给 `holding_import` 增加可空 `chat_session_id` 及索引；已有普通导入保持 NULL。开发数据库已升级。其他环境运行 `APP_ENV=<环境> ... alembic upgrade head` 后重启后端。工具集与系统提示词的当前版本以注册表及提示词模块常量为准。

验证包括真实 LangGraph 的人工中断/恢复、流式卡片、刷新恢复、归属隔离、旧指纹拒绝、普通聊天拒绝确认、重复与并发决策、恢复失败重试、有效及无效图片上传。另用 PostgreSQL 回滚事务验证中途失败没有部分持仓或流水，以及重复确认的幂等性。自动测试不调用真实聊天模型。

2026-10-08 验证结果：全量后端测试 465 项通过、4 项可选数据库测试跳过；本功能的 2 项 PostgreSQL 测试另行启用后全部通过。Ruff、Pyright 和当前后端环境导入检查通过；OpenAPI 已包含四个新增接口，两个新工具均已注册，本地 OCR 运行时可用。未进行网页/移动端交互验证，也未使用用户真实截图调用聊天模型。
