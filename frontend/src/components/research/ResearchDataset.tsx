import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { marketSignTextClass } from '@/lib/market-colors'

export type Row = Record<string, unknown>
export type ResearchLink = { label: string; to: string }
export const asRow = (value: unknown): Row | null =>
  value !== null && typeof value === 'object' && !Array.isArray(value) ? value as Row : null
export const rowList = (value: unknown): Row[] => Array.isArray(value) ? value.map(asRow).filter((item): item is Row => item !== null) : []
export const isComplex = (value: unknown) => value !== null && typeof value === 'object'
const CN = 'Asia/Shanghai'
const PAGE_SIZE = 20
const COLORS = ['#2563eb', '#10b981', '#a855f7', '#f59e0b', '#e11d48', '#0e7490', '#4f46e5', '#64748b', '#84cc16', '#f97316']

export function exchangeDate(ms: number, withTime = false) {
  if (ms < 100_000_000_000 || ms > 10_000_000_000_000) return String(ms)
  return new Intl.DateTimeFormat('sv-SE', {
    timeZone: CN, year: 'numeric', month: '2-digit', day: '2-digit',
    ...(withTime ? { hour: '2-digit', minute: '2-digit', hourCycle: 'h23' as const } : {}),
  }).format(ms)
}

export function formatCell(value: unknown, key: string, locale: string) {
  if (value == null) return '—'
  if (typeof value === 'number') {
    if (key.endsWith('_ms') || key.endsWith('_date') || key === 'timestamp') return exchangeDate(value, !key.includes('date'))
    return new Intl.NumberFormat(locale, { maximumFractionDigits: 6 }).format(value)
  }
  return typeof value === 'string' || typeof value === 'boolean' ? String(value) : '—'
}

export function fieldLabel(key: string, t: (key: string, options?: { defaultValue: string }) => string) {
  return t(`researchData.fields.${key}`, { defaultValue: key.replace(/_/g, ' ') })
}

function Nested({ label, value, actions }: { label: string; value: unknown; actions?: (row: Row) => ResearchLink[] }) {
  const [open, setOpen] = useState(false)
  return <details onToggle={event => setOpen(event.currentTarget.open)} className="rounded-lg border border-border/60 p-3">
    <summary className="cursor-pointer text-sm font-medium">{label}{Array.isArray(value) ? ` · ${value.length}` : ''}</summary>
    {open && <div className="mt-3"><ResearchDataset value={value} actions={actions} /></div>}
  </details>
}

function DatasetTable({ rows, actions }: { rows: Row[]; actions?: (row: Row) => ResearchLink[] }) {
  const { t: typed, i18n } = useTranslation('configuration')
  const t = typed as (key: string, options?: { defaultValue: string }) => string
  const [page, setPage] = useState(0)
  const pages = Math.max(1, Math.ceil(rows.length / PAGE_SIZE))
  const current = Math.min(page, pages - 1)
  const visible = rows.slice(current * PAGE_SIZE, (current + 1) * PAGE_SIZE)
  const columns = [...new Set(visible.flatMap(row => Object.keys(row).filter(key => !isComplex(row[key]))))]
  const hasDetails = visible.some(row => Object.values(row).some(isComplex))
  const links = visible.map(row => actions?.(row) ?? [])
  const hasActions = links.some(link => link.length)
  return <div className="space-y-3">
    <div className="scrollbar overflow-x-auto rounded-lg border border-border/60">
      <table className="w-full border-collapse text-left text-xs">
        <thead className="bg-muted/60"><tr>
          {columns.map(key => <th className="whitespace-nowrap px-3 py-2 font-semibold" key={key} scope="col">{fieldLabel(key, t)}</th>)}
          {hasActions && <th className="whitespace-nowrap px-3 py-2" scope="col">{t('researchData.drilldown')}</th>}
          {hasDetails && <th className="px-3 py-2" scope="col">{t('researchData.details')}</th>}
        </tr></thead>
        <tbody>{visible.map((row, index) => <tr key={index} className="border-t border-border/50 align-top hover:bg-muted/30">
          {columns.map(key => <td key={key} className="max-w-[22rem] break-words px-3 py-2 tabular-nums">
            {key === 'url' && typeof row[key] === 'string' && row[key].startsWith('https://')
              ? <a className="text-primary hover:underline" href={row[key]} target="_blank" rel="noopener noreferrer">{t('researchData.sourceArticle')}</a>
              : formatCell(row[key], key, i18n.language)}
          </td>)}
          {hasActions && <td className="min-w-24 px-3 py-2"><div className="flex flex-wrap gap-2">{links[index].map(link =>
            <Link key={link.to} to={link.to} className="whitespace-nowrap text-primary hover:underline">{link.label}</Link>
          )}</div></td>}
          {hasDetails && <td className="min-w-40 px-3 py-2">
            {Object.entries(row).filter(([, value]) => isComplex(value)).map(([key, value]) =>
              <Nested key={key} label={fieldLabel(key, t)} value={value} actions={actions} />)}
          </td>}
        </tr>)}</tbody>
      </table>
    </div>
    {pages > 1 && <div className="flex items-center justify-end gap-3 text-xs">
      <button type="button" onClick={() => setPage(current - 1)} disabled={current === 0} className="rounded border px-2 py-1 disabled:opacity-40">{t('researchData.prev')}</button>
      <span className="tabular-nums">{current + 1} / {pages}</span>
      <button type="button" onClick={() => setPage(current + 1)} disabled={current >= pages - 1} className="rounded border px-2 py-1 disabled:opacity-40">{t('researchData.next')}</button>
    </div>}
  </div>
}

export function ResearchDataset({ value, actions }: {
  value: unknown; actions?: (row: Row) => ResearchLink[]
}) {
  const { t: typed, i18n } = useTranslation('configuration')
  const t = typed as (key: string, options?: { defaultValue: string }) => string
  if (value == null || Array.isArray(value) && !value.length) return <p className="text-sm text-muted-foreground">{t('researchData.empty')}</p>
  if (Array.isArray(value)) {
    const rows = rowList(value)
    if (!rows.length) return <ul className="flex flex-wrap gap-2">{value.map((item, i) =>
      <li key={i} className="rounded border px-2 py-1 text-xs">{formatCell(item, '', i18n.language)}</li>
    )}</ul>
    return <DatasetTable rows={rows} actions={actions} />
  }
  const row = asRow(value)
  if (!row) return <p className="text-sm">{formatCell(value, '', i18n.language)}</p>
  const values = Object.entries(row).filter(([key, item]) => !isComplex(item) && key !== 'timestamp')
  const groups = Object.entries(row).filter(([, item]) => isComplex(item))
  return <div className="min-w-0 space-y-4">
    {!!values.length && <dl className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4">
      {values.map(([key, item]) => <div key={key} className="min-w-0 rounded-lg bg-muted/40 p-3">
        <dt className="text-xs text-muted-foreground">{fieldLabel(key, t)}</dt>
        <dd className="mt-1 break-words text-sm font-medium tabular-nums">{formatCell(item, key, i18n.language)}</dd>
      </div>)}
    </dl>}
    <div className="flex flex-wrap gap-3">{actions?.(row).map(link =>
      <Link key={link.to} to={link.to} className="text-xs text-primary hover:underline">{link.label}</Link>
    )}</div>
    {groups.map(([key, item]) => <div key={key} className="space-y-2">
      {key !== 'item' && <h4 className="text-sm font-semibold">{fieldLabel(key, t)}</h4>}
      <ResearchDataset value={item} actions={actions} />
    </div>)}
    {!values.length && !groups.length && <p className="text-sm text-muted-foreground">{t('researchData.empty')}</p>}
  </div>
}

type Point = { date: string; y: number }
function pointRows(value: unknown, metric: string): Point[] {
  const byDate = new Map<string, number>()
  for (const row of rowList(value)) {
    const rawDate = row.date_ms ?? row.timestamp ?? row.date
    const day = typeof rawDate === 'number' ? exchangeDate(rawDate, metric === 'price') : rawDate
    if (typeof day === 'string' && typeof row[metric] === 'number' && Number.isFinite(row[metric])) byDate.set(day, row[metric])
  }
  return [...byDate].sort(([a], [b]) => a.localeCompare(b)).map(([date, y]) => ({ date, y }))
}

export function ResearchChart({ value, metric, compare }: { value: unknown; metric: string; compare: boolean }) {
  const { t: typed, i18n } = useTranslation('configuration')
  const t = typed as (key: string, options?: { defaultValue: string }) => string
  const root = asRow(value)
  if (!root) return null
  let series = compare
    ? rowList(root.item).map(row => ({ name: String(row.thscode), points: pointRows(row.item, metric) }))
    : [{ name: String(root.thscode ?? fieldLabel(metric, t)), points: pointRows(root.item, metric) }]
  if (metric === 'strategy') {
    const pointMap = asRow(root.curve_points)
    const points = (pointMap ? [pointMap] : rowList(root.curve_points)).flatMap(row => Object.entries(row)
      .filter((p): p is [string, number] => /^\d{4}-\d{2}-\d{2}$/.test(p[0]) && typeof p[1] === 'number' && Number.isFinite(p[1]))
      .map(([date, y]) => ({ date, y }))).sort((a, b) => a.date.localeCompare(b.date))
    series = [{ name: t('researchData.strategyCurve'), points }]
  }
  series = series.filter(s => s.points.length >= 2)
  if (!series.length) return null
  if (compare) {
    const first = series[0].points.find(p => series.every(s => s.points.some(x => x.date === p.date && x.y > 0)))
    if (!first) return null
    series = series.map(s => {
      const base = s.points.find(x => x.date === first.date)!.y
      return { ...s, points: s.points.filter(p => p.date >= first.date).map(p => ({ ...p, y: p.y / base * 100 })) }
    })
  }
  const dates = [...new Set(series.flatMap(s => s.points.map(p => p.date)))].sort()
  const index = new Map(dates.map((date, i) => [date, i]))
  const candles = !compare && metric === 'close_price' ? rowList(root.item).flatMap(row => {
    const timestamp = row.date_ms ?? row.timestamp
    const [open, high, low, close] = [row.open_price, row.high_price, row.low_price, row.close_price]
    if (typeof timestamp !== 'number' || typeof open !== 'number' || typeof high !== 'number'
        || typeof low !== 'number' || typeof close !== 'number') return []
    const date = exchangeDate(timestamp)
    return index.has(date) && [open, high, low, close].every(Number.isFinite) &&
      low <= Math.min(open, close) && high >= Math.max(open, close) ? [{ date, open, high, low, close }] : []
  }) : []
  const useCandles = candles.length >= 2 && candles.length <= 200
  const values = useCandles ? candles.flatMap(bar => [bar.low, bar.high]) : series.flatMap(s => s.points.map(p => p.y))
  const min = values.reduce((a, b) => Math.min(a, b), Infinity)
  const max = values.reduce((a, b) => Math.max(a, b), -Infinity)
  const width = 740, height = 240, margin = 20
  const x = (date: string) => margin + (index.get(date) ?? 0) / Math.max(1, dates.length - 1) * (width - 2 * margin)
  const y = (price: number) => max === min ? height / 2 : margin + (max - price) / (max - min) * (height - 2 * margin)
  const xy = (p: Point) => [
    x(p.date), y(p.y),
  ].join(',')
  const summary = (n: number) => new Intl.NumberFormat(i18n.language, { maximumFractionDigits: 4 }).format(n)
  return <figure className="space-y-2 rounded-xl border border-border/70 p-3">
    <figcaption className="flex flex-wrap items-baseline justify-between gap-2">
      <span className="text-sm font-medium">{t(compare ? 'researchData.commonBase' : 'researchData.trend')}</span>
      <span className="text-xs text-muted-foreground tabular-nums">{summary(min)} – {summary(max)}</span>
    </figcaption>
    <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={t('researchData.trend')} className="w-full">
      {[0, 1, 2, 3, 4].map(i => <line key={i} x1={margin} x2={width - margin} y1={margin + i * 50} y2={margin + i * 50} stroke="currentColor" opacity=".12" />)}
      {useCandles ? candles.map((bar, i) => {
        const center = x(bar.date)
        const body = Math.max(2, Math.min(12, (width - 2 * margin) / dates.length * .6))
        return <g key={i} className={marketSignTextClass(bar.close - bar.open)}>
          <line x1={center} x2={center} y1={y(bar.high)} y2={y(bar.low)} stroke="currentColor" strokeWidth="1.2" />
          <rect x={center - body / 2} y={y(Math.max(bar.open, bar.close))} width={body}
            height={Math.max(1.4, Math.abs(y(bar.open) - y(bar.close)))} fill="currentColor" />
        </g>
      }) : series.map((s, i) => <polyline key={s.name} fill="none" stroke={COLORS[i % COLORS.length]} strokeWidth="2.5"
        points={s.points.filter((_, j) => j % Math.max(1, Math.floor(s.points.length / 300)) === 0 || j === s.points.length - 1).map(xy).join(' ')} />)}
    </svg>
    <div className="flex justify-between text-xs text-muted-foreground tabular-nums"><time>{dates[0]}</time><time>{dates[dates.length - 1]}</time></div>
    {!useCandles && <ul className="flex flex-wrap gap-3 text-xs">{series.map((s, i) => <li key={s.name} className="inline-flex items-center gap-1.5"><span className="h-2 w-2 rounded-full" style={{ backgroundColor: COLORS[i % COLORS.length] }} />{s.name}</li>)}</ul>}
  </figure>
}
