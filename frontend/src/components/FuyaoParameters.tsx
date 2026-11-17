import { useId } from 'react'
import { useTranslation } from 'react-i18next'
import type { FuyaoOperation, FuyaoParameter } from '@panwatch/api'
import { Button } from '@panwatch/base-ui/components/ui/button'
import { Input } from '@panwatch/base-ui/components/ui/input'
import { Label } from '@panwatch/base-ui/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@panwatch/base-ui/components/ui/select'

const UNSET = '__unset__'

function example(param: FuyaoParameter) {
  if (param.example_days_ago !== undefined) return String(Date.now() - param.example_days_ago * 86_400_000)
  return param.example === undefined ? '' : String(param.example)
}

export function initialFuyaoParams(operation: FuyaoOperation, settings?: unknown) {
  const saved = (settings as { params?: Record<string, string> } | null | undefined)?.params
  return Object.fromEntries(operation.parameters.map(param => [param.name, saved ? (saved[param.name] ?? '') : example(param)]))
}

export function fuyaoQueryValues(params: Record<string, string>) {
  return Object.fromEntries(Object.entries(params).filter(([, value]) => value.trim()))
}

export function FuyaoParameters({ operation, value, onChange, disabled }: {
  operation: FuyaoOperation
  value: Record<string, string>
  onChange: (value: Record<string, string>) => void
  disabled?: boolean
}) {
  const { t } = useTranslation('configuration')
  const uid = useId()
  const update = (name: string, entry: string) => onChange({ ...value, [name]: entry })
  return <div className="space-y-3">
    <div className="flex items-center justify-between gap-2">
      <h3 className="text-sm font-semibold">{t('fuyao.rest.parameters')}</h3>
      {operation.parameters.some(p => p.example !== undefined || p.example_days_ago !== undefined) &&
        <Button type="button" size="sm" variant="outline" disabled={disabled}
          onClick={() => onChange(initialFuyaoParams(operation))}>{t('fuyao.rest.fillExample')}</Button>}
    </div>
    {!operation.parameters.length && <p className="text-sm text-muted-foreground">{t('fuyao.rest.noParameters')}</p>}
    <div className="grid gap-3 sm:grid-cols-2">{operation.parameters.map(param => {
      const id = uid + '-' + param.name
      const choices = param.enum ?? (param.type === 'boolean' ? ['true', 'false'] : undefined)
      const entry = value[param.name] ?? ''
      const hint = param.default === undefined ? example(param) : t('fuyao.rest.defaultValue', { value: String(param.default) })
      return <div key={param.name} className="min-w-0 space-y-1.5">
        <Label id={id + '-label'} htmlFor={id} className="font-mono break-all">{param.name}{param.required && <span aria-hidden="true" className="ml-1 text-primary">*</span>}</Label>
        {choices ? <Select value={entry || UNSET} disabled={disabled} required={param.required}
          onValueChange={next => update(param.name, next === UNSET ? '' : next)}>
          <SelectTrigger id={id} aria-labelledby={id + '-label'} aria-describedby={id + '-hint'}><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value={UNSET} disabled={param.required}>{hint || t('fuyao.rest.unset')}</SelectItem>
            {choices.map(choice => <SelectItem key={choice} value={choice}>{choice}</SelectItem>)}
          </SelectContent>
        </Select> : <Input id={id} required={param.required} value={entry} disabled={disabled}
          aria-describedby={id + '-hint'} placeholder={hint} autoComplete="off" maxLength={16_384}
          inputMode={param.type === 'integer' ? 'numeric' : param.type === 'number' ? 'decimal' : 'text'}
          onChange={event => update(param.name, event.target.value)} />}
        <p id={id + '-hint'} className="break-words text-xs text-muted-foreground">{param.description || (param.encoding === 'date-ms' ? t('fuyao.rest.timestamp') : '')}</p>
      </div>
    })}</div>
  </div>
}
