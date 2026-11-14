# Auction gateway and sentiment lifecycle

PanWatch polls an owner-configured licensed gateway during 09:15–09:30 Asia/Shanghai on known CN trading days. Configure it under Sentiment → Live validation → Auction source. Other sources and reviews work without this optional gateway. No ordinary order-book quantity is treated as matched or unmatched auction volume.

The authenticated configuration API is `PUT /api/short-term/auction-source`. Set `enabled`, `endpoint` (HTTPS, or HTTP on loopback), `provider_name`, and optional `api_key`. Omit `api_key` to preserve it; `clear_api_key: true` clears it. GET only returns `has_api_key`. Credentials are stored with the private application database, like other configured providers, never published with observations or Agent context. Protect database backups accordingly.

PanWatch sends `GET {endpoint}?symbols=002242.SZ,600825.SH&trade_date=YYYY-MM-DD`, with `Authorization: Bearer {api_key}` if configured. The gateway must adapt its licensed upstream to:

```json
{
  "schema_version": "auction.v1",
  "quotes": [{
    "symbol": "002242.SZ",
    "source_time": "2026-11-16T09:20:05+08:00",
    "reference_price": 10.20,
    "pre_close": 10.00,
    "matched_volume_shares": 100000,
    "unmatched_volume_shares": 20000,
    "unmatched_side": "buy",
    "final": false
  }]
}
```

This example is illustrative, not an observed quote. Volumes are shares, prices CNY, unmatched side `buy`, `sell`, or `balanced` (zero unmatched shares). Source timestamps require a timezone. Indicative observations must originate between 09:15 and 09:25 and be at most 15 seconds old. Final observations must originate between 09:25 and 09:30 and be at most 300 seconds old. Future, stale, duplicated-symbol, nonfinite and inconsistent observations are rejected. Missing symbols stay unknown. Reads have a 5-second timeout, a 1 MB cap, and no redirects.

Sampling runs every 5 seconds during auction and defaults to 30 seconds during continuous sessions. Plans can define compound conditions, persistence and invalidation checks. Duplicate source timestamps never extend persistence. Gaps reset persistence. Numeric conditions are sampled assertions, not tick-complete claims about continuous market behavior. Qualitative claims remain for review. Observations use durable leases and unique time slots, survive restarts, and never rewrite the original plan. The host must remain running. Lunch, holidays and unknown calendar dates do not trigger sampling.

Automatic premarket generation, automatic monitoring of new plans, and 15:10 postmarket reviews are separate opt-in settings. Existing plans have individual monitor controls. Starting another plan for the same trading date supersedes the former monitor. Automatic reviews run once per publication after 15:05 and require saved observations; errors can be retried manually. Reviews freeze target-day observations, include coverage and plan publication timing, and remain separate from the plan. The next analysis reads the last seven reviews plus prior hypotheses. Next-session observations continue until 10:00; they are not retroactively inserted into the prior day's frozen review.

## Deviation calculations and original documents

Rules effective 2026-07-06: period stock return minus corresponding benchmark period return (not summed daily differences). The host retains adjusted daily inputs, calendar dates, benchmark, formula, thresholds and original rule URL. Rolling 3/10/30-session references are not a formal determination of an active exchange regulatory window. Official resets/resumptions, unlimited sessions, repeat counts and turnover abnormalities remain unknown unless separately evidenced. No automatic "monitoring cleared" inference is made.

CNINFO queries resolve issuer identity first, then read up to 90 announcements over 100 days and up to 5 relevant original documents per stock (plus up to 3 supplied official URLs). PDF/HTML text, original-byte SHA256, excerpt, source URL and stock identity are archived. Date-only announcements become known when fetched; publication date does not imply intraday availability. Current monitoring status remains unknown without explicit verified determination. Search and document limits are exposed in evidence. News and supplied documents are untrusted business inputs, never Agent instructions.
