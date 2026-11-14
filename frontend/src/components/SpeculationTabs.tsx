import { useTranslation } from 'react-i18next'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@panwatch/base-ui/components/ui/tabs'
import { formatNumber } from '@/i18n/format'

type Stock = { code: string; name: string; change: number | null; streak: number | null; previous_streak?: number; first_time?: string | null; last_time?: string | null; breaks?: number | null; amount?: number | null; sealed_amount?: number | null; state?: 'promoted' | 'conflict' | 'limit_down' | 'broken' | 'not_sealed' | 'unknown' }
type Theme = { code: string; name: string; complete: boolean; limit_up: number | null; first_boards: number | null; relay_boards: number | null; height: number | null; previous_mean: number | null; core: Stock[]; overlaps: string[] }
type TrendState = 'aligned' | 'above' | 'below' | 'stale' | 'insufficient' | 'invalid'
export type Speculation = {
  relay: { complete: boolean; height: number | null; previous_height: number | null; ungraded_up: number; ungraded_previous: number; ladder: { level: number; count: number; stocks: Stock[] }[]; promotion: { level: number; total: number; promoted: number | null; rate: number | null }[]; anchors: Stock[]; negative_feedback: Stock[] }
  themes: { scanned: number; available: number | null; candidates: Theme[] }
  trends: { code: string; name: string; amount: number; change: number | null; themes: string[]; structure: { state: TrendState; as_of?: string; distance_ma20?: number; ma20_change?: number; drawdown20?: number; return5?: number } }[]
}
const n = (value: number | null | undefined) => value == null ? '—' : formatNumber(value, { maximumFractionDigits: 2 })
const pct = (value: number | null | undefined) => value == null ? '—' : `${n(value)}%`

export default function SpeculationTabs({ data }: { data?: Speculation }) {
  const { t } = useTranslation('shortTerm')
  const money = (amount: number | null | undefined) => amount == null ? '—' : t('spec.money', { value: n(amount / 1e8) })
  const stock = (r: Stock, detailed = false) => <div key={r.code} className="rounded-xl border border-border/60 p-3 space-y-1.5">
    <div className="flex justify-between gap-2 text-sm"><span className="font-medium">{r.name} <span className="text-xs text-muted-foreground">{r.code}</span></span><span className={(r.change ?? 0) > 0 ? 'text-market-up' : (r.change ?? 0) < 0 ? 'text-market-down' : ''}>{pct(r.change)}</span></div>
    {r.state && <p className="text-xs text-primary">{t('spec.previousLevel', { level: n(r.previous_streak) })} · {t(`spec.outcomes.${r.state}`)}</p>}
    {detailed && <><p className="text-xs text-muted-foreground">{t('spec.sealTimes', { first: r.first_time ?? '—', last: r.last_time ?? '—', breaks: n(r.breaks) })}</p><p className="text-xs text-muted-foreground">{t('spec.sealMoney', { sealed: money(r.sealed_amount), amount: money(r.amount) })}</p></>}
  </div>
  return <Tabs defaultValue="themes" className="space-y-4">
    <TabsList aria-label={t('spec.tabsLabel')} className="grid grid-cols-3 gap-2 rounded-2xl bg-accent/40 p-1.5">
      {(['themes', 'relay', 'trend'] as const).map(key => <TabsTrigger key={key} value={key} className="rounded-xl py-3 text-sm font-medium">{t(`spec.tabs.${key}`)}</TabsTrigger>)}
    </TabsList>
    {!data ? <p className="card p-5 text-sm text-muted-foreground">{t('spec.legacy')}</p> : <>
      <div className="grid sm:grid-cols-3 gap-3">
        <div className="card p-4"><p className="text-xs text-muted-foreground">{t('spec.height')}</p><p className="mt-2 text-xl font-semibold tabular-nums">{n(data.relay.previous_height)} → {n(data.relay.height)}</p></div>
        <div className="card p-4"><p className="text-xs text-muted-foreground">{t('spec.anchors')}</p><p className="mt-2 text-sm font-medium">{data.relay.anchors.map(r => r.name).join(' / ') || t('spec.unknown')}</p></div>
        <div className="card p-4"><p className="text-xs text-muted-foreground">{t('spec.cycle')}</p><p className="mt-2 text-sm leading-6">{t('spec.cycleHint')}</p></div>
      </div>
      <p className="text-xs text-muted-foreground leading-6">{t('spec.scope')}</p>
      {!data.relay.complete && <p role="status" className="text-sm text-primary">{t('spec.partial')}</p>}
      <TabsContent value="themes" className="space-y-4">
        <div><h2 className="font-semibold">{t('spec.themeTitle')}</h2><p className="mt-1 text-sm text-muted-foreground leading-6">{t('spec.themeMethod', { scanned: data.themes.scanned, available: n(data.themes.available) })}</p></div>
        <div className="grid lg:grid-cols-2 gap-4">{data.themes.candidates.map(theme => <article key={theme.code} className="card p-5 space-y-4">
          <div className="flex justify-between gap-3"><h3 className="font-semibold">{theme.name}</h3><span className="text-xs text-primary">{theme.complete ? t('spec.candidate') : t('spec.unknown')}</span></div>
          <div className="grid grid-cols-3 gap-2 text-center">{[[t('up'), theme.limit_up], [t('spec.firstBoards'), theme.first_boards], [t('spec.relayBoards'), theme.relay_boards]].map(([label, value]) => <div key={String(label)} className="rounded-xl bg-accent/40 p-3"><p className="text-xs text-muted-foreground">{label}</p><p className="mt-1 text-xl font-semibold">{n(value as number | null)}</p></div>)}</div>
          <p className="text-sm">{t('spec.themeHeight', { height: n(theme.height), change: pct(theme.previous_mean) })}</p>
          <div><p className="text-xs text-muted-foreground mb-2">{t('spec.coreHint')}</p><div className="space-y-2">{theme.core.map(r => <div key={r.code} className="flex flex-wrap justify-between gap-2 text-sm"><span>{r.name} <span className="text-xs text-muted-foreground">{r.code}</span></span><span>{t('spec.level', { level: r.streak ?? 0 })} · {r.first_time ?? '—'}</span></div>)}</div></div>
          {!!theme.overlaps.length && <p className="text-xs text-muted-foreground">{t('spec.overlaps', { names: theme.overlaps.join(' / ') })}</p>}
          <div className="border-t pt-3 text-xs leading-6"><p className="font-medium">{t('spec.catalyst')}</p><p className="text-muted-foreground">{t('spec.themeWatch')}</p></div>
        </article>)}</div>
        {!data.themes.candidates.length && <p className="card p-5">{t('spec.noThemes')}</p>}
      </TabsContent>
      <TabsContent value="relay" className="space-y-5">
        <div className="rounded-2xl bg-primary/5 border border-primary/15 p-4 text-sm leading-7">{t('spec.relayGuide')}</div>
        <section className="card p-5"><h2 className="font-semibold mb-4">{t('spec.promotion')}</h2><div className="grid sm:grid-cols-3 gap-3">{data.relay.promotion.map(r => <div key={r.level} className="rounded-xl bg-accent/40 p-4"><p className="font-medium">{t('spec.advance', { from: r.level, to: r.level + 1 })}</p><p className="mt-2 text-xl font-semibold">{n(r.promoted)} / {r.total}</p><p className="text-xs text-muted-foreground mt-1">{pct(r.rate == null ? null : r.rate * 100)}</p></div>)}</div><p className="mt-3 text-xs text-muted-foreground leading-6">{t('spec.promotionHint', { count: data.relay.ungraded_previous })}</p></section>
        <div className="grid lg:grid-cols-2 gap-5">
          <section className="space-y-3"><h2 className="font-semibold">{t('spec.ladder')}</h2>{data.relay.ladder.map(group => <details key={group.level} open={group.level >= 2} className="card p-4"><summary className="cursor-pointer font-medium text-sm">{t('spec.ladderLevel', { level: group.level, count: group.count })}</summary><div className="mt-3 grid sm:grid-cols-2 lg:grid-cols-1 gap-2">{group.stocks.map(r => stock(r, true))}</div></details>)}<p className="text-xs text-muted-foreground">{t('spec.ungraded', { count: data.relay.ungraded_up })}</p></section>
          <div className="space-y-5"><section className="card p-5 space-y-3"><h2 className="font-semibold">{t('spec.anchorFeedback')}</h2>{data.relay.anchors.map(r => stock(r))}{!data.relay.anchors.length && <p className="text-sm text-muted-foreground">{t('spec.unknown')}</p>}<p className="text-xs text-muted-foreground leading-6">{t('spec.anchorWatch')}</p></section>
            <section className="card p-5 space-y-3"><h2 className="font-semibold">{t('spec.negative')}</h2>{data.relay.negative_feedback.map(r => stock(r))}{!data.relay.negative_feedback.length && <p className="text-sm text-muted-foreground">{t('spec.noNegative')}</p>}<p className="text-xs text-muted-foreground leading-6">{t('spec.sealCaution')}</p></section></div>
        </div>
      </TabsContent>
      <TabsContent value="trend" className="space-y-4">
        <div><h2 className="font-semibold">{t('spec.trendTitle')}</h2><p className="text-sm text-muted-foreground leading-6 mt-1">{t('spec.trendMethod')}</p></div>
        <div className="grid lg:grid-cols-2 gap-4">{data.trends.map(r => <article key={r.code} className="card p-5 space-y-4">
          <div className="flex justify-between gap-2"><h3 className="font-semibold">{r.name} <span className="text-xs text-muted-foreground">{r.code}</span></h3><span className="text-xs text-primary">{t(`spec.trends.${r.structure.state}`)}</span></div>
          <p className="text-xs text-muted-foreground leading-6">{r.themes.join(' / ')}</p>
          <div className="flex flex-wrap justify-between gap-3 text-sm"><span>{t('spec.turnover')} <strong>{money(r.amount)}</strong></span><span>{t('spec.change')} <strong>{pct(r.change)}</strong></span></div>
          <div className="grid grid-cols-2 gap-3 text-sm"><p>{t('spec.ma20')} <strong>{pct(r.structure.distance_ma20)}</strong></p><p>{t('spec.slope')} <strong>{pct(r.structure.ma20_change)}</strong></p><p>{t('spec.drawdown')} <strong>{pct(r.structure.drawdown20)}</strong></p><p>{t('spec.return5')} <strong>{pct(r.structure.return5)}</strong></p></div>
          <p className="text-xs text-muted-foreground">{t('spec.barDate', { date: r.structure.as_of ?? '—' })}</p>
          <div className="border-t pt-3 text-xs leading-6"><p className="font-medium">{t('next')}</p><p className="text-muted-foreground">{t('spec.trendWatch')}</p></div>
        </article>)}</div>
        {!data.trends.length && <p className="card p-5 text-sm">{t('spec.noTrends')}</p>}
      </TabsContent>
    </>}
  </Tabs>
}
