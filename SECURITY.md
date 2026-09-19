# 安全策略

## 报告漏洞

请**不要**为安全漏洞创建公开 GitHub issue。

请通过 [GitHub Security Advisories](../../security/advisories/new) 或直接邮件联系维护者私下报告，内容包含：

- 漏洞描述及其潜在影响
- 复现步骤
- 建议的缓解措施

对确认的漏洞，我们会在 48 小时内确认收到，并在 7 天内给出修复或缓解方案。

## 生产部署前检查清单

- 设置强随机 `JWT_SECRET_KEY`（32 位以上字符）
- 轮换所有密钥 —— 永远不要使用 `.env.example` 中的示例值
- 设置 `DEBUG=false`
- 将 `ALLOWED_ORIGINS` 限制为实际的前端域名
- 不希望对话数据发送到 Langfuse 时，设置 `LANGFUSE_TRACING_ENABLED=false`
- 使用环境专属的 `.env` 文件 —— 永远不要把密钥提交到 git

## 内置安全措施

- 密码使用 bcrypt 哈希存储（绝不存明文）
- JWT token 包含 `jti` claim 保证唯一性
- 所有用户输入先经清洗再使用
- 认证与聊天端点均有限流
- `detect-secrets` 预提交钩子检测密钥泄露
- CORS 已配置（生产环境收紧 `ALLOWED_ORIGINS`）
