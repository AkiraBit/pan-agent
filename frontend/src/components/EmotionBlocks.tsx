import { useState, type ReactNode } from 'react'
import { ArrowRight, Clock3, ExternalLink, Link2 } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Button } from '@panwatch/base-ui/components/ui/button'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@panwatch/base-ui/components/ui/select'
import type { Claim, Cycle, EmotionBlock, EmotionPublication, EmotionWorkspace, Evidence } from '@panwatch/api/emotion'
import { formatDate, formatNumber } from '@/i18n/format'

export const emotionStamp = (value: string | null) => value ? formatDate(value, { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', timeZoneName: 'short' }) : '—'
const number = (value: number | null | undefined) => value == null ? '—' : formatNumber(value, { maximumFractionDigits: 2 })
const change = (value: number | null) => value == null ? '—' : `${value > 0 ? '+' : ''}${number(value)}%`
const direction = (value: number | null) => value == null ? 'text-muted-foreground' : value > 0 ? 'text-market-up' : value < 0 ? 'text-market-down' : 'text-muted-foreground'
export function EmotionCard({ title, children, extra }: { title: string; children: ReactNode; extra?: ReactNode }) {
  return <section className="rounded-2xl border bg-card min-w-0 overflow-hidden"><div className="px-5 py-4 border-b flex flex-wrap items-center justify-between gap-3"><h2 className="font-semibold text-sm break-words">{title}</h2>{extra}</div><div className="p-5">{children}</div></section>
}
function Pill({ children }: { children: ReactNode }) { return <span className="inline-flex rounded-md border bg-accent/50 px-2 py-1 text-[11px] leading-4 text-muted-foreground">{children}</span> }
type Props = { block: EmotionBlock; publication: EmotionPublication; workspace: EmotionWorkspace; stock: string | null; onEvidence: (e: Evidence) => void; onStock: (symbol: string) => void; onPublication: (id: string) => void }

function CycleDiagram({ cycle, publication, onStock }: { cycle: Cycle; publication: EmotionPublication; onStock: (s: string) => void }) {
  const { t } = useTranslation('emotion')
  const nodes = cycle.symbols.map((symbol, i) => ({ symbol, x: 30 + (i % 3) * 240, y: 30 + Math.floor(i / 3) * 120 }))
  return <div className="overflow-x-auto scrollbar rounded-xl bg-accent/20 border"><svg viewBox={`0 0 750 ${Math.ceil(nodes.length / 3) * 120 + 10}`} className="w-full min-w-[640px]" role="img" aria-label={cycle.name}>
    {cycle.relations.map((edge, i) => { const a = nodes.find(n => n.symbol === edge.source), b = nodes.find(n => n.symbol === edge.target); if (!a || !b) return null; return <line key={i} x1={a.x + 100} y1={a.y + 40} x2={b.x + 100} y2={b.y + 40} className="stroke-primary/30" strokeWidth={1.5} strokeDasharray={edge.kind === 'business_relation' ? undefined : '5 5'}><title>{`${t(`relationKinds.${edge.kind}` as 'relationKinds.relay_hypothesis')}: ${edge.explanation}`}</title></line> })}
    {nodes.map(n => { const q = publication.facts.quotes.find(q => q.symbol === n.symbol); return <g key={n.symbol} role="button" tabIndex={0} aria-label={q?.name || n.symbol} onClick={() => onStock(n.symbol)} onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onStock(n.symbol) } }} className="cursor-pointer focus:outline-none [&:focus-visible_rect]:stroke-primary">
      <rect x={n.x} y={n.y} width={205} height={80} rx={12} className="fill-card stroke-border" strokeWidth={1.5} />
      <text x={n.x + 14} y={n.y + 27} className="fill-foreground text-[14px] font-medium">{q?.name || n.symbol}</text>
      <text x={n.x + 14} y={n.y + 51} className="fill-muted-foreground text-[10px]">{n.symbol}</text>
      <text x={n.x + 190} y={n.y + 64} textAnchor="end" className={`${direction(q?.change_pct ?? null)} fill-current text-[12px]`}>{change(q?.change_pct ?? null)}</text>
    </g> })}
  </svg></div>
}

export default function EmotionBlockRenderer({ block, publication: p, workspace, stock, onEvidence, onStock, onPublication }: Props) {
  const { t } = useTranslation('emotion')
  const [window, setWindow] = useState('all')
  const [scenario, setScenario] = useState<string | null>(null)
  const [evidenceFilter, setEvidenceFilter] = useState('all')
  const a = p.analysis
  const subset = <T,>(items: T[], key: (v: T) => string) => block.entity_ids.length ? items.filter(v => block.entity_ids.includes(key(v))) : items
  const refs = (ids: string[]) => <div className="flex flex-wrap gap-1 mt-3">{ids.map(id => { const e = p.facts.evidence.find(e => e.id === id); return e ? <Button key={id} variant="ghost" size="sm" className="h-auto text-xs text-primary px-2 py-1.5 whitespace-normal text-left" onClick={() => onEvidence(e)}><Link2 className="w-3 h-3 mr-1 shrink-0" />{e.title}</Button> : null })}</div>
  const claims = (items: Claim[]) => <ul className="space-y-3">{items.map((c, i) => <li key={i} className="text-sm leading-7 break-words">{c.text}{refs(c.evidence_ids)}</li>)}</ul>
  let content: ReactNode
  switch (block.kind) {
    case 'verdict':
      return <section className="rounded-2xl border border-primary/25 bg-gradient-to-br from-primary/10 to-card p-6"><Pill>{t(`stages.${a.stage}`)}</Pill><h2 className="mt-4 text-2xl font-semibold tracking-tight leading-snug break-words">{a.title}</h2><p className="mt-3 text-sm text-muted-foreground leading-7 break-words">{a.summary}</p><div className="grid md:grid-cols-2 gap-6 mt-5 pt-5 border-t border-primary/15"><div><h3 className="text-xs font-semibold mb-3 text-primary">{t('supports')}</h3>{claims(a.supports)}</div><div><h3 className="text-xs font-semibold mb-3">{t('counters')}</h3>{claims(a.counters)}</div></div></section>
    case 'market': {
      const m = p.facts.snapshot.market, counts = p.facts.snapshot.sentiment.counts
      content = <><p className="text-xs text-muted-foreground mb-4">{t('scope')} · {t('coverage', { count: p.facts.coverage.count, expected: p.facts.coverage.expected ?? '—' })}</p><div className="grid grid-cols-2 lg:grid-cols-5 gap-3">{[['marketUp', m.valid ? m.rising : null], ['marketDown', m.valid ? m.falling : null], ['limitUp', counts.up], ['limitDown', counts.down], ['broken', counts.broken]].map(([key, value]) => <div key={String(key)} className="rounded-xl bg-accent/40 p-4"><p className="text-xs text-muted-foreground">{t(key as 'marketUp')}</p><p className="mt-2 text-2xl font-semibold tabular-nums">{number(value as number | null)}</p></div>)}</div><p className="mt-4 text-xs text-muted-foreground">{t('valid', { count: m.valid })} · {t('marketDate', { date: p.market_as_of })}</p></>
      break
    }
    case 'cycles':
      content = <div className="space-y-8">{subset(a.cycles, c => c.id).map(c => <article key={c.id}><div className="flex flex-wrap items-center gap-3"><h3 className="font-semibold">{c.name}</h3><Pill>{t(`stages.${c.stage}`)}</Pill></div><p className="my-4 text-sm leading-7 text-muted-foreground">{c.summary}</p><CycleDiagram cycle={c} publication={p} onStock={onStock} />{refs(c.evidence_ids)}{c.relations.length > 0 && <details className="mt-4"><summary className="cursor-pointer text-sm font-medium">{t('relationships')}</summary><div className="mt-3 space-y-4">{c.relations.map((r, i) => <div key={i} className="rounded-xl border p-4"><div className="flex flex-wrap items-center gap-2 text-xs"><span>{r.source}</span><ArrowRight className="w-3 h-3" /><span>{r.target}</span><Pill>{t(`relationKinds.${r.kind}` as 'relationKinds.relay_hypothesis')}</Pill></div><p className="text-sm mt-2 leading-7">{r.explanation}</p>{refs(r.evidence_ids)}</div>)}</div></details>}</article>)}{!a.cycles.length && <p className="text-sm text-muted-foreground">{t('noCycles')}</p>}</div>
      break
    case 'watchlist': {
      const items = subset(a.watchlist, s => s.symbol)
      const selected = items.find(s => s.symbol === stock) || items[0]
      content = block.page === 'stock' && selected ? <>
        <div className="flex gap-2 overflow-x-auto scrollbar pb-3">{items.map(s => <Button key={s.symbol} variant={selected.symbol === s.symbol ? 'secondary' : 'ghost'} size="sm" onClick={() => onStock(s.symbol)}>{p.facts.quotes.find(q => q.symbol === s.symbol)?.name || s.symbol}</Button>)}</div>
        {(() => { const q = p.facts.quotes.find(q => q.symbol === selected.symbol)!; return <div className="mt-4"><div className="flex justify-between gap-4"><div><Pill>{selected.role}</Pill><h3 className="text-2xl font-semibold mt-3">{q.name}</h3><p className="text-xs text-muted-foreground mt-1">{selected.symbol}</p></div><div className="text-right"><p className="text-3xl font-semibold tabular-nums">{number(q.price)}</p><p className={`mt-2 tabular-nums ${direction(q.change_pct)}`}>{change(q.change_pct)}</p></div></div><p className="mt-6 text-sm leading-7">{selected.thesis}</p><div className="mt-5 rounded-xl border bg-accent/20 p-4"><h4 className="text-xs font-medium">{t('invalidates')}</h4><p className="text-sm leading-7 mt-2 text-muted-foreground">{selected.invalidation}</p></div><p className="text-xs mt-4 text-muted-foreground">{q.source} · {t('sourceTime', { time: emotionStamp(q.source_time) })} · {t(`evidenceStates.${q.quality}` as 'evidenceStates.available')}</p>{refs(selected.evidence_ids)}</div> })()}
      </> : <div className="overflow-x-auto scrollbar"><table className="w-full text-sm"><thead className="text-xs text-muted-foreground"><tr>{['name', 'role', 'price', 'change', 'next'].map(k => <th key={k} className="text-left font-normal px-3 pb-3 whitespace-nowrap">{t(k as 'name')}</th>)}</tr></thead><tbody>{items.map(s => { const q = p.facts.quotes.find(q => q.symbol === s.symbol)!; return <tr key={s.symbol} className="border-t"><td className="p-3"><button className="text-left text-primary font-medium whitespace-nowrap focus-visible:ring-2 focus-visible:ring-primary rounded" onClick={() => onStock(s.symbol)}>{q.name}<span className="block text-[11px] font-normal text-muted-foreground mt-1">{s.symbol}</span></button></td><td className="p-3 min-w-24"><Pill>{s.role}</Pill></td><td className="p-3 tabular-nums whitespace-nowrap">{number(q.price)}</td><td className={`p-3 tabular-nums whitespace-nowrap ${direction(q.change_pct)}`}>{change(q.change_pct)}</td><td className="p-3 min-w-64 max-w-md text-xs leading-6 text-muted-foreground">{s.thesis}</td></tr> })}</tbody></table></div>
      break
    }
    case 'scenarios': {
      const items = subset(a.scenarios, s => s.id), selected = items.find(s => s.id === scenario) || items[0]
      content = <><p className="text-xs text-muted-foreground mb-4">{t('scenarioHint')}</p><div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-3">{items.map((s, i) => <button key={s.id} aria-pressed={s.id === selected?.id} onClick={() => setScenario(s.id)} className={`text-left p-4 rounded-xl border focus-visible:ring-2 focus-visible:ring-primary ${s.id === selected?.id ? 'border-primary/50 bg-primary/10' : 'bg-accent/20 hover:bg-accent/40'}`}><span className="text-xs text-muted-foreground tabular-nums">{String(i + 1).padStart(2, '0')}</span><h3 className="font-semibold mt-3 text-sm">{s.title}</h3><p className="text-xs leading-6 text-muted-foreground mt-2">{s.thesis}</p></button>)}</div>{selected && <div className="mt-5 border-t pt-5 space-y-5"><div className="grid md:grid-cols-2 gap-6"><div><h3 className="text-xs font-semibold mb-3">{t('supports')}</h3>{claims(selected.supports)}</div><div><h3 className="text-xs font-semibold mb-3">{t('counters')}</h3>{claims(selected.counters)}</div></div><div className="rounded-xl bg-accent/30 p-4"><h3 className="text-xs font-semibold">{t('invalidates')}</h3><p className="text-sm leading-7 mt-2">{selected.invalidation}</p></div><div className="flex flex-wrap gap-2">{selected.condition_ids.map(id => <Pill key={id}>{a.conditions.find(c => c.id === id)?.title}</Pill>)}</div></div>}</>
      break
    }
    case 'conditions':
      content = <><div className="flex gap-2 flex-wrap mb-4"><Button size="sm" variant={window === 'all' ? 'secondary' : 'ghost'} onClick={() => setWindow('all')}>{t('allWindows')}</Button>{(['premarket', 'auction', 'opening', 'afternoon', 'close', 'next_session'] as const).map(w => <Button key={w} size="sm" variant={window === w ? 'secondary' : 'ghost'} onClick={() => setWindow(w)}>{t(`windows.${w}`)}</Button>)}</div><p className="text-xs text-muted-foreground mb-5 leading-6">{t('conditionHint')}</p><div className="space-y-4">{subset(a.conditions, c => c.id).filter(c => (window === 'all' || c.window === window) && (block.page !== 'stock' || !stock || !c.subject || c.subject === stock)).map(c => { const state = p.condition_states.find(s => s.id === c.id); return <article key={c.id} className="rounded-xl border p-4"><div className="flex flex-wrap items-start justify-between gap-3"><div><span className="text-[11px] text-primary">{t(`windows.${c.window}`)}</span><h3 className="font-medium text-sm mt-1">{c.title}</h3></div><Pill>{t(`states.${state?.state || 'unknown'}`)}</Pill></div><p className="text-sm leading-7 mt-3">{c.criterion}</p><p className="text-xs leading-6 text-muted-foreground mt-2">{t('invalidates')}：{c.invalidation}</p>{state && <p className="text-xs text-muted-foreground mt-3 flex items-start gap-1"><Clock3 className="w-3 h-3 mt-0.5 shrink-0" />{t(`reasons.${state.reason}` as 'reasons.window_not_reached')} · {emotionStamp(state.observed_at)}</p>}{refs(c.evidence_ids)}</article> })}</div></>
      break
    case 'evidence':
      content = <><Select value={evidenceFilter} onValueChange={setEvidenceFilter}><SelectTrigger className="w-56 max-w-full mb-4" aria-label={t('openEvidence')}><SelectValue /></SelectTrigger><SelectContent><SelectItem value="all">{t('pages.evidence')}</SelectItem>{['user_unverified', 'reported', 'prior_hypothesis', 'unavailable', 'stale'].map(v => <SelectItem key={v} value={v}>{t(`evidenceStates.${v}` as 'evidenceStates.reported')}</SelectItem>)}</SelectContent></Select><div className="divide-y">{subset(p.facts.evidence, e => e.id).filter(e => evidenceFilter === 'all' || e.status === evidenceFilter).map(e => <button key={e.id} className="w-full py-4 text-left rounded focus-visible:ring-2 focus-visible:ring-primary" onClick={() => onEvidence(e)}><div className="flex flex-wrap gap-2 items-center justify-between"><h3 className="text-sm font-medium">{e.title}</h3><Pill>{t(`evidenceStates.${e.status}` as 'evidenceStates.observed')}</Pill></div><p className="text-xs text-muted-foreground mt-2">{e.source} · {emotionStamp(e.published_at || e.observed_at)} <ExternalLink className="inline-block w-3 h-3 ml-1" /></p></button>)}</div></>
      break
    case 'memory':
      content = <><p className="text-sm leading-7 whitespace-pre-wrap">{a.memory_summary}</p><h3 className="text-xs font-semibold mt-5 mb-3">{t('questions')}</h3><ul className="space-y-2 list-disc pl-4 text-sm leading-7 text-muted-foreground">{a.open_questions.map((q, i) => <li key={i}>{q}</li>)}</ul><h3 className="text-xs font-semibold mt-6 mb-3">{t('memoryInput')} · {p.memory_input.length}</h3><div className="space-y-3">{p.memory_input.map(m => <article key={m.publication_id} className="rounded-xl border p-4"><Button variant="link" className="h-auto p-0" onClick={() => onPublication(m.publication_id)}>{t('version', { version: m.revision })} · {m.target_trade_date}</Button><p className="mt-2 text-xs leading-6 text-muted-foreground">{m.summary}</p></article>)}{!p.memory_input.length && <p className="text-sm text-muted-foreground">{t('noMemory')}</p>}</div><p className="mt-5 text-xs text-muted-foreground border-t pt-4">{t('noResult')}</p></>
      break
    case 'changes':
      content = <div className="space-y-4">{a.changes.map((text, i) => <div key={i} className="flex gap-3"><span className="mt-2 h-2 w-2 rounded-full bg-primary shrink-0" /><p className="text-sm leading-7">{text}</p></div>)}</div>
      break
    case 'data_quality':
      content = <><p className="text-xs text-muted-foreground leading-6 mb-4">{t('capabilityHint')}</p><div className="divide-y">{Object.entries(p.facts.capabilities).map(([key, value]) => <div key={key} className="flex flex-wrap justify-between gap-2 py-3 text-sm"><span>{t(`capabilities.${key}` as 'capabilities.auction')}</span><Pill>{value ? t('evidenceStates.available') : t('unavailable')}</Pill></div>)}</div><p className="mt-4 text-xs text-muted-foreground">{t('coverage', { count: p.facts.coverage.count, expected: p.facts.coverage.expected ?? '—' })} · {t(`evidenceStates.${p.facts.coverage.status}` as 'evidenceStates.complete')}</p></>
      break
    case 'runs':
      content = <div className="space-y-4">{workspace.runs.map(r => <details key={r.id} className="rounded-xl border p-4" open={r.status === 'running'}><summary className="cursor-pointer text-sm"><span className="font-medium">{r.target_trade_date}</span><span className="ml-3 text-xs text-muted-foreground">{t(`runStates.${r.status}`)} · {emotionStamp(r.created_at)}</span></summary><p className="mt-3 text-xs text-muted-foreground">{t('model')}：{r.model_label || '—'}</p><div className="mt-3 space-y-3">{r.events.map(e => <div key={e.seq} className="flex flex-wrap justify-between gap-2 text-xs"><span>{t(`eventTypes.${e.type}` as 'eventTypes.step_updated')}{e.data.tool_name ? ` · ${String(e.data.tool_name)}` : ''}</span><time className="text-muted-foreground">{emotionStamp(e.at)}</time></div>)}</div>{r.publication_id && <Button size="sm" variant="link" className="mt-3 p-0" onClick={() => onPublication(r.publication_id!)}>{t('originalPlan')}</Button>}</details>)}{!workspace.runs.length && <p className="text-sm text-muted-foreground">{t('noRuns')}</p>}</div>
      break
    default:
      content = <p className="text-sm text-muted-foreground">{t('unknownBlock')}</p>
  }
  return <EmotionCard title={block.title}>{content}</EmotionCard>
}
