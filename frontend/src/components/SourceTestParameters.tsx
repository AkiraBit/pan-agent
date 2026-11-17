import type { DataSourceTestSettings, DataSourceTestValue } from '@panwatch/api'
import { Input } from '@panwatch/base-ui/components/ui/input'
import { Label } from '@panwatch/base-ui/components/ui/label'
import { useTranslation } from 'react-i18next'

export function SourceTestParameters({ settings, symbols, onSymbolsChange, values, onChange }: {
  settings: DataSourceTestSettings
  symbols: string
  onSymbolsChange: (value: string) => void
  values: Record<string, DataSourceTestValue>
  onChange: (values: Record<string, DataSourceTestValue>) => void
}) {
  const { t } = useTranslation('configuration')
  const translate = t as unknown as (key: string, options?: Record<string, unknown>) => string
  const spec = settings.symbols
  return <div className="space-y-4">
    {spec && <div className="space-y-1.5">
      <Label htmlFor="source-test-symbols">{t('dataSources.probeParams.symbols')}</Label>
      <Input id="source-test-symbols" className="font-mono" value={symbols} onChange={e => onSymbolsChange(e.target.value)}
        aria-describedby="probe-symbols-help" placeholder={spec.examples.join(', ')} />
      <p id="probe-symbols-help" className="text-xs text-muted-foreground">
        {t('dataSources.probeParams.symbolsHelp', {
          markets: spec.markets.map(market => translate(`dataSources.callOrder.markets.${market}`, { defaultValue: market })).join(' / '),
          count: spec.maximum,
        })}
      </p>
    </div>}
    {settings.fields.length > 0 && <div className="grid gap-4 sm:grid-cols-2">
      {settings.fields.map(field => {
        const id = `probe-${field.key}`
        const key = `dataSources.probeParams.fields.${field.key}`
        const value = values[field.key] ?? (field.type === 'date' ? '' : field.default ?? '')
        return <div key={field.key} className="min-w-0 space-y-1.5">
          <Label htmlFor={id} className="flex flex-wrap items-center gap-x-2">
            {translate(`${key}.label`, { defaultValue: field.key })}
            {field.wire && <code className="text-xs font-normal text-muted-foreground">{field.wire}</code>}
          </Label>
          <Input id={id} type={field.type === 'integer' ? 'number' : 'date'} value={String(value)} min={field.minimum} max={field.maximum}
            aria-describedby={`${id}-help`} onChange={e => onChange({ ...values, [field.key]: e.target.value })} />
          <p id={`${id}-help`} className="text-xs text-muted-foreground">
            {translate(`${key}.help`)}
            {field.default !== null && (field.type === 'date'
              ? t('dataSources.probeParams.latestSession', { date: String(field.default) })
              : t('dataSources.probeParams.defaultValue', { value: String(field.default) }))}
          </p>
        </div>
      })}
    </div>}
  </div>
}
