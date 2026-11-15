import type { TranslationShape } from '../../resource-types'
import { etf as zhEtf } from '../zh-CN/etf'
export const etf = {
  title: 'Broad-market ETFs', overview: 'Overview', national: 'State investor tracking', previous: 'Previous trading day', next: 'Next trading day', date: 'Trading day', latest: 'Latest trading day', refresh: 'Refresh quotes',
  closed: 'Closed', trading: 'Trading', published: 'Shares published', pending: 'Shares pending', stale: 'Updating quotes',
  minute: 'Minute turnover', basket: '{{count}} broad-market ETFs', total: 'Daily turnover', more: '{{value}}% above average', less: '{{value}}% below average',
  quiet: 'No unusual volume', loud: 'Elevated turnover', quietDetail: 'Cumulative turnover below the historical average', loudDetail: 'Cumulative turnover above the historical average',
  baselinePending: 'Historical baseline pending', excess: 'Above average', baseline: 'Typical minute', auction: 'Closing auction',
  halfHour: 'Half-hour turnover', times: '{{value}}×', baselineDays: '{{count}}-day period average', amountUnit: '×100M CNY', sharesUnit: '×100M units',
  details: '{{count}} ETFs', detailsHint: 'Turnover · Change · Relative volume', shares: 'Shares & subscriptions',
  index: 'Index', fund: 'ETF', change: 'Change', turnover: 'Turnover', peak: 'Peak interval', ratio: 'Relative volume', units: 'Unit change', net: 'Est. net subscriptions', size: 'Assets',
  net20: '20-day net subscriptions', net60: '60-day net subscriptions', maxIn: 'Largest subscription', maxOut: 'Largest redemption', inflow: 'Subscriptions', outflow: 'Redemptions', hs300: 'CSI 300', surge: 'Volume surge', flowDays: 'Elevated turnover days',
  loading: 'Loading quotes', unavailable: 'Quotes unavailable', retry: 'Retry', empty: 'No quotes',
  disclosed: 'Disclosed holdings', institutions: 'Institutions', heldFunds: 'ETFs held', watchFlow: 'Est. subscriptions in held ETFs', signals: 'Countertrend subscriptions',
  all: 'All institutions', huijin: 'Central Huijin', csf: 'China Securities Finance', guoxin: 'Guoxin', chengtong: 'Chengtong',
  holder: 'Holder', reportDate: 'Reporting date', heldShares: 'Units held', heldRatio: 'Ownership', heldDelta: 'Change in units',
  noHoldings: 'No disclosed holdings', noSignals: 'No countertrend subscription signals', watchlist: 'Flows in held ETFs',
  countertrend: 'Countertrend subscription', period: 'Reporting period', coverage: '{{count}} ETFs disclosed', history: 'Subscription history',
} as const satisfies TranslationShape<typeof zhEtf>
