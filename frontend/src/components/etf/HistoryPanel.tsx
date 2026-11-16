import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { RefreshCw } from 'lucide-react'
import { Button } from '@panwatch/base-ui/components/ui/button'
import { Input } from '@panwatch/base-ui/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@panwatch/base-ui/components/ui/select'
import { etfApi, type EtfHistory, type EtfPeriod } from '@panwatch/api/etf'
import { marketSignTextClass } from '@/lib/market-colors'
import { numeric, signed } from './charts'
import { TrendChart } from './TrendChart'
import { MarketComparisonChart } from './MarketComparisonChart'
import { useEtf } from './useEtf'

const periods: EtfPeriod[] = ['1m', '3m', '6m', '1y', 'all', 'custom']
const periodLabels = { '1m': 'range_1m', '3m': 'range_3m', '6m': 'range_6m', '1y': 'range_1y', all: 'range_all', custom: 'range_custom' } as const
const institutions = ['huijin', 'csf', 'guoxin', 'chengtong'] as const

function HistoryPlots({ data, national, onDate }: { data: EtfHistory; national: boolean; onDate: (date: string) => void }) {
  const { t } = useTranslation('etf')
  const series = data.series
  const money = t('amountUnit')
  const cumulativeLabel = t(data.summary.net_days < data.summary.days ? 'knownCumulativeNet' : 'cumulativeNet')
  return <div className="etf-history-content">
    <div className="etf-history-stats">{([
      ['periodNet', data.summary.net, data.summary.net_days], ['periodIn', data.summary.inflow, data.summary.net_days],
      ['periodOut', data.summary.outflow, data.summary.net_days], ['periodAmount', data.summary.amount, data.summary.amount_days],
    ] as const).map(([key, value, count]) => <div className="etf-card" key={key}><span>{t(key)}</span><b className={key === 'periodAmount' ? '' : marketSignTextClass(value)}>{key === 'periodAmount' ? numeric(value, 0) : signed(value, 0)}<small>{money}</small></b>{count < data.summary.days && <span>{t('knownTotal', { count, total: data.summary.days })}</span>}</div>)}</div>
    {national ? <section className="etf-card"><div className="etf-panel-heading"><h2>{t('heldEtfTrend')}</h2><span>{t('historyCoverage', { count: data.summary.days })}</span></div>
      <TrendChart points={series.map(p => ({ date: p.date, value: p.net, secondary: p.hs300, detail: t('pointCoverage', { count: p.covered, total: p.expected }) }))} label={t('net')} unit={money} secondaryLabel={t('hs300')} bars market onDate={onDate} />
    </section> : <MarketComparisonChart data={data} onDate={onDate} />}
    {national && <div className="etf-history-grid">
      <section className="etf-card"><h2>{cumulativeLabel}</h2><TrendChart points={series.map((p, i) => ({ date: p.date, value: p.cumulative_net, detail: p.cumulative_net_days < i + 1 ? t('knownTotal', { count: p.cumulative_net_days, total: i + 1 }) : undefined }))} label={cumulativeLabel} unit={money} market onDate={onDate} /></section>
      <section className="etf-card"><h2>{t('turnoverTrend')}</h2><TrendChart points={series.map((p) => ({ date: p.date, value: p.amount }))} label={t('turnover')} unit={money} bars onDate={onDate} /></section>
    </div>}
    {national && <section className="etf-card"><div className="etf-panel-heading"><h2>{t('holdingsTrend')}</h2><span>{t('reportPoints', { count: data.holdings_trend.length })}</span></div>
      {data.holdings_trend.length ? <><TrendChart points={data.holdings_trend.map(p => ({ date: p.date, value: p.shares }))} label={t('heldShares')} unit={t('sharesUnit')} />
        <div className="etf-report-periods">{data.holdings_trend.map(p => <div key={p.date}><b>{p.date}</b>{p.before_range && <span>{t('beforeRange')}</span>}<span>{t('reportCoverage', { count: p.reported_funds, total: p.expected_funds })}</span><span>{t('heldShares')} {numeric(p.reported_shares, 2)} {t('sharesUnit')}</span></div>)}</div></> : <p className="etf-empty">{t('noHoldings')}</p>}
    </section>}
    <section className="etf-card"><div className="etf-panel-heading"><h2>{t('intervalFunds')}</h2><span>{t('basket', { count: data.summary.funds })}</span></div>
      <div className="scrollbar overflow-x-auto"><table><thead><tr><th>{t('fund')}</th><th>{t('index')}</th><th>{t('periodNet')}</th><th>{t('periodAmount')}</th><th>{t('size')}</th><th>{t('dataCoverage')}</th></tr></thead>
        <tbody>{data.funds.map(row => <tr key={row.code}><td><strong>{row.name}</strong><small>{row.code}</small></td><td>{row.index}</td><td className={marketSignTextClass(row.net)}>{signed(row.net)}{money}</td><td>{numeric(row.amount)}{money}</td><td>{numeric(row.scale)}{money}</td><td><div>{t('flowCoverageDays', { count: row.days, total: row.expected_days })}</div><div>{t('amountCoverageDays', { count: row.amount_days, total: row.expected_days })}</div></td></tr>)}</tbody></table></div>
      {!data.funds.length && <p className="etf-empty">{t(national ? 'noHoldings' : 'noHistory')}</p>}
    </section>
    {national && <details className="etf-card etf-fold"><summary>{t('holdingsRecords')}</summary><div className="etf-fold-body scrollbar overflow-x-auto"><table><thead><tr><th>{t('reportDate')}</th><th>{t('holder')}</th><th>{t('fund')}</th><th>{t('heldShares')}</th><th>{t('heldRatio')}</th><th>{t('heldDelta')}</th></tr></thead>
      <tbody>{data.disclosures.map(row => <tr key={`${row.report_date}:${row.code}:${row.holder_name}`}><td>{row.report_date}</td><td>{row.holder_name}</td><td>{row.name}<small>{row.code}</small></td><td>{numeric(row.shares / 1e8, 2)}{t('sharesUnit')}</td><td>{numeric(row.ratio_percent, 2)}%</td><td className={marketSignTextClass(row.shares_change)}>{signed(row.shares_change == null ? null : row.shares_change / 1e8, 2)}</td></tr>)}</tbody></table>{!data.disclosures.length && <p className="etf-empty">{t('noHoldings')}</p>}</div></details>}
    <section className="etf-card"><h2>{t('signals')}</h2>{data.signals.length ? <div className="etf-surge-list">{[...data.signals].reverse().map(point => <button key={point.date} type="button" onClick={() => onDate(point.date)}><b>{point.date}</b><span>{t('countertrend')}<small>{t('hs300')} <em className={marketSignTextClass(point.hs300_change_percent)}>{signed(point.hs300_change_percent, 2)}%</em> · {t('times', { value: numeric(point.peak_ratio) })}</small></span><span className={marketSignTextClass(point.net)}>{signed(point.net)} {money}<small>{t('net')}</small></span></button>)}</div> : <p className="etf-empty">{t('noSignals')}</p>}</section>
  </div>
}

export function EtfHistoryPanel({ national = false, refresh, onDate }: { national?: boolean; refresh: number; onDate: (date: string) => void }) {
  const { t } = useTranslation('etf')
  const [params, setParams] = useSearchParams()
  const rawPeriod = params.get('period') as EtfPeriod
  const period: EtfPeriod = periods.includes(rawPeriod) ? rawPeriod : '3m'
  const code = params.get('code') || ''
  const institution = national ? params.get('institution') || '' : ''
  const start = params.get('start') || '', end = params.get('end') || ''
  const [draft, setDraft] = useState({ start, end })
  useEffect(() => { setDraft({ start, end }) }, [start, end])
  const [invalid, setInvalid] = useState(false)
  const [retry, setRetry] = useState(0)
  const query = { period, scope: national ? 'national' as const : 'market' as const, code, institution,
    start: period === 'custom' ? start : '', end: period === 'custom' ? end : '' }
  const valid = period !== 'custom' || Boolean(start && end && start <= end)
  const key = JSON.stringify(query)
  const state = useEtf(key, signal => etfApi.history(query, signal), valid, refresh + retry, data => data.collecting ? 3000 : 60000)
  const data = state.data
  const change = (values: Record<string, string>) => setParams(previous => {
    const next = new URLSearchParams(previous)
    Object.entries(values).forEach(([name, value]) => value ? next.set(name, value) : next.delete(name))
    return next
  })
  const choosePeriod = (value: EtfPeriod) => {
    setInvalid(false)
    if (value === 'custom') {
      const range = data?.range ?? { start, end }
      setDraft(range); change({ period: value, ...range })
    } else change({ period: value, start: '', end: '' })
  }
  const apply = () => {
    if (!draft.start || !draft.end || draft.start > draft.end) { setInvalid(true); return }
    setInvalid(false); change({ period: 'custom', ...draft })
  }
  return <>
    <div className="etf-history-controls"><div role="group" aria-label={t('range')} className="etf-range-buttons">{periods.map(value => <Button key={value} size="sm" variant={period === value ? 'default' : 'ghost'} aria-pressed={period === value} onClick={() => choosePeriod(value)}>{t(periodLabels[value])}</Button>)}</div>
      <div className="etf-history-filters"><Select value={code || 'all'} onValueChange={value => change({ code: value === 'all' ? '' : value })}><SelectTrigger aria-label={t('fund')} className="h-9 w-56"><SelectValue placeholder={t('allFunds')} /></SelectTrigger><SelectContent><SelectItem value="all">{t('allFunds')}</SelectItem>{data?.universe.map(row => <SelectItem key={row.code} value={row.code}>{row.name} {row.code}</SelectItem>)}</SelectContent></Select>
        {national && <Select value={institution || 'all'} onValueChange={value => change({ institution: value === 'all' ? '' : value })}><SelectTrigger aria-label={t('institutions')} className="h-9 w-40"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="all">{t('all')}</SelectItem>{institutions.map(value => <SelectItem key={value} value={value}>{t(value)}</SelectItem>)}</SelectContent></Select>}</div>
    </div>
    {period === 'custom' && <form className="etf-custom-range" onSubmit={event => { event.preventDefault(); apply() }}><label>{t('startDate')}<Input type="date" aria-label={t('startDate')} value={draft.start} onChange={event => setDraft({ ...draft, start: event.target.value })} /></label><span>—</span><label>{t('endDate')}<Input type="date" aria-label={t('endDate')} value={draft.end} onChange={event => setDraft({ ...draft, end: event.target.value })} /></label><Button type="submit" size="sm">{t('applyRange')}</Button></form>}
    {(invalid || !valid) && <p className="etf-error" role="alert">{t('invalidRange')}</p>}
    {state.loading && valid && !data && <div className="etf-card etf-empty" role="status"><RefreshCw className="animate-spin" size={20} />{t('loading')}</div>}
    {state.error && <div className="etf-error" role="alert">{t('unavailable')}<Button size="sm" variant="ghost" onClick={() => setRetry(value => value + 1)}>{t('retry')}</Button></div>}
    {data && <><div className="etf-history-caption"><span>{data.range.start} — {data.range.end}</span><span>{data.collecting ? t('collectingHistory', { loaded: data.summary.loaded_days, total: data.summary.days }) : t('observedDays', { loaded: data.summary.net_days, total: data.summary.days })}{data.stale && ` · ${t('stale')}`}</span><span>{t('fundCoverage', { min: data.summary.coverage_min, max: data.summary.coverage_max, total: data.summary.funds })}</span></div><HistoryPlots key={key} data={data} national={national} onDate={onDate} /></>}
  </>
}
