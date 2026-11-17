import { useId } from 'react'
import { useTranslation } from 'react-i18next'
import type { FtshareOperation, FtshareSettings, FtshareTier } from '@panwatch/api'
import { Badge } from '@panwatch/base-ui/components/ui/badge'
import { Button } from '@panwatch/base-ui/components/ui/button'
import { Input } from '@panwatch/base-ui/components/ui/input'
import { Label } from '@panwatch/base-ui/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@panwatch/base-ui/components/ui/select'

const UNSET = '__unset__'

export function initialFtshareSettings(operation: FtshareOperation, saved?: unknown, variant = 0): FtshareSettings {
  const stored = saved as Partial<FtshareSettings> | null | undefined
  if (stored?.variant !== undefined && operation.variants[stored.variant] && stored.params) {
    return { variant: stored.variant, params: Object.fromEntries(operation.variants[stored.variant].parameters
      .filter(param => stored.params?.[param.name] !== undefined)
      .map(param => [param.name, String(stored.params?.[param.name])])) }
  }
  return { variant, params: { ...operation.variants[variant].preset } }
}

export function ftshareQueryValues(settings: FtshareSettings): FtshareSettings {
  return { ...settings, params: Object.fromEntries(Object.entries(settings.params).filter(([, value]) => value.trim())) }
}

export function FtshareTierBadge({ tier }: { tier: FtshareTier }) {
  const { t } = useTranslation('configuration')
  return <Badge variant={tier === 'basic' ? 'secondary' : 'outline'}>{t(`ftshare.tiers.${tier}`)}</Badge>
}

export function FtshareParameters({ operation, value, onChange, disabled }: {
  operation: FtshareOperation
  value: FtshareSettings
  onChange: (value: FtshareSettings) => void
  disabled?: boolean
}) {
  const { t } = useTranslation('configuration')
  const uid = useId()
  const variant = operation.variants[value.variant]
  const update = (name: string, entry: string) => onChange({ ...value, params: { ...value.params, [name]: entry } })
  return <div className="space-y-3">
    {operation.variants.length > 1 && <div className="space-y-1.5">
      <Label htmlFor={uid + '-variant'}>{t('ftshare.variant')}</Label>
      <Select value={String(value.variant)} disabled={disabled}
        onValueChange={id => onChange(initialFtshareSettings(operation, null, Number(id)))}>
        <SelectTrigger id={uid + '-variant'}><SelectValue /></SelectTrigger>
        <SelectContent>{operation.variants.map((entry, index) =>
          <SelectItem key={entry.path} value={String(index)}>{entry.path}</SelectItem>)}</SelectContent>
      </Select>
    </div>}
    <div className="flex items-center justify-between gap-2">
      <h3 className="text-sm font-semibold">{t('fuyao.rest.parameters')}</h3>
      {!!variant.parameters.length && <Button type="button" size="sm" variant="outline" disabled={disabled}
        onClick={() => onChange(initialFtshareSettings(operation, null, value.variant))}>{t('ftshare.restoreExample')}</Button>}
    </div>
    {!variant.parameters.length && <p className="text-sm text-muted-foreground">{t('fuyao.rest.noParameters')}</p>}
    <div className="grid gap-3 sm:grid-cols-2">{variant.parameters.map(param => {
      const id = uid + '-' + param.name
      const entry = value.params[param.name] ?? ''
      return <div key={param.name} className="min-w-0 space-y-1.5">
        <Label id={id + '-label'} htmlFor={id} className="font-mono break-all">{param.name}{param.required && <span aria-hidden="true" className="ml-1 text-primary">*</span>}</Label>
        {param.enum ? <Select value={entry || UNSET} disabled={disabled} required={param.required}
          onValueChange={next => update(param.name, next === UNSET ? '' : next)}>
          <SelectTrigger id={id} aria-labelledby={id + '-label'} aria-describedby={id + '-hint'}><SelectValue /></SelectTrigger>
          <SelectContent>{!param.required && <SelectItem value={UNSET}>{t('fuyao.rest.unset')}</SelectItem>}
            {param.enum.map(choice => <SelectItem key={choice} value={choice}>{choice}</SelectItem>)}</SelectContent>
        </Select> : <Input id={id} required={param.required} value={entry} disabled={disabled}
          aria-describedby={id + '-hint'} placeholder={param.format ?? param.default} autoComplete="off" maxLength={16384}
          inputMode={param.type === 'integer' ? 'numeric' : param.type === 'number' ? 'decimal' : 'text'}
          onChange={event => update(param.name, event.target.value)} />}
        <p id={id + '-hint'} className="break-words text-xs text-muted-foreground">{param.description.replace(/`/g, '')}</p>
      </div>
    })}</div>
    {variant.rules.map((rule, index) => <p key={index} className="text-xs text-muted-foreground">
      {t(`ftshare.rules.${rule.kind}`, {
        fields: (rule.kind === 'unless' ? rule.fields.slice(1) : rule.fields).join(' / '),
        first: rule.fields[0],
      })}
    </p>)}
  </div>
}
