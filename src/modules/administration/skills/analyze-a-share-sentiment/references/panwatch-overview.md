# PanWatch 总览契约

存在 `validate_overview` 时按本契约执行；在 Codex 或普通助手中无此工具时直接输出符合文末 JSON Schema 的分析对象，并单独提供实际计算数据与时间口径，不调用不存在的宿主工具。

总览使用宿主传入的 `get_market_facts`，其行情来自长桥 MCP；不得借用模型记忆补造数值。先 `load_builtin_skill`，读取事实后，通过 `validate_overview` 返回 schema 约束的 JSON。Codex 独立使用时可调用对应长桥 MCP 工具，遵循相同口径。禁止读取账户余额、持仓或交易记录用于市场情绪分析。

## 时间与输出归属

- 宿主以长桥 `trading_days` 和各条 `quote.timestamp` 确认最新有行情的交易日，保留采集时间。盘中数据是暂定观察，不是收盘结果。筛选器没有逐行时间戳，只用于枚举目录；涨跌指标必须从同日有效报价计算。
- 主板、创业板、科创板、北交所分别报告覆盖；未返回的板块不填零。股票总数是长桥返回目录，不声称覆盖所有上市股票。
- 行情数值、指数、来源、覆盖、缓存时效由宿主提供；模型返回判断字段，不重复生成数字卡片。
- 页面使用当前总览，不提供分析版本选择。后台可保存运行证据；旧结果过期时必须显示其真实日期和更新状态。

## 模型字段

`title`、`summary`、`direction`、`direction_reason`；`loss_relief` 与 `profit_diffusion` 分别包含 `state`、`explanation`、`evidence_ids`。方向枚举为 `improving/stable/deteriorating/mixed/insufficient`。无历史可比数据时不能把静态弱势说成“正在恶化”，两轴使用 `insufficient` 并说明当前水平。

`stage` 包含 `kind`、`stages`、`status`、`rationale`、`evidence_ids`。阶段顺序为：

| 枚举 | 展示名称 |
|---|---|
| ice | 低迷/冰点 |
| repair | 修复 |
| expansion | 发酵/扩张 |
| heat | 高热 |
| divergence | 分歧 |
| retreat | 退潮 |

- `kind=stage`：`stages` 恰好一个枚举。仍须标明 `candidate/supported/conflicted`，位置不是精确测量。
- `kind=between`：两个相邻阶段，按上表顺序排列；允许 `retreat → ice`。表示阶段边界未确认，不代表 50% 进度或两者概率相等。
- `kind=unknown`：空数组，`status=insufficient`。无法缩小到相邻阶段、证据明显不足时不强行落点。
- 曲线仅解释阶段关系，不是指数、历史温度或未来行情路径；阶段可以跳转、反复。不得生成坐标、进度百分比、情绪总分或阶段胜率。

`groups` 恰好包含 G/A/P/R 各一个，每组有 `status=observed/proxy/missing/conflicted`、解释及证据引用。`supports`、`counters` 必须引用给定证据；`next_checks` 给出观察时段、观察对象、加强和推翻判断的条件。`limitations` 明确重要缺口。

## 当前长桥口径与待验证参数

- G/R：从同日可用股票报价计算涨跌家数、涨幅中位数、10/90分位。分位及有效分母由程序提供。
- A：在真实涨停限价和完整事件池缺失时，仅提供强势股比例代理。主板5%、创业/科创10%、北交所15%为**未回测的观察阈值**，不是涨停、晋级或交易信号；不得声称已经得到1.0实证验证。
- P：使用此前交易日收盘后冻结的强势队列及其后续报价；首次运行、队列未成熟、报价不齐时缺失或部分可用。不是昨日涨停溢价，也不能当作可成交收益。
- 长桥 `market_temperature` 和历史温度是供应商综合指标；只作背景，不按温度区间直接映射六阶段，也不视为G/A/P/R合成分数。
- 分页目录与报价非原子采样，记录采集窗口、重复及缺失；不完整时收缩判断。筛选器金额字段的原始值与单位可能不一致，不据此汇总成交额。
- 没有完整A/P、跨日比较或足够分板块覆盖时，阶段至多为候选/冲突，不输出 `supported`。缺口本身是数据质量证据，可作为反证引用。

研究依据仍见 [参数与依据](parameters-and-evidence.md) 与 [首轮实证](study-2026-11.md)；这些结论不证明当前长桥代理指标的预测能力。

机器可读的分析字段定义见 [overview.schema.json](overview.schema.json)。宿主负责附加行情卡片、覆盖、来源、数据时点和更新状态；这些数值不得由模型重写。
