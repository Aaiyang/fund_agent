"""Fund Agent 后端的独立 Agent 模块.

目录职责（架构红线见 docs/PROJECT_SPEC.md 4.4：Agent → Tool → Domain Service）：
- graph/    LangGraph 图与节点（LangGraphAgent）
- tools/    工具注册表与工具实现（只调领域服务，禁止直连数据库）
- context/  上下文组装（历史修剪、消息格式转换、token 估算）
- prompts/  系统提示词与会话标题模板
"""
