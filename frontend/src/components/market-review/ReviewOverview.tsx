import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { ChevronRight, ExternalLink } from 'lucide-react'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@panwatch/base-ui/components/ui/dialog'
import { formatDate } from '@/i18n/format'
import { marketSignTextClass } from '@/lib/market-colors'
import { Bars } from './charts'
import { Ladder } from './LimitPanels'
import { groupStocks, pool, pct, clock, type Daily, type Etf, type LimitBoard, type LimitStock, type Overseas, type ReviewResponse, type Provenance } from './data'
import { useReview } from './use-review'

export function ResourceState({ loading, error, stale, children, onRetry }: { loading?: boolean; error?: string; stale?: boolean; children?: React.ReactNode; onRetry?: () => void }) {
  const { t } = useTranslation('marketReview')
  return <>{(error || stale) && <p role="status" className="review-warning">{children ? t('stale') : t('unavailable')} {onRetry && <button type="button" onClick={onRetry}>{t('retry')}</button>}</p>}{children || <p className="review-empty" role="status">{t(loading ? 'loading' : error ? 'unavailable' : 'empty')}</p>}</>
}
function SourceLink({ path, children }: { path: string; children: React.ReactNode }) {
  const { t } = useTranslation('marketReview')
  return <a className="review-source-link" href={({ '/macro': 'https://quote.eastmoney.com/center/gridlist.html#us_etf', '/lhb': 'https://data.eastmoney.com/stock/tradedetail.html', '/calendar': 'https://finance.baidu.com/calendar', '/etf': 'https://gu.qq.com/sh510300', '/futures': 'http://www.cffex.com.cn/ccpm/' } as Record<string, string>)[path]} target="_blank" rel="noopener noreferrer" title={t('external')}>{children}<ExternalLink size={11} /></a>
}
export function SourceNote({ data }: { data?: Provenance }) {
  const { t } = useTranslation('marketReview')
  const methods: Record<string, string> = { eastmoney_pool: t('method_eastmoney_pool'), etf_turnover: t('method_etf_turnover'), etf_snapshot: t('method_etf_snapshot'), cffex_top20: t('method_cffex_top20'), lhb_disclosure: t('method_lhb_disclosure'), calendar_stars: t('method_calendar_stars'), sector_etfs: t('method_sector_etfs') }
  if (!data?.sources?.length) return null
  return <div className="review-source"><span>{t('source')} </span>{data.sources.map((source, index) => <span key={source.id}>{index > 0 && ' · '}<a href={source.url} target="_blank" rel="noopener noreferrer">{source.name}</a></span>)}{data.method && <p>{methods[data.method]}</p>}</div>
}
export function ReviewHero({ board, limit = false }: { board: LimitBoard; limit?: boolean }) {
  const { t } = useTranslation('marketReview')
  const active = board.stocks.filter(s => s.active)
  const highest = active.length ? Math.max(...active.map(s => s.board_count ?? 1)) : 0
  const leaders = active.filter(s => s.board_count === highest).map(s => s.name)
  const groups = groupStocks(pool(board))
  return <section className={`review-hero ${limit ? 'is-limit' : ''}`}>
    {!limit && <div className="review-hero-title"><p>{board.market_status} · {board.date} · {clock(board.observed_at)}</p><h1>{t('highest')} {t('boards', { count: highest })}<span> · {leaders.join('、') || '—'}</span></h1><p>{t('sealed')} {t('families', { count: board.active_count })}{groups[0] ? ` · ${t('most', { name: groups[0].name, count: groups[0].stocks.length })}` : ''}</p></div>}
    <div className="review-metrics">{([[t('sealed'), board.active_count], [t('sealRate'), `${board.seal_rate ?? '—'}%`], [t('opened'), board.opened_count], [t(limit ? 'highest' : 'consecutive'), limit ? t('boards', { count: highest }) : active.filter(s => (s.board_count ?? 1) > 1).length]]).map(([name, value]) => <div key={name}><span>{name}</span><strong>{value}</strong></div>)}</div>
    <div className="review-history"><Bars values={(board.history ?? []).map(d => d.sealed)} labels={(board.history ?? []).map(d => d.date)} label={t('history')} compact /><small>{t('history')}</small></div>
    {limit && <div className="review-limit-caption"><span>{t('consecutive')} <b className="text-market-up">{active.filter(s => (s.board_count ?? 1) > 1).length}</b> · {t('promotion')} {board.promotion?.map(p => `${p.label} ${p.promoted}/${p.base}`).join(' · ')}</span><span>{board.market_status} · {clock(board.observed_at)}</span></div>}
  </section>
}
export function ReviewOverview({ board, onOpen, refresh, onRetry }: { board: LimitBoard | undefined; onOpen: (s: LimitStock) => void; refresh: number; onRetry: () => void }) {
  const { t } = useTranslation('marketReview')
  const overseas = useReview<Overseas>('overseas', '', refresh)
  const daily = useReview<Daily>('daily', '', refresh)
  const etf = useReview<Etf>('etf', '', refresh)
  const [detail, setDetail] = useState<'etf' | 'futures' | null>(null)
  const [extended, setExtended] = useState(false)
  const market = overseas.data?.payload
  const day = daily.data?.payload
  const flow = etf.data?.payload
  const groups = board ? groupStocks(pool(board)) : []
  const money = (n?: number | null) => n == null ? '—' : `${n > 0 ? '+' : ''}${Math.abs(n) >= 1e8 ? `${(n / 1e8).toFixed(1)}${t('yi')}` : `${(n / 1e4).toFixed(0)}${t('wan')}`}`
  const errorProps = <T,>(state: { loading: boolean; error?: string; data?: ReviewResponse<T> }) => ({ loading: state.loading, error: state.error, stale: state.data?.stale, onRetry })
  const etfChart = flow && (flow.minutes.length ? <Bars values={flow.minutes.map(m => m[1])} labels={flow.minutes.map(m => m[0])} label={t('etfTotal')} unit={t('yi')} /> : <p className="review-empty">{t('minuteMissing')}</p>)
  const futuresChart = day?.futures && <Bars values={day.futures.series.map(d => d.net_change)} labels={day.futures.series.map(d => d.date.slice(5))} label={t('futuresHistory')} unit={t('units')} />
  return <>
    <div className="review-overview-grid">
      <section className="review-panel review-overview-ladder"><div className="review-section-heading"><h2>{t('ladder')}</h2><Link to="/limit-up">{t('fullLadder')}<ChevronRight size={14} /></Link></div>{board ? <Ladder board={board} preview onOpen={onOpen} /> : <p className="review-empty">{t('empty')}</p>}</section>
      <section className="review-panel review-overseas"><div className="review-section-heading"><h2>{t('overseas')}</h2><SourceLink path="/macro">{t('allSectors')}</SourceLink></div><ResourceState {...errorProps(overseas)}>{market && <>
        <div className="review-overseas-meta">{market.industry.sectors.some(s => s.extended) ? <button type="button" onClick={() => setExtended(value => !value)} aria-pressed={extended}>{t(extended ? 'extended' : 'regular')}</button> : <span>{t('regular')}</span>}<span>{formatDate(market.industry?.meta?.generated_at || '', { dateStyle: 'short', timeStyle: 'short' })} {t('updated')}</span></div>
        <div className="review-commodities">{market.indicators?.commodities?.items?.filter(q => ['BRENT', 'XAU', 'XAG'].includes(q.symbol)).map(q => <a key={q.symbol} href={q.url || 'https://finance.sina.com.cn/futuremarket/'} target="_blank" rel="noopener noreferrer"><small>{q.name}</small><strong>{q.price?.toLocaleString(undefined, { maximumFractionDigits: q.decimals ?? 2 }) ?? '—'}</strong><span className={marketSignTextClass(q.change_percent)}>{pct(q.change_percent)}</span></a>)}</div>
        <div className="review-indices">{market.indicators?.groups?.flatMap(g => g.items).slice(0, 3).map(q => <a key={q.symbol} href={q.url || 'https://gu.qq.com/'} target="_blank" rel="noopener noreferrer"><small>{q.name}</small><strong>{q.price?.toLocaleString() ?? '—'}</strong><span className={marketSignTextClass(q.change_percent)}>{pct(q.change_percent)}</span></a>)}</div>
        <div className="review-sectors">{market.industry?.sectors?.map(s => { const change = extended ? s.extended?.change_percent : s.regular?.change_percent; return <a key={s.id} href={s.url} title={s.symbol} target="_blank" rel="noopener noreferrer" className={`${marketSignTextClass(change)} ${(change ?? 0) >= 0 ? 'review-up-tint' : 'review-down-tint'}`}><span>{s.name}</span><strong>{pct(change)}</strong></a> })}</div>
        <SourceNote data={market} />{!!Object.keys(market.errors ?? {}).length && <p className="review-warning">{t('partial')}</p>}
      </>}</ResourceState></section>
      <section className="review-panel review-etf"><div className="review-section-heading"><h2>{t('etf')}</h2><button type="button" disabled={!flow} onClick={() => setDetail('etf')}>{t('detail')}<ChevronRight size={14} /></button></div><ResourceState {...errorProps(etf)}>{flow && <><div className="review-flow-summary"><span>{t('amount')} <strong>{flow.amount.toFixed(0)}</strong> {t('yi')}</span><span>{flow.date.slice(5)} · {flow.peak_window?.ratio != null && t('times', { value: flow.peak_window.ratio.toFixed(1) })}</span></div><p className="review-flow-note">{t('etfTotal')} · {t('peak')} {flow.peak_window ? `${flow.peak_window.start} – ${flow.peak_window.end}` : '—'}</p>{etfChart}<SourceNote data={flow} />{flow.errors?.baseline && <p className="review-flow-note">{t('baselineMissing')}</p>}</>}</ResourceState></section>
      <section className="review-panel review-futures"><div className="review-section-heading"><h2>{t('futures')}</h2><button type="button" disabled={!day?.futures} onClick={() => setDetail('futures')}>{t('detail')}<ChevronRight size={14} /></button></div><ResourceState {...errorProps(daily)} error={daily.error || (day?.errors?.futures ? 'unavailable' : undefined)}>{day?.futures && <><div className="review-flow-summary"><span>{t('netChange')} <strong className={marketSignTextClass(day.futures.total.net_change)}>{day.futures.total.net_change > 0 ? '+' : ''}{day.futures.total.net_change.toLocaleString()}</strong> {t('units')}</span><span>{day.futures.date.slice(5)}</span></div>{futuresChart}<SourceNote data={day.futures} />{day.futures.partial && <p className="review-warning">{t('partial')}</p>}</>}</ResourceState></section>
      <section className="review-panel review-topics"><div className="review-section-heading"><h2>{t('topics')} <small>{t('includeOpened')}</small></h2><Link to="/limit-up?view=wall">{t('allLimits')}<ChevronRight size={14} /></Link></div><div className="review-topic-grid">{groups.slice(0, 6).map(g => <div className="review-topic" key={g.name}><Link to={`/limit-up?view=wall&q=${encodeURIComponent(g.name)}`}><h3>{g.name}</h3><span className="text-market-up">{t('families', { count: g.stocks.length })}</span></Link><div>{g.stocks.slice(0, 3).map(s => <button type="button" key={s.code} onClick={() => onOpen(s)}>{s.name}{(s.board_count ?? 1) > 1 && <small className="text-market-up">{t('boards', { count: s.board_count ?? 1 })}</small>}</button>)}{g.stocks.length > 3 && <Link to={`/limit-up?view=wall&q=${encodeURIComponent(g.name)}`}>+{g.stocks.length - 3}</Link>}</div></div>)}</div></section>
      <section className="review-panel review-hotmoney"><div className="review-section-heading"><h2>{t('hotmoney')}</h2><SourceLink path="/lhb">{t('lhb')}</SourceLink></div><ResourceState {...errorProps(daily)} error={daily.error || (day?.errors?.lhb ? 'unavailable' : undefined)}>{day?.lhb && <><p className="review-flow-note">{day.lhb.date} · {clock(day.lhb.observed_at)}</p><div className="review-seats">{day.lhb.seats?.map(s => <a key={s.key} href={`https://data.eastmoney.com/stock/lhb/yyb/${encodeURIComponent(s.key)}.html`} target="_blank" rel="noopener noreferrer"><span><strong>{s.alias}</strong><small>{s.stocks.map(stock => stock.name).join('、')}</small></span><b className={marketSignTextClass(s.net)}>{money(s.net)}</b></a>)}</div><p className="review-lhb-summary">{t('institution')} <span className={marketSignTextClass(day.lhb.institution_net)}>{money(day.lhb.institution_net)}</span> · {t('connect')} <span className={marketSignTextClass(day.lhb.connect_net)}>{money(day.lhb.connect_net)}</span> · {t('listed')} {day.lhb.count}</p><SourceNote data={day.lhb} /></>}</ResourceState></section>
      <section className="review-panel review-calendar"><div className="review-section-heading"><h2>{t('calendar')}</h2><SourceLink path="/calendar">{t('all')}</SourceLink></div><ResourceState {...errorProps(daily)} error={daily.error || (day?.errors?.calendar ? 'unavailable' : undefined)}>{day?.calendar && <div>{day.calendar.macro?.map(event => <div className="review-event" key={`${event.date}:${event.title}`}><time>{event.date.slice(5)}<small>{event.time}</small></time><span>{event.title}</span></div>)}<SourceNote data={day.calendar} /></div>}</ResourceState></section>
    </div>
    <Dialog open={detail != null} onOpenChange={open => { if (!open) setDetail(null) }}><DialogContent className="review-dialog max-w-3xl max-h-[90dvh] overflow-y-auto scrollbar"><DialogHeader><DialogTitle>{t(detail === 'etf' ? 'etf' : 'futures')}</DialogTitle><DialogDescription>{detail === 'etf' ? flow?.date : day?.futures?.date}</DialogDescription></DialogHeader>{detail === 'etf' ? <>{etfChart}<div className="review-detail-stats">{flow?.windows.map(w => <div key={w.start}><span>{w.start}–{w.end}</span><strong>{w.amount.toFixed(1)} {t('yi')}</strong><small>{w.ratio == null ? t('baselineMissing') : t('times', { value: w.ratio.toFixed(2) })}</small></div>)}</div></> : <>{futuresChart}<div className="review-detail-stats">{(['net', 'long', 'short'] as const).map(key => <div key={key}><span>{t(key)}</span><strong>{day?.futures?.total[key].toLocaleString()} {t('units')}</strong></div>)}</div></>}<SourceLink path={detail === 'etf' ? '/etf' : '/futures'}>{t('external')}</SourceLink></DialogContent></Dialog>
  </>
}
