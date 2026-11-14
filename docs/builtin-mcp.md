# Built-in MCP / 内置 MCP

PanWatch ships a fixed Longbridge connector. The account menu opens `/integrations/mcp`; the application's existing inbound `/mcp` endpoint remains separate. There is no marketplace, custom URL, package installer or local-command configuration.

## 使用步骤

1. 先登录 PanWatch，打开右上角菜单 → **MCP**。
2. 默认选择中国大陆节点 `https://mcp.longbridge.cn`；全球节点为 `https://mcp.longbridge.com`。
3. 点击 **前往长桥授权**，在同一浏览器标签页登录长桥并确认权限。PanWatch 使用 OAuth 授权码与 PKCE S256，仅请求 `account.read`。授权流程有效期为 10 分钟；超时或取消后可重新发起。
4. 返回后点击 **检测连接**。工具列表来自实际服务发现，并按 PanWatch 的查询白名单过滤；具体可用数据仍受长桥账户权限影响。
5. 开启 **供 AI 助手使用**。助手对话可以调用已发现的长桥查询工具；授权完成本身不会自动启用。

内置范围为 `quote`、`static_info`、`candlesticks`、`capital_flow`、`capital_distribution`、`account_balance`、`stock_positions`。交易、自选修改及自动化写入工具不会注册给助手，服务端也拒绝调用。当前仅接入交互式助手，不改变定时 Agent 或 TradingAgents 的行情数据源。

配置页采用左侧服务列表、右侧详情布局；官方图标直接引用[长桥品牌资源](https://open.longbridge.com/zh-CN/docs/assets)，外层使用固定黑色圆角背景，亮暗主题下保持一致。详情展示关联时间、服务端实际版本及查询工具的原始介绍。简介默认最多一行，溢出时显示“展开 / 收起”，短简介不显示折叠按钮。版本来自 MCP 初始化的 `serverInfo.version`，并非 MCP 协议版本或 PanWatch 版本。

授权账号优先显示 `邮箱(账号名)`，仅使用长桥签名授权信息实际提供的字段。若缺少邮箱，显示可用账号名或脱敏账户编号并提示缺失，不把 OAuth 客户端 ID 当作账号。当前长桥授权可能只有 JSON `sub` 内的 `account_no` / `member_id`，不提供邮箱与账号名。点击“检测连接”可刷新账号显示与服务版本，无需重新授权。新增关联从授权完成时记录时间；旧连接没有可靠的原始关联时间，显示“此前未记录”，不会以检测或刷新时间代替。

## 部署与凭证

- 非本机部署必须使用 HTTPS。本机开发允许 `localhost`、`127.0.0.1`、`::1` 的 HTTP 地址；保持从同一地址完成授权回调。反向代理应保留浏览器 `Origin`。
- 授权令牌仅在后端使用。数据库中的凭证及待完成授权信息通过 Fernet 加密；密钥保存在数据目录的 `mcp-credentials.key`，新建时权限为 `0600`。
- 迁移或备份时同时保留数据库与该密钥，按敏感数据保护二者。丢失密钥后需恢复原密钥，或断开连接并重新授权。密钥不会因读取失败而被自动替换。
- 令牌会在需要时刷新。用户在长桥撤销授权后，下一次刷新或调用若被拒绝，页面提示重新授权。
- 凭证不进入模型上下文；查询结果会进入当前助手对话及其已有持久化记录。
- **断开连接** 删除 PanWatch 当前保存的授权和待完成流程，并停止新的工具调用。要撤销长桥侧授权，需在长桥账户安全设置中移除；已经签发的访问令牌可能持续有效至过期。数据库历史备份和已有对话记录不会被该操作删除。

## English

Sign in to PanWatch, open **MCP**, choose a region and authorize on Longbridge in the same browser tab. Return, test discovery and explicitly enable assistant use. Only the seven read queries listed above are exposed. Scheduled agents and TradingAgents data sources are unchanged.

Remote deployments require HTTPS. Tokens are encrypted on the server, using `mcp-credentials.key` in the data directory. Preserve this key together with the database during backup or migration. Tokens never enter model context; query results enter the current assistant conversation. Disconnecting removes local credentials. Revoke the grant separately in Longbridge account security; existing access tokens may remain valid until expiration.

## References

- [Longbridge MCP overview](https://open.longbridge.com/zh-CN/docs/mcp)
- [Longbridge authorization](https://open.longbridge.com/zh-CN/docs/mcp/authorization)
- [Longbridge OAuth scopes](https://open.longbridge.com/zh-CN/docs/getting-started)
- [MCP lifecycle and version negotiation](https://modelcontextprotocol.io/specification/2025-11-25/basic/lifecycle)
