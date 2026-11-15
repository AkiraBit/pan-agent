import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { ChevronDown, ChevronLeft, ChevronRight, RefreshCw } from 'lucide-react'
import { Button } from '@panwatch/base-ui/components/ui/button'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@panwatch/base-ui/components/ui/select'
import { Tabs, TabsList, TabsTrigger } from '@panwatch/base-ui/components/ui/tabs'
import { etfApi, type EtfBoard, type EtfNationalTeam, type EtfRow } from '@panwatch/api/etf'
import { marketSignTextClass } from '@/lib/market-colors'
import { FlowChart, MinuteChart, numeric, signed } from '@/components/etf/charts'
import '@/components/etf/etf.css'

function useEtf<T>(key: string, loader: (signal: AbortSignal) => Promise<T>, enabled: boolean, refresh: number) {
  const [state, setState] = useState<{ key: string; data?: T; error?: boolean; loading: boolean }>({ key: '', loading: true })
  useEffect(() => {
    if (!enabled) return
    const controller = new AbortController()
    let timer: ReturnType<typeof setTimeout>
    const load = async () => {
      setState(previous => ({ key, data: previous.key === key ? previous.data : undefined, loading: !previous.data || previous.key !== key }))
      try {
        const data = await loader(controller.signal)
        if (!controller.signal.aborted) setState({ key, data, loading: false })
      } catch {
        if (!controller.signal.aborted) setState(previous => ({ key, data: previous.key === key ? previous.data : undefined, error: true, loading: false }))
      } finally {
        if (!controller.signal.aborted) timer = setTimeout(() => { if (!document.hidden) void load(); else timer = setTimeout(load, 60000) }, 60000)
      }
    }
    void load()
    return () => { controller.abort(); clearTimeout(timer) }
    // loader is bound to this resource key; refresh explicitly reloads it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, enabled, refresh])
  return state.key === key ? state : { key, loading: true, data: undefined, error: false }
}

function FundTable({ rows }: { rows: EtfRow[] }) {
  const { t } = useTranslation('etf')
  return <>
    <div className="etf-desktop-table scrollbar overflow-x-auto"><table><thead><tr>{(['index', 'fund', 'change', 'turnover', 'peak', 'ratio', 'units', 'net', 'size'] as const).map(key => <th key={key}>{t(key)}</th>)}</tr></thead>
      <tbody>{rows.map((row, i) => <tr key={row.code}><td className="etf-group">{i === 0 || rows[i - 1].index !== row.index ? row.index : ''}</td><td><strong>{row.manager}</strong><small>{row.code}</small></td><td className={marketSignTextClass(row.change_percent)}>{signed(row.change_percent, 2)}{row.change_percent == null ? '' : '%'}</td><td>{numeric(row.amount)}{t('amountUnit')}</td><td>{row.peak_window ? `${row.peak_window.start}–${row.peak_window.end}` : '—'}</td><td>{row.peak_window?.ratio == null ? '—' : t('times', { value: numeric(row.peak_window.ratio) })}</td><td className={marketSignTextClass(row.shares_delta)}>{signed(row.shares_delta)}{t('sharesUnit')}</td><td className={marketSignTextClass(row.net)}>{signed(row.net)}{t('amountUnit')}</td><td>{numeric(row.scale, 0)}{t('amountUnit')}</td></tr>)}</tbody></table></div>
    <div className="etf-mobile-table">{rows.map((row, i) => <div key={row.code}>{(i === 0 || rows[i - 1].index !== row.index) && <div className="etf-mobile-group">{row.index}</div>}<div className="etf-mobile-row"><div><strong>{row.manager}</strong><small>{row.code}</small><b className={marketSignTextClass(row.change_percent)}>{signed(row.change_percent, 2)}{row.change_percent == null ? '' : '%'}</b></div><p><span>{row.peak_window ? `${row.peak_window.start}–${row.peak_window.end}` : '—'} · {numeric(row.peak_window?.amount)} {t('amountUnit')}</span><span>{row.peak_window?.ratio == null ? '—' : t('times', { value: numeric(row.peak_window.ratio) })}</span><span>{t('net')} <em className={marketSignTextClass(row.net)}>{signed(row.net)}{t('amountUnit')}</em></span></p></div></div>)}</div>
  </>
}

function Overview({ board, onDate }: { board: EtfBoard; onDate: (value: string) => void }) {
  const { t } = useTranslation('etf')
  const ratio = board.cumulative?.[board.cumulative.length - 1]?.[3]
  const difference = ratio == null ? null : Math.round((ratio - 1) * 100)
  const loud = ratio != null && ratio >= 1.2
  const history = board.series ?? []
  const valid = history.filter(row => row.net != null)
  const greatest = valid.length ? valid.reduce((a, b) => a.net! > b.net! ? a : b) : null
  const least = valid.length ? valid.reduce((a, b) => a.net! < b.net! ? a : b) : null
  return <>
    <section className="etf-card etf-focus"><div className="etf-focus-heading"><div><h2>{t('minute')}</h2><span>{t('basket', { count: board.covered })}</span></div><div className="etf-total"><div><span>{t('total')}</span>{difference != null && <em className={marketSignTextClass(difference)}>{t(difference >= 0 ? 'more' : 'less', { value: Math.abs(difference) })}</em>}</div><b>{numeric(board.amount)}<small>{t('amountUnit')}</small></b></div></div>
      <div className="etf-signal"><strong>{ratio == null ? t('baselinePending') : t(loud ? 'loud' : 'quiet')}</strong>{ratio != null && <p>{t(ratio >= 1 ? 'loudDetail' : 'quietDetail')}</p>}</div>
      <MinuteChart key={board.date} board={board} />
      <details className="etf-half"><summary><b>{t('halfHour')}</b><ChevronDown size={14} /></summary><div className="etf-periods">{(board.windows ?? []).map(window => <div className={(window.ratio ?? 0) >= 2 ? 'etf-period hot' : 'etf-period'} key={window.start}><span>{window.start}–{window.end}</span><b>{numeric(window.amount)}<small>{t('amountUnit')}</small></b><span>{window.ratio == null ? '—' : t('times', { value: numeric(window.ratio) })}</span></div>)}</div></details>
    </section>
    <div className="etf-secondary"><details className="etf-card etf-fold"><summary><div>{t('details', { count: board.covered })}<small>{t('detailsHint')}</small></div><ChevronDown size={17} /></summary><div className="etf-fold-body"><FundTable rows={board.etfs} /></div></details>
      <details className="etf-card etf-fold"><summary><div>{t('shares')}<small>{t(board.shares_published ? 'published' : 'pending')}</small></div><ChevronDown size={17} /></summary><div className="etf-fold-body">
        <div className="etf-share-stats"><div><span>{t('net')} · {board.date.slice(5).replace('-', '/')}</span><b className={marketSignTextClass(board.net)}>{signed(board.net, 0)}<small>{t('amountUnit')}</small></b></div><div><span>{t('net20')}</span><b className={marketSignTextClass(board.net20)}>{signed(board.net20, 0)}<small>{t('amountUnit')}</small></b></div></div>
        <FlowChart key={board.date} series={history} onDate={onDate} />
        <div className="etf-flow-summary"><span>{t('net60')} <b className={marketSignTextClass(valid.reduce((sum, r) => sum + r.net!, 0))}>{valid.length === history.length ? signed(valid.reduce((sum, r) => sum + r.net!, 0), 0) : '—'} {t('amountUnit')}</b></span>{greatest && <span>{t('maxIn')} {greatest.date.slice(5).replace('-', '/')} <b className={marketSignTextClass(greatest.net)}>{signed(greatest.net, 0)} {t('amountUnit')}</b></span>}{least && <span>{t('maxOut')} {least.date.slice(5).replace('-', '/')} <b className={marketSignTextClass(least.net)}>{signed(least.net, 0)} {t('amountUnit')}</b></span>}</div>
        <div className="etf-surge-list">{(board.surges ?? []).slice(0, 10).map(row => <button type="button" key={row.date} onClick={() => onDate(row.date)}><b>{row.date.slice(5).replace('-', '/')}</b><span>{row.peak_window?.start}–{row.peak_window?.end} · {t('times', { value: numeric(row.peak_window?.ratio) })}<small>{t('turnover')} {numeric(row.peak_window?.amount, 0)} {t('amountUnit')} · {t('hs300')} <em className={marketSignTextClass(row.hs300_change_percent)}>{signed(row.hs300_change_percent, 2)}%</em></small></span><span className={marketSignTextClass(row.net)}>{signed(row.net, 0)} {t('amountUnit')}<small>{t('net')}</small></span></button>)}</div>
      </div></details></div>
  </>
}

function NationalTeam({ data, onDate }: { data: EtfNationalTeam; onDate: (value: string) => void }) {
  const { t } = useTranslation('etf')
  const [institution, setInstitution] = useState('all')
  const holdings = data.holdings.filter(row => institution === 'all' || row.institution === institution)
  const groups = [...new Set(holdings.map(row => row.institution))]
  const codes = new Set(holdings.map(row => row.code))
  const rows = data.watchlist.filter(row => codes.has(row.code))
  const flow = rows.length && rows.every(row => row.net != null) ? rows.reduce((sum, row) => sum + row.net!, 0) : null
  const institutionLabel = (id: string) => t(id as 'huijin' | 'csf' | 'guoxin' | 'chengtong')
  return <div className="etf-national">
    <div className="etf-national-tools"><span>{t('coverage', { count: data.coverage.filter(row => row.report_date).length })}</span><Select value={institution} onValueChange={setInstitution}><SelectTrigger aria-label={t('institutions')} className="w-44 h-9"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="all">{t('all')}</SelectItem>{data.institutions.map(id => <SelectItem key={id} value={id}>{institutionLabel(id)}</SelectItem>)}</SelectContent></Select></div>
    <div className="etf-national-stats"><div className="etf-card"><span>{t('institutions')}</span><b>{groups.length || '—'}</b></div><div className="etf-card"><span>{t('heldFunds')}</span><b>{codes.size || '—'}</b></div><div className="etf-card"><span>{t('watchFlow')}</span><b className={marketSignTextClass(flow)}>{signed(flow)}<small>{t('amountUnit')}</small></b></div></div>
    <section className="etf-card"><h2>{t('disclosed')}</h2>{!holdings.length ? <p className="etf-empty">{t('noHoldings')}</p> : <div className="etf-holdings scrollbar overflow-x-auto"><table><thead><tr>{(['holder', 'fund', 'reportDate', 'heldShares', 'heldRatio', 'heldDelta'] as const).map(key => <th key={key}>{t(key)}</th>)}</tr></thead><tbody>{holdings.map(row => <tr key={`${row.code}:${row.holder_name}`}><td><strong>{row.holder_name}</strong></td><td>{row.name}<small>{row.code}</small></td><td>{row.report_date}</td><td>{numeric(row.shares / 1e8, 2)} {t('sharesUnit')}</td><td>{numeric(row.ratio_percent, 2)}%</td><td className={marketSignTextClass(row.shares_change)}>{signed(row.shares_change == null ? null : row.shares_change / 1e8, 2)}{row.shares_change == null ? '' : t('sharesUnit')}</td></tr>)}</tbody></table></div>}</section>
    {!!rows.length && <section className="etf-card"><h2>{t('watchlist')}</h2><FundTable rows={rows} /></section>}
    <section className="etf-card"><h2>{t('signals')}</h2>{!data.signals.length ? <p className="etf-empty">{t('noSignals')}</p> : <div className="etf-surge-list">{data.signals.map(row => <button type="button" key={row.date} onClick={() => onDate(row.date)}><b>{row.date.slice(5).replace('-', '/')}</b><span>{t('countertrend')}<small>{t('hs300')} <em className={marketSignTextClass(row.index_change_percent)}>{signed(row.index_change_percent, 2)}%</em> · {t('times', { value: numeric(row.peak_ratio) })}</small></span><span className={marketSignTextClass(row.net_subscription_estimate_cny)}>{signed(row.net_subscription_estimate_cny / 1e8)} {t('amountUnit')}<small>{t('net')}</small></span></button>)}</div>}</section>
  </div>
}

export default function BroadEtf() {
  const { t } = useTranslation('etf')
  const [params, setParams] = useSearchParams()
  const date = params.get('date') || ''
  const active = params.get('view') === 'national' ? 'national' : 'overview'
  const [refresh, setRefresh] = useState(0)
  const boardState = useEtf(`board:${date}`, signal => etfApi.board(date, signal), true, refresh)
  const datesState = useEtf('dates', etfApi.dates, true, refresh)
  const nationalState = useEtf(`national:${date}`, signal => etfApi.national(date, signal), active === 'national', refresh)
  const board = boardState.data?.payload
  const dates = datesState.data ?? []
  const index = dates.indexOf(date || board?.date || dates[0])
  const change = (key: string, value: string) => setParams(previous => { const next = new URLSearchParams(previous); if (value) next.set(key, value); else next.delete(key); return next }, { replace: true })
  const onDate = (value: string) => setParams(previous => { const next = new URLSearchParams(previous); next.set('date', value); next.delete('view'); return next })
  const retry = () => setRefresh(value => value + 1)
  const state = active === 'national' ? nationalState : boardState
  return <div className="etf-page">
    <div className="etf-page-heading"><div><h1>{t('title')}</h1><span className="etf-status">{board?.date.slice(5).replace('-', '/')} {board && t(board.status === '盘中' ? 'trading' : 'closed')} {board && '·'} {board && t(board.shares_published ? 'published' : 'pending')}{(boardState.data?.stale || boardState.error) && ` · ${t('stale')}`}</span></div>
      <div className="etf-date-controls"><Button variant="ghost" size="icon" aria-label={t('previous')} disabled={index < 0 || index >= dates.length - 1 || boardState.loading} onClick={() => change('date', dates[index + 1])}><ChevronLeft size={16} /></Button><Select value={date || 'latest'} onValueChange={value => change('date', value === 'latest' ? '' : value)}><SelectTrigger aria-label={t('date')} className="h-8 w-36 border-0 shadow-none"><SelectValue placeholder={t('date')} /></SelectTrigger><SelectContent><SelectItem value="latest">{dates[0] || t('latest')}</SelectItem>{dates.map(day => <SelectItem key={day} value={day}>{day}</SelectItem>)}</SelectContent></Select><Button variant="ghost" size="icon" aria-label={t('next')} disabled={index <= 0 || boardState.loading} onClick={() => change('date', index === 1 ? '' : dates[index - 1])}><ChevronRight size={16} /></Button><Button variant="ghost" size="icon" aria-label={t('refresh')} onClick={retry}><RefreshCw size={14} className={state.loading ? 'animate-spin' : ''} /></Button></div></div>
    <Tabs value={active} onValueChange={value => change('view', value === 'overview' ? '' : value)} className="etf-tabs"><TabsList><TabsTrigger value="overview">{t('overview')}</TabsTrigger><TabsTrigger value="national">{t('national')}</TabsTrigger></TabsList></Tabs>
    {state.loading && !state.data && <div className="etf-card etf-empty" role="status"><RefreshCw className="animate-spin" size={20} />{t('loading')}</div>}
    {state.error && <div className="etf-error" role="alert">{t('unavailable')}<Button variant="ghost" size="sm" onClick={retry}>{t('retry')}</Button></div>}
    {active === 'overview' && board && <Overview board={board} onDate={onDate} />}
    {active === 'national' && nationalState.data && <NationalTeam data={nationalState.data} onDate={onDate} />}
  </div>
}
