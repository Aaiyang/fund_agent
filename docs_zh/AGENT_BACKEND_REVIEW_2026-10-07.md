# 后端 Agent 功能检查（2026-10-07）

> 本文保留首次检查的历史快照，测试数量、类型错误和代码行号均对应当时的工作区。后续恢复已修复模型档案重排导致的误切换问题，当前验证结果和剩余问题见 [恢复记录](F:/project/fund_agent/docs_zh/GIT_RECOVERY_2026-10-07.md)。

## 结论与范围

Agent 的基础对话、工具调度、人工确认、检查点和上下文管理已有实现。现有 357 个测试全部通过，基础 HTTP SSE 返回也通过了额外验证。但仍复现了 7 类功能缺陷，尚不能据此认定完整业务链路可以稳定上线。

本次检查针对当前工作区内容（包含已有的暂存、未暂存和未跟踪修改），没有修改业务代码、模型供应商档案或数据库。额外验证使用假模型、内存检查点、模拟数据库连接和模拟身份；没有请求真实 LLM、基金数据源或 Langfuse。

## 功能现状

| 功能 | 当前实现和验证情况 |
| --- | --- |
| 非流式聊天 | `/api/v1/chatbot/chat` 接入真实 LangGraph 图；假模型集成测试通过；长回复边界失败 |
| SSE 流式聊天 | `/api/v1/chatbot/chat/stream` 已接通；HTTP 验证模型文本和最终 `done=true` 正常 |
| 聊天历史 | 检查点支持历史读取、清空；长回复会使历史读取失败；摘要清理不完整 |
| 基金工具 | `search_funds`、`get_fund_snapshot`、`get_fund_history`、`get_fund_holdings` 已注册，调用领域服务 |
| 持仓工具 | `get_portfolio`、`get_positions` 已注册；身份通过已认证调用配置传入，输入 schema 不包含 `user_id` |
| 行情工具 | `get_market_context` 已注册，调用行情服务 |
| 通用工具 | `ask_human`、DuckDuckGo 搜索已注册；人工确认中断与恢复已有集成测试 |
| 工具循环保护 | 递归上限为 25，已有友好提示测试；重复调用保护存在跨轮次误拦截和批内漏拦截 |
| 上下文 | 最近轮次选择、预算校验、工具配对校验、摘要段和 epoch 持久化已有实现；二次压缩存在水位线错误 |
| 长期记忆 | 存在 mem0 接入和会话记忆快照实现；本次没有连接真实 pgvector / mem0 验证 |
| 模型设置 | 支持供应商档案读取、保存、切换和模型列表探测；保存后保持当前档案的逻辑存在缺陷 |
| 独立 Agent API | `/api/v1/agent/chat` 明确返回 501。符合 `docs/PROJECT_SPEC.md` 当前 MVP 占位约定，不作为缺陷 |

工具共 9 个，当前没有交易执行或持仓写入工具。

## 已复现缺陷

### 1. P1：重复工具限制累计整段会话，阻止后续正常查询

位置：[agent.py:291](F:/project/fund_agent/backend/app/agent/graph/agent.py:291)。

守卫统计 `state.messages[:-1]` 中的相同工具签名，包含之前所有用户轮次，而代码注释与设计要求是限制当前 Run。相同参数先前使用两次后，第三轮独立提问仍被拒绝。

复现：同一线程连续发送三个独立提问，每轮模型只调用一次同参数工具。实际工具执行次数为 2；第三轮收到 `DUPLICATE_TOOL_CALL`。行情工具无参数，也会受到该问题影响。

建议：按最近用户消息或显式 run id 划定计数范围；新用户轮次重新计数，同时保留同一轮循环保护。

### 2. P1：输出复用输入的长度限制，长回复使聊天和历史接口返回 500

位置：[chat.py:29](F:/project/fund_agent/backend/app/schemas/chat.py:29)、[agent.py:614](F:/project/fund_agent/backend/app/agent/graph/agent.py:614)。

`Message.content` 限制为 3000 字符，同时用于用户输入和模型输出。`__process_messages()` 将完整模型回复构造成该模型，超长时抛出 `ValidationError`。此时回复已经写入检查点，后续历史读取会重复失败。

复现：假模型回复 3001 个字符，`POST /api/v1/chatbot/chat` 返回 500；随后 `GET /api/v1/chatbot/messages` 也返回 500。直接调用 `get_response()` 和 `get_chat_history()` 同样失败。

建议：拆分输入与输出消息模型，让输入限制独立生效；输出和已有历史应可完整返回。

### 3. P1：二次摘要压缩重复计算覆盖范围，静默跳过最近历史

位置：[manager.py:227](F:/project/fund_agent/backend/app/agent/context/manager.py:227)、[manager.py:269](F:/project/fund_agent/backend/app/agent/context/manager.py:269)、[summary.py:58](F:/project/fund_agent/backend/app/agent/context/summary.py:58)。

触发条件：启用 `CONVERSATION_SUMMARY_ENABLED` 和 `BATCH_COMPACTION_ENABLED`，同一线程至少完成两次压缩。

Manager 追加新摘要段，同时传入旧摘要；摘要器生成的 `covered_turn_count` 却是“旧段覆盖数 + 本次轮次数”。Manager 随后对所有段的覆盖数求和，造成重计。

复现：第一次压缩覆盖 5 轮；第二次新增压缩 3 轮。实际摘要段计数为 `[5, 8]`，总水位线成为 13，正确值应为 8。在下一次组装中，仍应保留的最近第 8、9 轮消失，`recent_turn_count` 变为 0。

建议：统一为互不重叠的分段摘要，每段只记录本次新增覆盖数；或者改为单个累积摘要并替换旧段。补充连续两次以上压缩的覆盖一致性测试。

### 4. P1：清空聊天没有清理摘要，下一轮仍使用旧上下文

位置：[agent.py:623](F:/project/fund_agent/backend/app/agent/graph/agent.py:623)、[state_store.py](F:/project/fund_agent/backend/app/agent/context/state_store.py)、[manager.py:457](F:/project/fund_agent/backend/app/agent/context/manager.py:457)。

触发条件：该线程已有摘要，且摘要功能开启。

`clear_chat_history()` 清理检查点和记忆快照，但没有调用 `context_manager.forget_thread()`，也没有清空 `session.context_state`。因此清空聊天后，旧摘要仍会被注入下一条消息；即使只清理进程内缓存，重启后也可从数据库恢复旧摘要。

复现：预置摘要 `OLD_PRIVATE_CONTEXT`，调用真实清空方法（数据库 DELETE 使用模拟连接），再组装只有一条新用户消息的上下文，旧摘要仍然出现。

建议：清空检查点时同步清空会话持久化摘要和进程内摘要/epoch，并验证进程重启后仍不会恢复。

### 5. P2：同一批工具调用可以绕过重复限制

位置：[agent.py:290](F:/project/fund_agent/backend/app/agent/graph/agent.py:290)、[agent.py:330](F:/project/fund_agent/backend/app/agent/graph/agent.py:330)。

每个工具调用只统计当前 AI 消息之前的历史，当前批次内的相同参数不计入限制；并发执行时没有统一预留计数。

复现：一条 AI 消息包含 3 个相同工具和参数、不同 call id 的调用。默认限制为 2，实际 3 个全部执行。

建议：在调度前顺序审核并预留本轮计数，然后只并发执行获准的调用。

### 6. P2：保存模型档案时可能静默切换当前模型

位置：[agent.py:156](F:/project/fund_agent/backend/app/api/v1/agent.py:156)、[service.py:179](F:/project/fund_agent/backend/app/services/llm/service.py:179)。

API 先重建注册表，再调用 `refresh_profiles()`。刷新方法通过当前索引在“新列表”中读取档案名，已经无法知道重建前的当前档案。

复现：列表 `[A, B]`，当前选择 `B`；保存为 `[B, A]` 后，当前模型变成 `A`。删除、插入或重排档案都可能触发错误选择。

建议：在重建之前保存当前档案名称，再以名称恢复；当前档案被删除时才使用默认回退。

### 7. P2：摘要调用仍使用绑定工具的模型，并接受空摘要

位置：[summary.py:76](F:/project/fund_agent/backend/app/agent/context/summary.py:76)、[service.py:320](F:/project/fund_agent/backend/app/services/llm/service.py:320)。

`_default_summarize()` 注释要求使用不带工具的临时模型，但调用是 `llm_service.call(messages)`，没有提供 model 或其他覆盖参数。LLMService 因此走默认的绑定工具路径，而不是一次性模型路径。

复现：记录摘要调用参数，确认没有任何覆盖参数；模拟模型返回带 tool call、空 content 的 AIMessage，摘要函数直接返回空字符串。`compact()` 未校验摘要非空，随后推进覆盖范围的逻辑存在丢失上下文的风险。

建议：显式选择无工具的调用路径，对空摘要、工具调用和非文本输出进行校验，失败时保留原历史与原 epoch。

## 其他审查发现

- **多用户部署时的模型配置权限问题（静态检查）**：`/agent/llm/settings` 和 `/agent/llm/switch` 仅依赖普通 `get_current_identity`，操作的是进程全局注册表和服务端文件。任一已登录用户都能更改其他用户使用的模型；还可以在保留同名档案旧 Key 的同时改变 `base_url`，导致后续请求将该 Key 发往新地址。应明确配置管理员权限或按用户隔离。没有实际发送 Key 或请求任意地址。
- **聊天鉴权仍有同步数据库 I/O（静态检查）**：`get_current_session()` 调用的 `DatabaseService.get_session()` 在 async 方法内使用同步 SQLModel Session。并发聊天请求可能阻塞事件循环，这是已有的遗留实现，尚未满足项目“所有数据库操作 async”的规则。
- **风格规则未被完整检查**：ContextManager、SummaryManager、ToolResult 和多个测试仍有函数内 import；部分异常路径使用 `logger.error()`。现有 Ruff 规则不足以覆盖 AGENTS.md 中的所有约束。`rich` 也未在项目依赖中声明，本地虚拟环境无法导入它。

## 验证结果与边界

| 检查 | 结果 |
| --- | --- |
| Pytest 全部现有测试 | **357 passed**，17.65 秒 |
| Ruff | **All checks passed**；有无法读取缓存目录的权限警告 |
| Pyright（明确指定项目虚拟环境） | **39 errors，0 warnings** |
| 额外缺陷复现 | 上述 7 类缺陷均有本地复现；长回复另验证了实际 HTTP 500 |
| HTTP SSE | 验证模型文本完整返回，末条事件 `done=true` |
| 应用导入与 OpenAPI | 正常生成，56 个路径、70 个操作；未启动 lifespan 或连接真实服务 |
| Alembic 迁移图 | 单个 head：`b7d4e8f2a1c9`；仅检查迁移图，没有执行迁移 |

Pyright 错误集中在 [registry.py:46](F:/project/fund_agent/backend/app/services/llm/registry.py:46) 的 `params` 字典类型推断、[service.py:77](F:/project/fund_agent/backend/app/services/llm/service.py:77) 的可能未初始化变量，以及 [cache.py:268](F:/project/fund_agent/backend/app/core/cache.py:268) 的 await 类型。不能把这些诊断全部等同于实际运行错误，但当前没有通过项目要求的 typecheck。

Windows 环境没有可用的 `make` / `uv` 命令，本次直接使用现有虚拟环境执行等价检查。在 `backend/` 下运行：

```powershell
New-Item -ItemType Directory -Force .audit_tmp | Out-Null
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp .audit_tmp/pytest
.\.venv\Scripts\ruff.exe check . --no-cache
.\.venv\Scripts\python.exe -m pyright --pythonpath .\.venv\Scripts\python.exe
```

最初的 pytest 默认临时目录出现权限错误；改用已创建的工作区临时目录后，完整测试通过。默认解释器下的 Pyright 曾报告依赖找不到；以上 39 个错误是指定正确虚拟环境后的结果。

**未覆盖**：真实 PostgreSQL 迁移与持久化、真实 LLM 工具选择质量和供应商切换、外部基金/行情/搜索网络、mem0/pgvector、Langfuse 上报、Redis/Taskiq 和生产并发。现有假模型测试证明调用链与确定性逻辑，不能证明这些外部服务已配置正确或联网可用。

建议先修复跨轮次误拦截和长回复 500，再修复摘要水位线与清理逻辑；同时通过 typecheck。之后再进行隔离测试数据库和真实模型的完整联调。
