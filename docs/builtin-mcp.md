# Built-in MCP / 内置 MCP

PanWatch ships a fixed Longbridge connector. The account menu opens `/integrations/mcp`; the application's existing inbound `/mcp` endpoint remains separate. There is no marketplace, custom URL, package installer or local-command configuration.

## 使用步骤

1. 先登录 PanWatch，打开右上角菜单 → **MCP & 技能** → **MCP**。
2. 默认选择中国大陆节点 `https://mcp.longbridge.cn`；全球节点为 `https://mcp.longbridge.com`。
3. 点击 **前往长桥授权**，在同一浏览器标签页登录长桥并确认权限。PanWatch 使用 OAuth 授权码与 PKCE S256，仅请求 `account.read`。授权流程有效期为 10 分钟；超时或取消后可重新发起。
4. 返回后点击 **检测连接**。工具列表来自实际服务发现，并按 PanWatch 的查询白名单过滤；具体可用数据仍受长桥账户权限影响。
5. 开启 **供 AI 助手使用**。助手对话可以调用已发现的长桥查询工具；授权完成本身不会自动启用。

授权后可直接切换 **连接节点**，无需重新授权。目标节点检测通过后保存，并刷新版本与工具列表；失败时保留原节点。切换保留授权账号、关联时间和启用状态。MCP 请求使用所选节点，令牌续期仍使用原授权节点与客户端注册；授权尚未完成时暂不能切换。

内置范围为 `quote`、`static_info`、`candlesticks`、`capital_flow`、`capital_distribution`、`account_balance`、`stock_positions`。交易、自选修改及自动化写入工具不会注册给助手，服务端也拒绝调用。当前仅接入交互式助手，不改变定时 Agent 或 TradingAgents 的行情数据源。

配置页采用左侧服务列表、右侧详情布局；官方图标直接引用[长桥品牌资源](https://open.longbridge.com/zh-CN/docs/assets)，外层使用固定黑色圆角背景，亮暗主题下保持一致。详情展示关联时间、服务端实际版本及查询工具的原始介绍。简介默认最多一行，溢出时显示“展开 / 收起”，短简介不显示折叠按钮。版本来自 MCP 初始化的 `serverInfo.version`，并非 MCP 协议版本或 PanWatch 版本。

授权账号优先显示 `邮箱(账号名)`，仅使用长桥签名授权信息实际提供的字段。若缺少邮箱，显示可用账号名或脱敏账户编号并提示缺失，不把 OAuth 客户端 ID 当作账号。当前长桥授权可能只有 JSON `sub` 内的 `account_no` / `member_id`，不提供邮箱与账号名。点击“检测连接”可刷新账号显示与服务版本，无需重新授权。新增关联从授权完成时记录时间；旧连接没有可靠的原始关联时间，显示“此前未记录”，不会以检测或刷新时间代替。

## 内置技能

**MCP & 技能 → 技能** 内置长桥全部 **13 个技能**，沿用左右分栏。左侧按来源归并，仅展示一个长桥入口；右侧展示该来源包含的 13 个技能、支持状态和独立开关。点击技能展开详情，可查看适配版本、官方版本或来源提交、已适配与尚未支持的能力、分析流程、示例及官方原文。`/integrations/mcp?tab=skills&skill=longbridge-market-data` 可直接定位；刷新、浏览器返回保留选择。

| 状态 | 技能 | 本期适配范围 |
| --- | --- | --- |
| 部分支持 | 长桥总览、行情数据 | 报价、证券资料、K 线、资金流；总览可按需查询账户 |
| 部分支持 | 技术分析 | 基础 K 线、量价与趋势观察，不含专用指标和回测引擎 |
| 部分支持 | 基本面 | 证券资料与返回的每股指标，不含完整报表、DCF |
| 部分支持 | 账户与持仓 | 余额与股票持仓，不含交易、再平衡、基金持仓或账单 |
| 尚未支持 | 新闻与公告、市场情报、期权与窝轮、机构研究、财报分析、量化策略、价值投资、自选与提醒 | 官方内容可查看，所需数据或执行能力未接入，不可启用 |

官方完整来源固定在 [`longbridge/skills` 提交 `38900e9`](https://github.com/longbridge/skills/tree/38900e9884027782c1f4e480b451d5f55a479d95)，保留 MIT 许可。全部 13 份 `SKILL.md`、引用资料和脚本文本以 JSON 随应用发布；脚本仅作为静态原文保存，不落为可执行程序。请求时不下载安装包、不拉取远程指令、不执行官方安装命令。

长桥详情顶部的总开关可一次启用或停用当前已适配的五项技能，批量修改在同一事务保存；未支持的八项不受影响。独立开关继续生效，总开关根据单项状态显示全部启用、部分启用或全部停用。部分启用时，打开总开关可补齐全部，也可点击“全部停用”。该操作不自动授权或启用 MCP。

页面提供“为什么有未支持的技能？”说明：技能是流程指导，仍依赖数据接口或计算能力。PanWatch 尚未接入新闻、衍生品、完整财报、机构研究、量化计算、回测和自选提醒写入；授权与应用适配范围分别判断。

五项已适配技能各有独立开关，默认关闭，保存在 `AppSettings` 的 `builtin_skill.<id>.enabled`。启用不会自动授权或启用 MCP。助手仅在技能开启且 MCP 已授权、已检测、已启用，并存在相应实际工具时，通过 `load_builtin_skill` 读取 PanWatch 审阅适配版 `1.0.0` 的流程。原文包含的更广泛能力不代表已接入；适配版本与官方来源版本分开显示。工具发现仅返回部分查询时，页面标记缺失能力，仍可使用已满足依赖的部分。

技能读取与数据查询分别保留执行记录，技能指导不作为行情事实或证据展示。每次加载重新检查开关、授权和工具状态；停用阻止后续加载，不撤回已进入对话的指导，也不删除 MCP 授权。当前仅用于交互式助手。

## 部署与凭证

- 非本机部署必须使用 HTTPS。本机开发允许 `localhost`、`127.0.0.1`、`::1` 的 HTTP 地址；保持从同一地址完成授权回调。反向代理应保留浏览器 `Origin`。
- 授权令牌仅在后端使用。数据库中的凭证及待完成授权信息通过 Fernet 加密；密钥保存在数据目录的 `mcp-credentials.key`，新建时权限为 `0600`。
- 迁移或备份时同时保留数据库与该密钥，按敏感数据保护二者。丢失密钥后需恢复原密钥，或断开连接并重新授权。密钥不会因读取失败而被自动替换。
- 令牌会在需要时刷新。用户在长桥撤销授权后，下一次刷新或调用若被拒绝，页面提示重新授权。
- 凭证不进入模型上下文；查询结果会进入当前助手对话及其已有持久化记录。
- **断开连接** 删除 PanWatch 当前保存的授权和待完成流程，并停止新的工具调用。要撤销长桥侧授权，需在长桥账户安全设置中移除；已经签发的访问令牌可能持续有效至过期。数据库历史备份和已有对话记录不会被该操作删除。

## English

Sign in to PanWatch, open **MCP & Skills → MCP**, choose a region and authorize on Longbridge in the same browser tab. Return, test discovery and explicitly enable assistant use. Only the seven read queries listed above are exposed. Scheduled agents and TradingAgents data sources are unchanged.

The **Skills** tab bundles official source files and references for all 13 Longbridge skills. Five skills (overview, market data, basic technical analysis, basic fundamentals and account/portfolio queries) are partially adapted for the current MCP tools. The other eight remain viewable but cannot be enabled. Each supported skill has an independent switch, off by default, and reuses existing MCP authorization. The assistant loads reviewed guidance through `load_builtin_skill`; source scripts remain inert text. Guidance is recorded in the tool audit trail but excluded from market facts and evidence. Adaptation versions and pinned official source versions are displayed separately.

After authorization, switching the connection node preserves the grant, account, original connection time and enabled state. The target is tested before saving; a failed test keeps the previous node. MCP calls use the selected node while token renewal stays with the original OAuth issuer and client registration.

Remote deployments require HTTPS. Tokens are encrypted on the server, using `mcp-credentials.key` in the data directory. Preserve this key together with the database during backup or migration. Tokens never enter model context; query results enter the current assistant conversation. Disconnecting removes local credentials. Revoke the grant separately in Longbridge account security; existing access tokens may remain valid until expiration.

## References

- [Longbridge official skills](https://open.longbridge.com/zh-CN/skill)
- [Longbridge MCP overview](https://open.longbridge.com/zh-CN/docs/mcp)
- [Longbridge authorization](https://open.longbridge.com/zh-CN/docs/mcp/authorization)
- [Longbridge OAuth scopes](https://open.longbridge.com/zh-CN/docs/getting-started)
- [MCP lifecycle and version negotiation](https://modelcontextprotocol.io/specification/2025-11-25/basic/lifecycle)
