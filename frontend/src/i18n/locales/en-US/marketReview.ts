import type { TranslationShape } from '../../resource-types'
import type { marketReview as zh } from '../zh-CN/marketReview'
export const marketReview = {
  fiveMinute: 'Minute source unavailable; showing Tencent five-minute prices.',

  minuteMissing: 'Minute data unavailable; showing the latest turnover snapshot',
  method_etf_snapshot: 'Actual daily turnover snapshots for all 16 ETFs; minute sources unavailable.',

  baselineMissing: '20-day same-window baseline unavailable',
  reasonMissing: 'The source does not supply limit-up reasons. Industry labels are not reasons.',
  method_eastmoney_pool: 'Eastmoney pools; Sina daily validation with Tencent fallback. Grouped by industry. Promotions use yesterday’s pool. Some ST, STAR and new listings may be excluded.',
  method_etf_turnover: 'Incremental turnover of 16 broad-market ETFs in CNY 100m, aligned at common timestamps.',
  method_cffex_top20: 'CITIC client positions in CFFEX top-20 contract rankings. Net change = long change − short change.',
  method_lhb_disclosure: 'Named brokerage disclosures, without trader aliases. Institutions are deduplicated by stock, preferring daily disclosures.',
  method_calendar_stars: 'Today’s events rated at least two stars by Baidu Finance.',
  method_sector_etfs: 'Public ETFs represent sectors and themes (hover for symbols). These differ from Kanpanba baskets. Commodities use futures quotes.',

  review: 'Review', limit: 'Limit up', workspace: 'Workspace', previous: 'Previous trading day', next: 'Next trading day', latest: 'Latest trading day', date: 'Trading date', refresh: 'Refresh quotes',
  loading: 'Loading market data…', unavailable: 'Market data unavailable', retry: 'Retry', stale: 'Source update failed. Showing the last successful data.', source: 'Sources:', fetched: 'Fetched at', empty: 'No market data', noMatch: 'No matching stocks', partial: 'Some market data is unavailable',
  highest: 'Highest', boards: '{{count}} boards', stocks: '{{count}} stocks', families: '{{count}} stocks', sealed: 'Limit up', sealRate: 'Seal rate', opened: 'Broken seal', consecutive: 'Consecutive',
  history: 'Limit-up count over 10 days', most: '{{name}} leads with {{count}} stocks', ladder: 'Consecutive limit-up ladder', fullLadder: 'Full ladder', promotion: 'Promotion', first: 'First board', more: '{{count}} more', all: 'All',
  search: 'Search name, symbol or catalyst', clear: 'Clear search', share: 'Export image', sharing: 'Exporting…', shareError: 'Export failed. Please retry.', close: 'Close',
  allLimits: 'All limit-up stocks', wall: 'Overview', details: 'Details', view: 'Limit-up view', includeOpened: 'Include broken seals', onlySealed: 'Sealed only', onlyOpened: 'Broken seals only', status: 'Status', group: 'Industry',
  stock: 'Stock', price: 'Price', change: 'Change', board: 'Boards', firstSeal: 'First seal', lastSeal: 'Last seal', opens: 'Seal breaks', reason: 'Catalyst', amount: 'Turnover', turnover: 'Turnover rate', cap: 'Float cap', sealAmount: 'Sealed orders',
  oneWord: 'Locked limit', resealed: 'Resealed', fallen: 'Streak ended', waiting: 'Awaiting promotion', lhbBadge: 'LHB', lhbNet: 'LHB net buying', minute: 'Intraday chart', noLine: 'No intraday data', quoteAt: 'Quote time', themeAt: 'Theme date', stockDetail: 'Stock quote details',
  overseas: 'US sector & theme ETFs', allSectors: 'All sectors', regular: 'Close', extended: 'Extended / overnight', updated: 'Updated', topics: 'Leading industries',
  etf: 'Broad-market ETF minute turnover', etfTotal: '16 broad-market ETFs', peak: 'Peak volume', times: '{{value}}×', yi: '100M', wan: '10K', units: 'contracts', detail: 'Details',
  futures: 'CITIC Futures', netChange: 'Net long change', futuresHistory: '10-session net position changes', net: 'Net position', long: 'Long', short: 'Short',
  hotmoney: 'Brokerage net purchases', lhb: 'Dragon & tiger board', institution: 'Institutions', connect: 'Stock Connect', listed: 'Listed', calendar: 'Financial calendar',
  footer: 'For reference · Each module shows its disclosure date', external: 'View on source website',
  metric: '{{name}}: {{value}}', minuteValue: '{{time}} · {{value}} × 100M', signed: '{{value}}',
} as const satisfies TranslationShape<typeof zh>
