# Regulatory windows and trading-day validation (V3)

PanWatch preserves the Agent's plan, source observations, regulatory event versions,
postmarket review and next-session memory as separate records. The host computes
rule windows and acceptance checkpoints; an Agent cannot declare its own checks
passed. No orders are placed by this workflow.

## Rule and source boundaries

The supported rule version is effective 2026-07-06:

- [SSE Trading Rules (2026)](https://www.sse.com.cn/lawandrules/sselawsrules2025/trade/universal/c/c_20260424_10816492.shtml): sections 5.4.2–5.4.3 and STAR 6.10–6.12.
- [SZSE Trading Rules (2026)](https://docs.static.szse.cn/www/lawrules/rule/trade/W020260424690713155663.pdf): sections 4.5.6, 5.4.3–5.4.5.
- [SSE public trading information](https://www.sse.com.cn/disclosure/diclosure/public/inquirydata/index.shtml) and [SZSE public trading information](https://www.szse.cn/disclosure/deal/public/): exchange publication dates and event periods. The adapters retain the original response and each event's source hash. SSE main-board, SZSE and STAR-specific records are integrated. STAR uses its own reason codes (ordinary 5/6, severe 7–12), list pagination and mandatory detail-period verification; daily price, amplitude, turnover and financing entries do not reset price-abnormality windows.
- Issuer originals come from CNInfo, with issuer identity, document hash, first observation time and excerpts. A company announcement is not silently converted into an exchange publication.

Ordinary price deviation uses every suffix of up to three eligible sessions with
±20% thresholds on the main board and ±30% on ChiNext/STAR. Severe price deviation
uses every suffix up to 10 sessions (+100%/−50%) and 30 sessions (+200%/−70%).
The same-direction repeat count uses independent disclosed ordinary events in ten
sessions: four on the main board, three on ChiNext/STAR. Daily trading-publication
entries for amplitude, turnover or a daily price move are not counted as ordinary
price-abnormality events. Turnover abnormality and discretionary exchange findings
are outside these numeric price windows.

Ordinary and severe events have independent reset histories. Exchange records take
priority over matching issuer events. Explicitly scoped investigation resumption
has its own source-linked anchor; an unrelated restructuring resumption does not
reset a regulatory window. First knowledge is append-only; source versions and
conflicting corrections remain auditable. Unresolved corrections, unknown dates,
missing trading sessions and incomplete source searches prevent a clean calculation.
A calendar-inconsistent issuer period can be reconciled only to a uniquely matched exchange record with the same event kind, end date and direction. The original claim, official period and source hashes remain visible; no date is repaired by guessing. A disclosed future or open-ended suspension is a trading constraint, not a missing historical source. No resumption date is invented.

Scanned supporting replies can use bounded local Apple Vision OCR on macOS with the installed Swift compiler. Executable/module caches and temporary PDFs stay under `DATA_DIR/document_ocr`; no documents leave the machine for OCR. Up to eight pages are recognized; low-confidence lines are omitted and their positions recorded. The original PDF hash and extraction method remain auditable. Supporting shareholder replies cannot create issuer events, and OCR-derived event notices require independent corroboration. Unsupported platforms retain an explicit OCR capability gap; required event coverage is separated from supporting-attachment readability.

The run freezes regulatory memory before analysis, and later discoveries do not
rewrite an earlier publication.

The numerator is the adjusted stock period return minus the benchmark period
return, not a sum of daily deviations. Benchmarks are SSE A Share Index, Shenzhen A
Share Index, ChiNext Composite and STAR 50 respectively. Provider forward-adjusted
closes remain a disclosed data convention, not official exchange calculation output.
Each result retains all candidate periods and price inputs for reproduction.

Special sessions use the confirmed exchange calendar, including holiday closures
and working weekends that remain closed. First five IPO sessions, the first
relisting session and explicitly disclosed no-limit sessions are excluded. SZSE's
entire delisting period is excluded; SSE's no-limit first delisting session is
excluded without importing Shenzhen's different rule. Suspensions require paired
disclosures; ex-right dates require adjusted history. Missing special-event coverage
is not repaired by guessing from price moves. Searches cover 100 calendar days,
up to 90 issuer announcements, 32 critical original documents per symbol and 80
price sessions; limits and incomplete searches are published in the evidence.

Numbers crossing a threshold do not establish an exchange determination. A verified
reset history does not prove that special monitoring has ended. No feed currently
provides a complete, authoritative stock-level monitoring-clearance verdict.

## Monday 2026-11-16 verification

Open **情绪作战台 → 交易日验证**, select 2026-11-16 and enable it before 09:10 that day. This persists a
service-owned workflow through the next confirmed session, 2026-11-17. Keep the
service and network available. The auction interface can stay disabled: the
checkpoint shows **skipped / not configured**, and no indicative auction prices,
matched volumes or unmatched volumes are synthesized from ordinary quotes.

| Shanghai time | Scheduled action / evidence |
| --- | --- |
| Before Monday 08:45 | Check service heartbeat, configured model, calendar and source-gap warnings. |
| Monday 08:45 | Generate a fresh plan via the normal Agent runtime; freeze the publication and activate monitoring. Failed/interrupted generation has at most two attempts before the premarket scheduling cutoff. |
| Monday 09:15 | Require the scheduled plan to have published before the deadline; require Friday 11-13 market reference and complete market coverage. A weekend rehearsal alone does not satisfy this checkpoint. |
| 09:15–09:25 | Licensed auction checkpoint. Disabled configuration remains explicitly skipped. |
| 09:30–10:00 | Verify source timestamps, watched-symbol coverage and opening conditions. |
| 10:00–11:30 | Validate morning sampling coverage; the lunch break is not a data outage. |
| 13:00–14:57 | Validate afternoon sampling coverage and invalidation conditions. |
| 15:00–15:05 | Require at least one same-day final closing quote. Repeated final snapshots do not inflate coverage. |
| 15:10, deadline 15:20 | Generate and persist a review from the original plan and its actual observations. Late catch-up is retained but fails the timeliness check. Failed/interrupted review can retry once. |
| Tuesday 08:45, deadline 09:15 | Generate a new plan that explicitly includes Monday's review ID in its frozen memory input. |
| Tuesday 09:30–10:00 | Validate next-session opening coverage on Monday's continuing observation record. |
| After Tuesday 10:01 | Preserve the final checkpoint snapshot and stop this validation workflow. |

Sampling requires at least 80% of requested symbols with fresh, positive quotes and
80% of the expected source-timestamp-distinct observations. Maximum gap is the
larger of 90 seconds and three armed sampling intervals. The interval is frozen
when enabled; later settings changes are shown as warnings. Missing, stale,
wrong-day, future or repeated source timestamps cannot manufacture a pass. Each
checkpoint transition is persisted. Reads do not start models or upstream requests.
An in-progress day's windows remain running/pending until their deadlines.

The validation page stays on the armed trading day when the workspace's default
plan date advances. Refresh and process restart preserve state. The workflow owns scheduled analysis and review on its two dates, so general schedules cannot create competing runs. The next-memory checkpoint is bound to its own scheduled publication; later manual versions cannot replace that evidence. Scheduler operations are isolated so one failing operation cannot suppress later monitoring checks. Pausing validation
stops its future scheduling; already running model/monitor tasks have their own
stop controls. An existing explicitly paused monitor is not silently restarted.

The exported JSON distinguishes `configured_stages_verified` from
`natural_session_verified`. With auction disabled, the latter cannot become true.
Controlled-clock tests prove orchestration and guards; actual Monday/Tuesday market
acceptance must be assessed from the persisted future observations.

## Failure handling

- Market collection is bounded to 225 seconds, covering its sequential source
  budgets plus headroom. Original-document and adjusted-price verification has a
  separate 240-second limit for cold PDF/OCR reads. Both stages are recorded; a
  timeout identifies the failed stage and preserves the last publication.
- A missing heartbeat or a source-time gap marks the affected checkpoint failed.
  Restarting the service resumes persisted work without filling missed samples.
- Missing premarket, review or memory deadlines remain failures even if a later
  recovery produces useful artifacts. Earlier published plans remain unchanged.
- Source fetch/schema failures appear in regulatory coverage; an empty search never
  clears monitoring. Conflicting disclosure versions require reconciliation rather
  than a new guessed anchor.
- No automatic trading, notifications, API purchases or auction credentials are
  part of this feature. The service reuses the locally configured model and sources.

### 价格复权依据与缺口

情绪策略的日线优先使用腾讯显式 `qfqday` 字段并留存请求和响应指纹。仅有 `day` 时，不根据请求中包含 `qfq` 就认定已复权：重新请求未复权日线，核对标的及日期集合，再按新浪 `qfq.js` 的有日期前复权因子计算 `价格 / 因子`。指数日线不套用个股复权因子。

原始响应、因子全文和逐日原价/因子/调整价保存在本次分析档案；页面展示采用的提供商口径、覆盖范围，审计证据包含逐日计算。Agent 只接收摘要及原始指纹，避免大表挤占上下文。该口径不是交易所认证的监管价格。

因子标的不匹配、条数不完整、非法值、重复或未来日期、未覆盖基期、原始日线日期冲突均保留缺口；正式监管窗口与滚动参考都不得输出数值。不存在因子变化时仍须有实际来源证明，不能用“新股应该没有分红”代替核验。原有冻结版本保持不变，新分析才使用新增来源。
