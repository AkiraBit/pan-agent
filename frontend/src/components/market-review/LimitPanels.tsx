import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ChevronDown, ChevronRight } from 'lucide-react'
import { Link } from 'react-router-dom'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@panwatch/base-ui/components/ui/dialog'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@panwatch/base-ui/components/ui/select'
import { Tabs, TabsList, TabsTrigger } from '@panwatch/base-ui/components/ui/tabs'
import { marketSignTextClass } from '@/lib/market-colors'
import { clock, groupStocks, ladderRows, pct, pool, type LimitStock, type LimitBoard } from './data'
import { Sparkline } from './charts'
import { useReview } from './use-review'
import type { MinutePoint } from './data'

export function StockTile({ stock, onOpen, compact = false }: { stock: LimitStock; onOpen: (stock: LimitStock) => void; compact?: boolean }) {
  const { t } = useTranslation('marketReview')
  const minute = useReview<{ line: MinutePoint[]; interval?: string }>(`minute/${stock.code}`, stock.trade_date || '', 0, !compact && !!stock.trade_date && !stock.line?.length)
  const sealed = stock.state === 'sealed' || stock.active
  const opened = stock.state === 'opened' || stock.active === false
  return <button type="button" className={`review-stock ${sealed ? 'is-sealed' : 'is-muted'} ${compact ? 'is-compact' : ''}`} onClick={() => onOpen(stock)}
    title={[stock.code, ...(stock.themes ?? []), stock.first_limit_at, stock.quote_at].filter(Boolean).join(' · ')}>
    {!compact && <span className="review-stock-status">
      {sealed ? <><span>{stock.limit_type === '一字板' ? '' : clock(stock.last_limit_at)}</span><span className="review-tag">{t(stock.limit_type === '一字板' ? 'oneWord' : stock.resealed ? 'resealed' : 'sealed')}</span></>
        : <><span className={marketSignTextClass(stock.change_percent)}>{pct(stock.change_percent)}</span>{opened && <span className="review-open-tag">{t('opened')}</span>}</>}
      {stock.lhb_net != null && <span className="review-tag">{t('lhbBadge')}</span>}
    </span>}
    <strong>{stock.name}</strong>
    {!compact && <Sparkline points={stock.line?.length ? stock.line : minute.data?.payload.line} muted={!sealed} />}
    <span className="review-stock-topic">{compact ? sealed ? ((stock.board_count ?? 1) > 1 ? t('boards', { count: stock.board_count ?? 1 }) : stock.tag || t('first')) : t('opened') : stock.topic_label || stock.theme || stock.themes?.[0] || stock.industry || '—'}</span>
  </button>
}
export function Ladder({ board, preview = false, onOpen, query = '' }: { board: LimitBoard; preview?: boolean; onOpen: (stock: LimitStock) => void; query?: string }) {
  const { t } = useTranslation('marketReview')
  const [expanded, setExpanded] = useState<Record<number, boolean>>({})
  const match = (stock: LimitStock) => [stock.code, stock.name, stock.group, ...(stock.themes ?? [])].join(' ').toLowerCase().includes(query.toLowerCase())
  const rows = ladderRows(board).map(row => ({ ...row, stocks: row.stocks.filter(match) })).filter(row => row.stocks.length)
  return <div className={`review-ladder ${preview ? 'is-preview' : ''}`}>
    {rows.length === 0 && <p className="review-empty">{t(query ? 'noMatch' : 'empty')}</p>}
    {rows.map((row, index) => {
      const size = preview ? 7 : expanded[row.height] || query ? row.stocks.length : 17
      const hidden = Math.max(0, row.stocks.length - size)
      return <div className="review-ladder-row" key={row.height}>
        <div className="review-level" style={{ opacity: Math.max(.55, 1 - index * .12) }}><strong>{t('boards', { count: row.height })}</strong><small>{t('stocks', { count: row.sealed })}</small></div>
        <div className="review-ladder-stocks">{row.stocks.slice(0, size).map(stock => <StockTile key={stock.code} stock={stock} onOpen={onOpen} />)}
          {hidden > 0 && (preview ? <Link className="review-more-stocks" to="/limit-up">{t('more', { count: hidden })}<ChevronRight size={12} /></Link>
            : <button type="button" className="review-more-stocks" aria-expanded={!!expanded[row.height]} onClick={() => setExpanded(value => ({ ...value, [row.height]: true }))}>{t('more', { count: hidden })}<ChevronDown size={12} /></button>)}
        </div>
      </div>
    })}
    <div className="review-promotion"><span>{t('promotion')} {board.promotion?.map(p => `${p.label} ${p.promoted}/${p.base}`).join(' · ')}</span><Link to="/limit-up?view=wall">{t('first')} {board.stocks.filter(s => s.active && s.board_count === 1).length} <ChevronRight size={12} /></Link></div>
  </div>
}
export function LimitList({ board, onOpen, query, view, onView }: { board: LimitBoard; onOpen: (stock: LimitStock) => void; query: string; view: string; onView: (view: string) => void }) {
  const { t } = useTranslation('marketReview')
  const [status, setStatus] = useState('all')
  const [group, setGroup] = useState('all')
  const [sort, setSort] = useState<{ key: 'board_count' | 'change_percent' | 'first_limit_at' | 'amount'; asc: boolean }>({ key: 'board_count', asc: false })
  const stocks = pool(board).filter(s => (status === 'all' || (status === 'sealed' ? s.active : !s.active)) && (group === 'all' || s.group === group) && [s.code, s.name, ...(s.themes ?? []), s.group].join(' ').toLowerCase().includes(query.toLowerCase()))
  const sorted = [...stocks].sort((a, b) => {
    const av = a[sort.key], bv = b[sort.key]
    if (av == null) return 1
    if (bv == null) return -1
    return (typeof av === 'string' && typeof bv === 'string' ? av.localeCompare(bv) : Number(av) - Number(bv)) * (sort.asc ? 1 : -1)
  })
  const sortBy = (key: typeof sort.key) => setSort({ key, asc: sort.key === key ? !sort.asc : key === 'first_limit_at' })
  const money = (n?: number | null) => n == null ? '—' : Math.abs(n) >= 1e8 ? `${(n / 1e8).toFixed(2)}${t('yi')}` : `${(n / 1e4).toFixed(0)}${t('wan')}`
  return <section className="review-all" id="limit-pool">
    <div className="review-section-heading"><h2>{t('allLimits')} <small>{t('stocks', { count: stocks.length })}</small></h2><Tabs value={view} onValueChange={onView}><TabsList aria-label={t('view')}><TabsTrigger value="wall">{t('wall')}</TabsTrigger><TabsTrigger value="details">{t('details')}</TabsTrigger></TabsList></Tabs></div>
    <div className="review-filters"><Select value={status} onValueChange={setStatus}><SelectTrigger aria-label={t('status')} className="h-8 w-36"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="all">{t('includeOpened')}</SelectItem><SelectItem value="sealed">{t('onlySealed')}</SelectItem><SelectItem value="opened">{t('onlyOpened')}</SelectItem></SelectContent></Select>
      <Select value={group} onValueChange={setGroup}><SelectTrigger aria-label={t('group')} className="h-8 w-40"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="all">{t('all')}</SelectItem>{groupStocks(pool(board)).map(g => <SelectItem key={g.name} value={g.name}>{g.name}</SelectItem>)}</SelectContent></Select></div>
    {stocks.length === 0 ? <p className="review-empty">{t('noMatch')}</p> : view === 'wall' ? <div className="review-wall">{groupStocks(stocks).map(g => <section className="review-theme-group" key={g.name}><h3>{g.name} <small>{g.stocks.length}</small></h3><div>{g.stocks.map(s => <StockTile key={s.code} stock={s} compact onOpen={onOpen} />)}</div></section>)}</div>
      : <div className="review-table-wrap overflow-x-auto scrollbar"><table className="review-table"><thead><tr><th>{t('stock')}</th>{([['board_count', 'board'], ['change_percent', 'change'], ['first_limit_at', 'firstSeal'], ['amount', 'amount']] as const).map(([key, label]) => <th key={key} aria-sort={sort.key === key ? sort.asc ? 'ascending' : 'descending' : 'none'}><button type="button" onClick={() => sortBy(key)}>{t(label)} {sort.key === key ? sort.asc ? '↑' : '↓' : '↕'}</button></th>)}<th>{t('lastSeal')}</th><th>{t('opens')}</th><th>{t('turnover')}</th><th>{t('reason')}</th></tr></thead><tbody>{sorted.map(s => <tr key={s.code}><td><button type="button" className="review-table-name" onClick={() => onOpen(s)}>{s.name}<small>{s.code}</small></button></td><td>{s.active ? t('boards', { count: s.board_count ?? 1 }) : t('opened')}</td><td className={marketSignTextClass(s.change_percent)}>{pct(s.change_percent)}</td><td>{clock(s.first_limit_at)}</td><td>{money(s.amount)}</td><td>{clock(s.last_limit_at)}</td><td>{s.open_count ?? '—'}</td><td>{s.turnover_rate == null ? '—' : `${s.turnover_rate.toFixed(2)}%`}</td><td className="review-reason">{s.themes?.join(' · ') || s.theme || '—'}</td></tr>)}</tbody></table></div>}
  </section>
}
export function StockDetail({ stock, onClose, date }: { stock: LimitStock | null; onClose: () => void; date: string }) {
  const { t } = useTranslation('marketReview')
  const minute = useReview<{ line: MinutePoint[]; interval?: string }>(`minute/${stock?.code || ''}`, date, 0, !!stock && !stock.line?.length)
  const money = (n?: number | null) => n == null ? '—' : Math.abs(n) >= 1e8 ? `${(n / 1e8).toFixed(2)}${t('yi')}` : `${(n / 1e4).toFixed(0)}${t('wan')}`
  return <Dialog open={!!stock} onOpenChange={open => { if (!open) onClose() }}><DialogContent className="review-dialog max-w-2xl max-h-[90dvh] overflow-y-auto scrollbar"><DialogHeader><DialogTitle>{stock?.name} <span className="text-muted-foreground text-sm">{stock?.code}</span></DialogTitle><DialogDescription>{date} · {t('stockDetail')}</DialogDescription></DialogHeader>{stock && <>
    <div className={`review-detail-price ${marketSignTextClass(stock.change_percent)}`}><strong>{stock.price?.toFixed(2) ?? '—'}</strong><span>{pct(stock.change_percent)}</span><span className="review-tag">{stock.active ? t('boards', { count: stock.board_count ?? 1 }) : t(stock.state === 'fallen' ? 'fallen' : stock.state === 'waiting' ? 'waiting' : 'opened')}</span></div>
    <Sparkline points={stock.line?.length ? stock.line : minute.data?.payload.line} large />{minute.data?.payload.interval === '5m' && <p className="review-flow-note">{t('fiveMinute')}</p>}
    <div className="review-detail-stats">{([[t('firstSeal'), clock(stock.first_limit_at)], [t('lastSeal'), clock(stock.last_limit_at)], [t('opens'), stock.open_count ?? '—'], [t('amount'), money(stock.amount)], [t('turnover'), stock.turnover_rate == null ? '—' : `${stock.turnover_rate.toFixed(2)}%`], [t('cap'), money(stock.float_cap)], [t('sealAmount'), money(stock.seal_amount)], [t('lhbNet'), money(stock.lhb_net)]]).map(([label, value]) => <div key={label}><span>{label}</span><strong>{value}</strong></div>)}</div>
    <div><h3>{t('reason')}</h3><p className="mt-2 text-sm">{stock.themes?.join(' · ') || stock.theme || t('reasonMissing')}</p>{stock.lhb_who?.length ? <p className="mt-2 text-xs text-muted-foreground">{stock.lhb_who.join(' · ')}</p> : null}</div>
    <div className="review-source">{t('quoteAt')} {stock.quote_at?.replace('T', ' ').slice(0, 19) || '—'} · {t('themeAt')} {stock.themes_date || '—'}</div>
  </>}</DialogContent></Dialog>
}
