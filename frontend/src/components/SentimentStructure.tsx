import { useTranslation } from 'react-i18next'
import type { SentimentSupplement } from '@panwatch/api/emotion'
import { formatNumber } from '@/i18n/format'
import { EmotionCard, emotionStamp } from './EmotionBlocks'

export default function SentimentStructure({ data }: { data?: SentimentSupplement }) {
  const { t } = useTranslation('emotion')
  if (!data) return null
  const stats = data.statistics.status === 'available' ? data.statistics.data : null
  const number = (v: number | null | undefined) => v == null ? '—' : formatNumber(v, { maximumFractionDigits: 2 })
  const dragon = data.dragon_tiger.status === 'available' ? (data.dragon_tiger.data?.stock_items ?? []).filter(r => r.range_days === 1 && Number.isFinite(r.net_value)).sort((a, b) => b.net_value! - a.net_value!).slice(0, 5) : []
  return <EmotionCard title={t('overview.report.structure')}>
    <p className="text-xs text-muted-foreground mb-4">{t('overview.report.fuyaoAt', { day: data.trade_date, at: emotionStamp(data.collected_at) })}</p>
    <div className="grid grid-cols-2 xl:grid-cols-4 gap-3">{([
      ['limitUp', stats?.limit_up_stock_count], ['opened', stats?.open_stock_count],
      ['sealRate', stats?.seal_rate == null ? null : stats.seal_rate * 100],
      ['limitDown', data.pools.down.status === 'available' ? data.pools.down.total : null],
    ] as const).map(([key, value]) => <div className="rounded-xl bg-accent/30 p-4" key={key}><p className="text-xs text-muted-foreground">{t(`overview.report.${key}`)}</p><p className="text-xl tabular-nums mt-2">{number(value)}{key === 'sealRate' && value != null ? '%' : ''}</p></div>)}</div>
    <p className="text-xs text-muted-foreground leading-6 mt-3">{t('overview.report.vendorScope')}</p>
    <div className="grid md:grid-cols-2 gap-3 mt-4">{data.ladders.map(l => <article key={l.board} className="rounded-xl border p-4"><h4 className="text-sm font-medium">{t(`overview.boards.${l.board}`)}</h4><p className="text-xs text-muted-foreground mt-2">{t('overview.report.ladderSample', { count: l.sample, excluded: l.excluded_or_unknown })}</p><div className="flex flex-wrap gap-2 mt-3">{l.levels.map(level => <span key={level.level} className="rounded-full border px-3 py-1 text-xs">{t('overview.report.level', { level: level.level, count: level.count })}</span>)}</div>{!l.levels.length && <p className="text-xs text-muted-foreground mt-2">{t(l.status === 'available' ? 'overview.report.noEligibleEvents' : 'overview.report.eventsMissing')}</p>}{l.status !== 'available' && !!l.levels.length && <p className="text-xs text-muted-foreground mt-2">{t('overview.report.eventsMissing')}</p>}</article>)}</div>
    {!!dragon.length && <div className="mt-5 border-t pt-4"><h4 className="text-sm font-medium">{t('overview.report.dragonTitle')}</h4><div className="space-y-2 mt-3">{dragon.map((r, i) => <div className="flex flex-wrap justify-between gap-2 text-xs" key={`${r.thscode}-${i}`}><span>{r.name} · {r.thscode}</span><span className="tabular-nums">{number(r.net_value)} {t('overview.report.cny')}</span></div>)}</div><p className="text-xs text-muted-foreground leading-6 mt-3">{t('overview.report.dragonScope')}</p></div>}
  </EmotionCard>
}
