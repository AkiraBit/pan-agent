import { useMemo, useRef, useState } from 'react'
import { ChevronRight, Search, X } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import type { FtshareTier } from '@panwatch/api'
import { Button } from '@panwatch/base-ui/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from '@panwatch/base-ui/components/ui/dialog'
import { Input } from '@panwatch/base-ui/components/ui/input'
import { FtshareTierBadge } from '@/components/FtshareParameters'
import { endpointSearchTokens, matchesEndpointSearch, normalizeEndpointTerm } from '@/lib/data-source-search'

export interface EndpointSearchEntry {
  id: number
  name: string
  provider: string
  detail: string
  path?: string
  operationId?: string
  tier?: FtshareTier
  index: string[]
}

export function EndpointSearchInput({ value, label, onChange, clearLabel }: {
  value: string; label: string; onChange: (value: string) => void; clearLabel?: string
}) {
  const input = useRef<HTMLInputElement>(null)
  return <div className="relative min-w-0">
    <Search aria-hidden="true" className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
    <Input ref={input} type="search" autoComplete="off" aria-label={label} placeholder={label}
      value={value} onChange={event => onChange(event.target.value)}
      className={clearLabel ? 'h-8 pl-8 pr-8 text-xs [&::-webkit-search-cancel-button]:hidden' : 'h-8 pl-8 text-xs'} />
    {clearLabel && value && <Button type="button" variant="ghost" size="icon" aria-label={clearLabel}
      className="absolute right-0.5 top-0.5 size-7 text-muted-foreground" onClick={() => { onChange(''); input.current?.focus() }}>
      <X className="size-3.5" aria-hidden="true" />
    </Button>}
  </div>
}

export function DataSourcesGlobalSearch({ entries, disabled, onSelect }: {
  entries: EndpointSearchEntry[]
  disabled: boolean
  onSelect: (id: number) => void
}) {
  const { t } = useTranslation('configuration')
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const selected = useRef<number | null>(null)
  const { hasQuery, matches } = useMemo(() => {
    const tokens = endpointSearchTokens(query)
    const term = normalizeEndpointTerm(query)
    const score = (entry: EndpointSearchEntry) => {
      const name = normalizeEndpointTerm(entry.name)
      const id = normalizeEndpointTerm(entry.operationId ?? '')
      if (term === name || term === id) return 0
      if (name.startsWith(term) || id.startsWith(term)) return 1
      if (name.includes(term)) return 2
      return 3
    }
    return { hasQuery: tokens.length > 0, matches: tokens.length ? entries.filter(entry => matchesEndpointSearch(entry.index, tokens))
      .sort((a, b) => score(a) - score(b) || a.id - b.id) : [] }
  }, [entries, query])

  const openMatch = (id: number) => {
    selected.current = id
    setOpen(false)
  }

  return <Dialog open={open} onOpenChange={next => {
    if (next) setQuery('')
    setOpen(next)
  }}>
    <DialogTrigger asChild><Button type="button" variant="outline" size="sm" disabled={disabled}>
      <Search aria-hidden="true" className="size-4" />{t('dataSources.search.global')}
    </Button></DialogTrigger>
    <DialogContent className="max-w-xl" onCloseAutoFocus={event => {
      if (selected.current === null) return
      const id = selected.current
      selected.current = null
      event.preventDefault()
      onSelect(id)
    }}>
      <DialogHeader className="mb-2 pr-8">
        <DialogTitle>{t('dataSources.search.global')}</DialogTitle>
        <DialogDescription>{t('dataSources.search.description')}</DialogDescription>
      </DialogHeader>
      <form onSubmit={event => {
        event.preventDefault()
        if (matches[0]) openMatch(matches[0].id)
      }}>
        <EndpointSearchInput value={query} label={t('dataSources.search.query')} onChange={setQuery} />
      </form>
      {hasQuery && !matches.length && <p role="status" className="text-sm text-muted-foreground">{t('fuyao.rest.empty')}</p>}
      {!!matches.length && <ul key={query} className="scrollbar max-h-[52dvh] space-y-1 overflow-y-auto overscroll-contain">
        {matches.map(entry => <li key={entry.id}>
          <Button type="button" variant="ghost" onClick={() => openMatch(entry.id)}
            className="h-auto w-full min-w-0 justify-between gap-2 whitespace-normal px-3 py-2 text-left">
            <span className="min-w-0">
              <span className="flex flex-wrap items-center gap-1.5">
                <span className="break-words text-[13px] font-semibold">{entry.name}</span>
                {entry.tier && <FtshareTierBadge tier={entry.tier} />}
              </span>
              <span className="mt-0.5 block break-words text-xs font-normal text-muted-foreground">{entry.provider} · {entry.detail}</span>
              {entry.path && <code className="mt-0.5 block break-all text-[11px] font-normal text-muted-foreground">{entry.path}</code>}
            </span>
            <ChevronRight aria-hidden="true" className="size-4 shrink-0 text-muted-foreground" />
          </Button>
        </li>)}
      </ul>}
    </DialogContent>
  </Dialog>
}
