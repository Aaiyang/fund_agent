# mem0 与数据库用户画像

长期语义记忆继续使用 mem0 + pgvector。画像由 PostgreSQL 管理，只有用户直接编辑或人工确认的字段生效，不从已有 mem0 记录自动推断。当前完成后端，frontend/mobile 画像管理页面尚未接入。

## 信息与字段

`user_persona` 保存已确认字段、递增版本与每字段来源；`user_persona_proposal` 保存未确认变更、当前用户原文、来源会话与消息 ID；`user_persona_history` 保存已提交变更。实际持仓、交易、净值和收益继续查询业务工具。

| 字段 | 允许值 |
| --- | --- |
| `response_language` | `zh-CN` / `en` |
| `response_detail` | `concise` / `balanced` / `detailed` |
| `investment_experience` | `beginner` / `intermediate` / `experienced` |
| `risk_preference` | 用户自述 `conservative` / `balanced` / `aggressive` |
| `investment_horizon_months` | 严格整数1–600，拒绝字符串和布尔值 |
| `investment_goals` | 最多5条，每条1–120字 |
| `excluded_fund_types` | `equity` / `bond` / `money_market` / `mixed` / `index` / `qdii` / `fof` / `reit` / `commodity` |

省略字段保持原值，显式null删除字段；未知字段、持仓金额、身份和系统指令字段返回422。目标文本是数据，不能改变工具权限或系统规则。画像不是正式风险测评或交易授权。第一阶段投资目标和期限为整体声明，涉及不同资金且范围不明确时应先澄清。

## 接口

基路径 `/api/v1/agent/user-profile`，无末尾斜杠。全部接口有限流，接受用户或会话 access token，拒绝 refresh token；身份始终来自鉴权，客户端不能提交 `user_id`。

| 方法及后缀 | 功能 |
| --- | --- |
| GET 基路径 | `revision`、`fields`、`provenance`、`pending_proposals`；新用户版本0，未知字段为null |
| PATCH 基路径 | 用户直接编辑已确认画像 |
| DELETE 基路径 | 清除画像、候选、原文证据和历史，保留空画像与递增版本 |
| GET `/history?limit=20` | 变更历史按版本倒序，limit范围1–100 |
| POST `/proposals/{id}/decision` | 用户接受或拒绝候选 |

编辑示例：

```json
{"expected_revision":0,"changes":{"response_detail":"concise","risk_preference":"conservative"}}
```

人工确认示例：

```json
{"expected_revision":0,"decision":"accept"}
```

拒绝使用 `reject`；清除请求体为 `{"expected_revision":1}`。过期更新返回409，需要重新读取；其他用户候选返回404。同一已接受或已拒绝决策重复提交不推进版本或追加历史，已终结候选不能反向决策。

直接编辑或接受候选会将其他待确认候选标为 `SUPERSEDED`。拒绝不推进画像版本。每用户最多20个待确认候选；同消息、同版本与相同变更重复提议复用原记录。

## Agent 与 mem0

用户明确要求长期记住或纠正时，Agent 可调用 `propose_user_profile_update(changes, evidence)`。工具身份、会话与消息 ID 来自真实运行时，证据必须是当前 HumanMessage 中不超过500字的原文。助手、工具、截图和旧消息不能作为来源。

工具只创建 `PENDING`，不改变已确认字段；普通聊天“确认”不能生效。客户端读取 `pending_proposals`，展示证据与字段变更，再调用独立人工决策接口。不存在供模型使用的确认、清除画像工具。

每次 chat 节点读取当前已确认画像，覆盖非流式、流式和人工中断恢复路径。画像放入动态上下文尾部；候选、原文证据和审计历史不注入。语义记忆也按问题在动态尾部召回，不将缺失画像字段补成已确认事实。数据库失败会明确降级；用户当前明确纠正优先于旧画像。

原文匹配只证明来源，不能证明模型理解正确。人工复核要检查假设、否定和资金范围。清除画像不清除 mem0 记忆或聊天检查点，也不能撤回在途模型请求；旧版本编辑和确认不能恢复已清除字段。

## 部署与验证

运行 `alembic upgrade head`，迁移 `d31f9a6b8204` 新增三张表，随后重启后端。`USER_PERSONA_ENABLED=true` 默认开启 Agent 自动读取；false只关闭自动注入，管理接口仍可用。

工具版本 `v4`，当前提示词版本 `fund-agent-v7`。画像提议沿用已有 LangGraph/Langfuse 调用链，没有额外画像提取 LLM。单元/API/Graph 测试覆盖白名单、鉴权、证据和故障降级；`FUND_TEST_POSTGRES=true` 运行 `tests/test_user_persona_postgres.py` 验证真实数据库隔离、幂等、旧版本保护、清除和回滚，临时数据最终回滚。

增量记忆写入、可靠队列、按问题动态召回和人工纠错已接入，详见 [语义记忆](SEMANTIC_MEMORY.md)。旧 mem0 条目暂时隔离，不自动转成已确认画像。
