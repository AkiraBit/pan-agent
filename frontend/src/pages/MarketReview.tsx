import { useRef, useState } from 'react'
import { Link, useLocation, useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { ChevronLeft, ChevronRight, RefreshCw, Search, Download, X } from 'lucide-react'
import { Button } from '@panwatch/base-ui/components/ui/button'
import { Input } from '@panwatch/base-ui/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@panwatch/base-ui/components/ui/select'
import { useReview } from '@/components/market-review/use-review'
import { Ladder, LimitList, StockDetail } from '@/components/market-review/LimitPanels'
import { ResourceState, ReviewHero, ReviewOverview, SourceNote } from '@/components/market-review/ReviewOverview'
import type { LimitBoard, LimitStock } from '@/components/market-review/data'
import '@/components/market-review/review.css'

export default function MarketReview() {
  const { t } = useTranslation('marketReview')
  const location = useLocation()
  const [params, setParams] = useSearchParams()
  const limit = location.pathname === '/limit-up'
  const date = limit ? params.get('date') || '' : ''
  const query = params.get('q') || ''
  const view = params.get('view') === 'details' ? 'details' : 'wall'
  const [refresh, setRefresh] = useState(0)
  const [selected, setSelected] = useState<{ stock: LimitStock; date: string } | null>(null)
  const [sharing, setSharing] = useState(false)
  const [shareError, setShareError] = useState(false)
  const boardState = useReview<LimitBoard>('board', date, refresh)
  const datesState = useReview<string[]>('dates', '', refresh)
  const board = boardState.data?.payload
  const dates = datesState.data?.payload ?? []
  const dayIndex = dates.indexOf(date || board?.date || dates[0])
  const exportRef = useRef<HTMLDivElement>(null)
  const updateParams = (key: string, value: string) => setParams(previous => { const next = new URLSearchParams(previous); if (value) next.set(key, value); else next.delete(key); return next }, { replace: true })
  const openStock = (stock: LimitStock) => setSelected({ stock, date: board?.date || date })
  const retry = () => setRefresh(value => value + 1)
  const exportImage = async () => {
    if (!exportRef.current || sharing) return
    setSharing(true); setShareError(false)
    try {
      const { toPng } = await import('html-to-image')
      const url = await toPng(exportRef.current, { pixelRatio: 2, backgroundColor: getComputedStyle(exportRef.current).backgroundColor,
        filter: node => !(node instanceof HTMLElement && node.dataset.export === 'hide') })
      const anchor = document.createElement('a'); anchor.download = `PanWatch-${board?.date || 'market'}-${limit ? 'limit' : 'review'}.png`; anchor.href = url; anchor.click()
    } catch { setShareError(true) } finally { setSharing(false) }
  }
  return <div className="market-review" ref={exportRef}>
    <div className="review-toolbar"><nav aria-label={t('view')} className="review-nav"><Link to="/" aria-current={!limit ? 'page' : undefined}>{t('review')}</Link><Link to="/limit-up" aria-current={limit ? 'page' : undefined}>{t('limit')}</Link></nav>
      <div className="review-toolbar-actions" data-export="hide">{limit && <div className="review-date-control"><Button variant="ghost" size="icon" aria-label={t('previous')} disabled={dayIndex < 0 || dayIndex >= dates.length - 1 || boardState.loading} onClick={() => updateParams('date', dates[dayIndex + 1])}><ChevronLeft size={16} /></Button>
        <Select value={date || 'latest'} onValueChange={value => updateParams('date', value === 'latest' ? '' : value)}><SelectTrigger className="h-8 w-[145px] border-0 bg-transparent text-xs" aria-label={t('date')}><SelectValue placeholder={board?.date || t('date')} /></SelectTrigger><SelectContent><SelectItem value="latest">{dates[0] || board?.date || t('latest')}</SelectItem>{dates.map(day => <SelectItem key={day} value={day}>{day}</SelectItem>)}</SelectContent></Select>
        <Button variant="ghost" size="icon" aria-label={t('next')} disabled={dayIndex <= 0 || boardState.loading} onClick={() => updateParams('date', dayIndex === 1 ? '' : dates[dayIndex - 1])}><ChevronRight size={16} /></Button></div>}
        <Button variant="ghost" size="icon" aria-label={t('refresh')} onClick={retry} disabled={boardState.loading}><RefreshCw size={15} className={boardState.loading ? 'animate-spin' : ''} /></Button>
      </div>
    </div>
    {limit && datesState.error && <p className="review-warning">{t('date')} · {t('unavailable')} <button type="button" onClick={retry}>{t('retry')}</button></p>}
    <ResourceState loading={boardState.loading} error={boardState.error} stale={boardState.data?.stale || !!board?.error} onRetry={retry}>{board && <ReviewHero board={board} limit={limit} />}</ResourceState>
    {!!Object.keys(board?.errors ?? {}).length && <p className="review-warning" role="status">{t('partial')}</p>}
    {!limit ? <ReviewOverview board={board} onOpen={openStock} refresh={refresh} onRetry={retry} /> : board && <>
      <div className="review-section-heading review-ladder-heading"><h2>{t('ladder')}</h2><div className="review-search" data-export="hide"><Search size={15} /><Input value={query} onChange={event => updateParams('q', event.target.value)} placeholder={t('search')} aria-label={t('search')} className="h-8 border-0 bg-transparent px-1 text-xs shadow-none" />{query && <button type="button" aria-label={t('clear')} onClick={() => updateParams('q', '')}><X size={14} /></button>}<Button variant="ghost" size="sm" onClick={exportImage} disabled={sharing} aria-label={t('share')}><Download size={14} /><span className="hidden sm:inline">{t(sharing ? 'sharing' : 'share')}</span></Button></div></div>
      {shareError && <p role="alert" className="review-warning">{t('shareError')}</p>}
      <Ladder key={`ladder-${board.date}`} board={board} onOpen={openStock} query={query} />
      <LimitList key={`pool-${board.date}`} board={board} onOpen={openStock} query={query} view={view} onView={value => updateParams('view', value)} />
    </>}
    <footer className="review-footer"><span>{t('footer')}</span><SourceNote data={board} />{board && <span>{board.date} · {board.market_status}</span>}</footer>
    <StockDetail stock={selected?.stock ?? null} date={selected?.date ?? ''} onClose={() => setSelected(null)} />
  </div>
}
