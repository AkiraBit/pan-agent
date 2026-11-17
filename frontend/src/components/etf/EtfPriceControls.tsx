import { useCallback, useEffect, useId, useLayoutEffect, useMemo, useRef, useState, type CSSProperties } from 'react'
import { ChevronLeft, ChevronRight, ListChecks, Search } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { etfApi, type EtfIntradayIssue, type EtfPriceInstrument, type EtfPriceLine, type PriceInstrumentKind } from '@panwatch/api/etf'
import { Button } from '@panwatch/base-ui/components/ui/button'
import { Input } from '@panwatch/base-ui/components/ui/input'
import { Popover, PopoverContent, PopoverTrigger } from '@panwatch/base-ui/components/ui/popover'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@panwatch/base-ui/components/ui/tabs'
import { useLocalStorage } from '@/lib/utils'
import { etfPriceColor, priceInstrumentKey } from './price-palette'

type Selection = { items: EtfPriceInstrument[]; visible: string[] }
type StoredSelection = Selection | { items: EtfPriceInstrument[]; active: string | null }
type Quote = { generation: number; value?: EtfPriceLine; failed?: boolean }

function restored(saved: StoredSelection): Selection {
  if ('visible' in saved) return saved
  return { items: saved.items, visible: saved.active ? [saved.active] : [] }
}

export function useEtfPriceLines(date: string | undefined, live: boolean, generation: number) {
  const [saved, setSaved] = useLocalStorage<StoredSelection>('panwatch_etf_price_lines', { items: [], visible: [] })
  const selection = useMemo(() => restored(saved), [saved])
  const cache = useRef(new Map<string, Quote>())
  const requests = useRef(new Map<string, AbortController>())
  const visibleKeys = useRef(new Set<string>())
  const [revision, redraw] = useState(0)
  const enabled = useMemo(() => {
    const keys = new Set(selection.visible)
    return selection.items.filter(item => keys.has(priceInstrumentKey(item)))
  }, [selection.items, selection.visible])

  useEffect(() => {
    if (!('visible' in saved)) setSaved(selection)
  }, [saved, selection, setSaved])

  const requestPrice = useCallback((date: string, instrument: EtfPriceInstrument, generation: number) => {
    const key = `${date}:${priceInstrumentKey(instrument)}`
    const { symbol, kind = 'etf' } = instrument
    if (requests.current.has(key)) return
    const controller = new AbortController()
    requests.current.set(key, controller)
    const finish = (value?: EtfPriceLine) => {
      if (controller.signal.aborted) return
      requests.current.delete(key)
      cache.current.delete(key)
      cache.current.set(key, { generation, value: value ?? previous, failed: !value })
      if (cache.current.size > 64) {
        const oldest = [...cache.current.keys()].find(candidate => !visibleKeys.current.has(candidate))
        if (oldest) cache.current.delete(oldest)
      }
      redraw(index => index + 1)
    }
    const previous = cache.current.get(key)?.value
    etfApi.priceLine(date, symbol, controller.signal, kind).then(
      value => finish(value.date === date && value.symbol === symbol && (value.kind ?? 'etf') === kind ? value : undefined),
      () => finish(),
    )
  }, [])

  useEffect(() => {
    const prior = visibleKeys.current
    const keys = new Set(date ? enabled.map(item => `${date}:${priceInstrumentKey(item)}`) : [])
    visibleKeys.current = keys
    for (const [key, controller] of requests.current) {
      if (!keys.has(key)) {
        controller.abort()
        requests.current.delete(key)
      }
    }
    if (!date) return
    for (const instrument of enabled) {
      const key = `${date}:${priceInstrumentKey(instrument)}`
      const entry = cache.current.get(key)
      if (entry && ((!live && entry.value?.complete)
        || (entry.generation === generation && (prior.has(key) || (live && !entry.failed))))) continue
      requestPrice(date, instrument, generation)
    }
  }, [date, live, generation, enabled, requestPrice])

  useEffect(() => () => {
    for (const controller of requests.current.values()) controller.abort()
    requests.current.clear()
    visibleKeys.current.clear()
  }, [])

  const rows = useMemo(() => {
    // The revision changes when a request updates the local cache.
    void revision
    const enabled = new Set(selection.visible)
    return selection.items.flatMap((instrument, colorIndex) => {
      const key = priceInstrumentKey(instrument)
      if (!enabled.has(key)) return []
      const entry = date ? cache.current.get(`${date}:${key}`) : undefined
      return [{ instrument, colorIndex, quote: entry?.value, failed: entry?.failed }]
    })
  }, [date, selection.items, selection.visible, revision])

  const update = (apply: (current: Selection) => Selection) => setSaved(current => apply(restored(current)))
  const setVisible = (item: EtfPriceInstrument, checked: boolean) => {
    const key = priceInstrumentKey(item)
    update(current => checked ? {
      items: current.items.some(other => priceInstrumentKey(other) === key) ? current.items : [...current.items, item],
      visible: current.visible.includes(key) ? current.visible : [...current.visible, key],
    } : { ...current, visible: current.visible.filter(symbol => symbol !== key) })
  }
  return { selection, rows, setVisible, retryPrice: (item: EtfPriceInstrument) => { if (date) requestPrice(date, item, generation) } }
}

const term = (text: string) => text.normalize('NFKC').trim().toLowerCase()
const CATALOG_CACHE_MS = 5 * 60 * 1000
const catalogCache: Partial<Record<PriceInstrumentKind, { items: EtfPriceInstrument[]; at: number }>> = {}

export function EtfPricePicker({ selection, onChange }: {
  selection: Selection
  onChange: (item: EtfPriceInstrument, checked: boolean) => void
}) {
  const { t } = useTranslation('etf')
  const [open, setOpen] = useState(false)
  const [kind, setKind] = useState<PriceInstrumentKind>('etf')
  const [query, setQuery] = useState('')
  const [retry, setRetry] = useState(0)
  const [response, setResponse] = useState<{
    kind: PriceInstrumentKind; items: EtfPriceInstrument[]; error?: `issues.${EtfIntradayIssue}` | 'priceSearchFailed'
  }>()
  const listId = useId()
  const list = useRef<HTMLUListElement>(null)
  const search = term(query)
  const selected = useMemo(() => new Set(selection.visible), [selection.visible])
  const current = response?.kind === kind ? response : undefined
  const shown = selection.items.filter(item => (item.kind ?? 'etf') === kind && selected.has(priceInstrumentKey(item))).length
  const results = useMemo(() => {
    // Keep saved instruments available even if their current catalog row is missing.
    const bySymbol = new Map(selection.items.filter(item => (item.kind ?? 'etf') === kind).map(item => [item.symbol, item]))
    for (const item of current?.items ?? []) bySymbol.set(item.symbol, item)
    return [...bySymbol.values()].flatMap(item => {
      const code = term(item.symbol)
      const name = term(item.name)
      if (search && !code.includes(search) && !name.includes(search)) return []
      const rank = !search || code === search || code.split('.')[0] === search || name === search ? 0
        : code.startsWith(search) || name.startsWith(search) ? 1 : 2
      return [{ item, rank, checked: selected.has(priceInstrumentKey(item)) }]
    }).sort((a, b) => Number(b.checked) - Number(a.checked) || a.rank - b.rank || a.item.symbol.localeCompare(b.item.symbol))
      .map(({ item }) => item)
  }, [selection.items, selected, current, search, kind])
  const checked = results.filter(item => selected.has(priceInstrumentKey(item)))
  const unchecked = results.filter(item => !selected.has(priceInstrumentKey(item)))

  useEffect(() => {
    if (!open) return
    const cached = catalogCache[kind]
    if (cached && Date.now() - cached.at < CATALOG_CACHE_MS) {
      setResponse({ kind, items: cached.items })
      return
    }
    const controller = new AbortController()
    etfApi.priceCatalog(controller.signal, kind).then(result => {
      if (controller.signal.aborted) return
      if (!result.issue) catalogCache[kind] = { items: result.items, at: Date.now() }
      setResponse({ kind, items: result.items, error: result.issue ? `issues.${result.issue}` : undefined })
    }, () => {
      if (!controller.signal.aborted) setResponse({ kind, items: [], error: 'priceSearchFailed' })
    })
    return () => controller.abort()
  }, [open, retry, kind])

  const changeOpen = (value: boolean) => {
    if (!value) setQuery('')
    setOpen(value)
  }
  const searchLabel = t(kind === 'index' ? 'priceIndexSearch' : 'priceSearch')
  const renderItem = (item: EtfPriceInstrument) => <li key={priceInstrumentKey(item)} className="[content-visibility:auto] [contain-intrinsic-size:auto_36px]">
    <label className="flex min-h-9 cursor-pointer items-center gap-2.5 rounded-md px-2.5 py-1.5 text-sm text-secondary-foreground hover:bg-muted focus-within:bg-muted">
      <input type="checkbox" className="size-4 shrink-0 accent-primary focus-visible:ring-2 focus-visible:ring-ring"
        checked={selected.has(priceInstrumentKey(item))} onChange={event => onChange(item, event.target.checked)}
        aria-label={`${item.name} ${item.symbol}`} />
      <span className="min-w-0 flex-1 truncate" title={item.name}>{item.name}</span>
      <span className="shrink-0 font-mono text-xs tabular-nums text-muted-foreground">{item.symbol}</span>
    </label>
  </li>
  return <Popover open={open} onOpenChange={changeOpen}>
    <PopoverTrigger asChild>
      <Button type="button" variant="outline" size="icon" className="size-7 shrink-0 rounded-md text-primary"
        title={t('priceAdd')} aria-label={t('priceAdd')}><ListChecks aria-hidden className="size-4" /></Button>
    </PopoverTrigger>
    <PopoverContent align="end" collisionPadding={12} aria-label={t('priceAdd')}
      className="w-96 max-w-[calc(100vw-1.5rem)] p-2.5">
      <Tabs value={kind} onValueChange={value => {
        if (value !== 'etf' && value !== 'index') return
        setKind(value)
        setQuery('')
        if (list.current) list.current.scrollTop = 0
      }}>
      <TabsList aria-label={t('priceInstrumentTypes')} className="grid h-8 w-full grid-cols-2">
        <TabsTrigger value="index" className="h-full text-xs">{t('priceIndexTab')}</TabsTrigger>
        <TabsTrigger value="etf" className="h-full text-xs">ETF</TabsTrigger>
      </TabsList>
      <TabsContent value={kind} className="mt-2">
      <div className="relative">
        <Search aria-hidden className="pointer-events-none absolute left-2.5 top-2.5 size-4 text-muted-foreground" />
        <Input type="search" className="h-9 pl-8" maxLength={80} value={query} placeholder={searchLabel}
          aria-label={searchLabel} aria-controls={listId}
          onChange={event => { setQuery(event.target.value); if (list.current) list.current.scrollTop = 0 }}
          onKeyDown={event => {
            if (event.nativeEvent.isComposing) return
            if (event.key === 'ArrowDown') {
              const first = list.current?.querySelector<HTMLInputElement>('input[type="checkbox"]')
              if (!first) return
              event.preventDefault()
              first.focus()
            } else if (event.key === 'Enter' && search && results.length === 1) {
              event.preventDefault()
              onChange(results[0], !selected.has(priceInstrumentKey(results[0])))
            }
          }} />
      </div>
      <div className="flex justify-between px-2 pt-2 text-xs tabular-nums text-secondary-foreground">
        <span>{current && !current.error ? t(search ? 'priceMatching' : kind === 'index' ? 'priceIndexCatalogTotal' : 'priceCatalogTotal', { count: results.length }) : ''}</span>
        {search && shown !== checked.length && <span>{t('priceVisibleCount', { count: shown })}</span>}
      </div>
      <ul ref={list} id={listId} aria-label={t('priceChecklist')} className="scrollbar mt-1.5 max-h-[min(22rem,45vh)] overflow-y-auto overscroll-contain">
        {[
          ...(checked.length ? [<li key="selected-group-heading" className="px-2.5 pb-0.5 pt-1">
            <h3 className="flex items-center gap-1.5 text-xs font-medium text-secondary-foreground">
              {t('priceCheckedGroup')}
              <span className="rounded bg-muted px-1.5 py-0.5 text-[11px] leading-none tabular-nums">{checked.length}</span>
            </h3>
          </li>, ...checked.map(renderItem)] : []),
          ...(checked.length && unchecked.length ? [<li key="selection-divider" role="presentation" className="px-2.5 py-1.5">
            <div role="separator" className="border-t border-border" />
          </li>] : []),
          ...unchecked.map(renderItem),
        ]}
      </ul>
      {(!results.length || !current || current.error) && <div className="flex items-center justify-between gap-2 px-2.5 py-1 text-xs text-secondary-foreground">
        <p role="status">{t(!current ? 'priceSearching' : current.error ?? 'priceSearchEmpty')}</p>
        {current?.error && <Button type="button" size="sm" variant="ghost" className="h-6 px-2 text-xs"
          onClick={() => { setResponse(undefined); setRetry(value => value + 1) }}>{t('retry')}</Button>}
      </div>}
      </TabsContent>
      </Tabs>
    </PopoverContent>
  </Popover>
}

export function EtfPriceStrip({ selection }: { selection: Selection }) {
  const { t } = useTranslation('etf')
  const scroller = useRef<HTMLDivElement>(null)
  const activeItem = useRef<HTMLSpanElement>(null)
  const visible = new Set(selection.visible)
  const latestVisible = selection.visible[selection.visible.length - 1]
  const previousVisible = useRef<string[]>([])
  const [edges, setEdges] = useState({ left: false, right: false })
  const updateEdges = () => {
    const element = scroller.current
    if (!element) return
    const next = { left: element.scrollLeft > 1, right: element.scrollWidth - element.clientWidth - element.scrollLeft > 1 }
    setEdges(previous => previous.left === next.left && previous.right === next.right ? previous : next)
  }
  useLayoutEffect(() => {
    const element = scroller.current
    if (!element) return
    const observer = new ResizeObserver(updateEdges)
    observer.observe(element)
    if (element.firstElementChild) observer.observe(element.firstElementChild)
    updateEdges()
    return () => observer.disconnect()
  }, [selection.visible.length])
  useLayoutEffect(() => {
    const prior = previousVisible.current
    previousVisible.current = selection.visible
    if (prior.includes(latestVisible)) return
    const element = scroller.current
    const tab = activeItem.current
    if (!element || !tab) return
    const outer = element.getBoundingClientRect()
    const inner = tab.getBoundingClientRect()
    if (inner.right > outer.right) element.scrollLeft += inner.right - outer.right
    else if (inner.left < outer.left) element.scrollLeft -= outer.left - inner.left
    updateEdges()
  }, [latestVisible, selection.visible])
  const scroll = (direction: number) => {
    const element = scroller.current
    element?.scrollBy({ left: direction * element.clientWidth * .8,
      behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' })
  }
  if (!selection.visible.length) return null
  const overflow = edges.left || edges.right
  return <div className="mx-4 flex min-w-0 items-center gap-1 sm:mx-6">
    {overflow && <Button type="button" size="icon" variant="ghost" className="size-7 shrink-0 text-muted-foreground" disabled={!edges.left}
      title={t('priceScrollLeft')} aria-label={t('priceScrollLeft')} onClick={() => scroll(-1)}><ChevronLeft aria-hidden className="size-4" /></Button>}
    <div ref={scroller} onScroll={updateEdges} role="group" aria-label={t('priceSelected')}
      className="scrollbar-none min-w-0 flex-1 overflow-x-auto">
      <div className="mx-auto flex w-max items-center gap-x-3 px-0.5">
        {selection.items.map((item, index) => {
          const key = priceInstrumentKey(item)
          if (!visible.has(key)) return null
          const color = { '--price-light': etfPriceColor(index, false), '--price-dark': etfPriceColor(index, true) } as CSSProperties
          return <span key={key} ref={key === latestVisible ? activeItem : undefined} style={color}
            title={`${item.name} · ${item.symbol}`}
            className="etf-price-chip inline-flex min-h-7 shrink-0 items-center gap-1.5 px-0.5 text-xs text-secondary-foreground">
            <i aria-hidden className="h-0.5 w-4 shrink-0 rounded bg-[var(--price-color)]" />
            <span className="max-w-[min(65vw,16rem)] truncate">{item.name}</span>
          </span>
        })}
      </div>
    </div>
    {overflow && <Button type="button" size="icon" variant="ghost" className="size-7 shrink-0 text-muted-foreground" disabled={!edges.right}
      title={t('priceScrollRight')} aria-label={t('priceScrollRight')} onClick={() => scroll(1)}><ChevronRight aria-hidden className="size-4" /></Button>}
  </div>
}
