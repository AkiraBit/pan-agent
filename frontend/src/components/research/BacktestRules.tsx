import { useTranslation } from 'react-i18next'
import { Button } from '@panwatch/base-ui/components/ui/button'
import { Input } from '@panwatch/base-ui/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@panwatch/base-ui/components/ui/select'
import type { BacktestConditions, BacktestRule } from '@panwatch/api'
import { rowList } from './ResearchDataset'

export const blankRule = (): BacktestRule => ({ indicator_code: '', operator: '', value: '' })
const EMPTY = '__unset__'

export function backtestReady(rules: BacktestConditions) {
  return [...rules.buy, ...rules.sell].every(rule =>
    rule.indicator_code && rule.operator && String(rule.value).trim())
}

export function BacktestRules({ indicators, value, onChange }: {
  indicators: unknown; value: BacktestConditions; onChange: (value: BacktestConditions) => void
}) {
  const { t } = useTranslation('configuration')
  const definitions = rowList(indicators).filter(row => typeof row.indicator_code === 'string' && row.indicator_code)
  function update(side: 'buy' | 'sell', index: number, patch: Partial<BacktestRule>) {
    onChange({ ...value, [side]: value[side].map((rule, i) => i === index ? { ...rule, ...patch } : rule) })
  }
  return <div className="grid gap-4 lg:grid-cols-2">
    {!definitions.length && <p role="status" className="text-sm text-muted-foreground lg:col-span-2">{t('researchData.indicatorsUnavailable')}</p>}
    {(['buy', 'sell'] as const).map(side => <fieldset key={side} className="space-y-3 rounded-lg border border-border/60 p-3">
      <legend className="px-1 text-sm font-medium">{t(side === 'buy' ? 'researchData.buyRules' : 'researchData.sellRules')}</legend>
      {value[side].map((rule, index) => {
        const definition = definitions.find(row => row.indicator_code === rule.indicator_code)
        const operators = [...new Set(String(definition?.support_operation || '').split(',').map(s => s.trim()).filter(Boolean))]
        return <div key={index} className="space-y-2">
          <div className="grid grid-cols-[minmax(0,1.4fr)_minmax(0,.75fr)_minmax(0,.8fr)] gap-2">
            <Select value={rule.indicator_code || EMPTY} onValueChange={code =>
              update(side, index, { ...blankRule(), indicator_code: code === EMPTY ? '' : code })} disabled={!definitions.length}>
              <SelectTrigger aria-label={t('researchData.indicator')}><SelectValue /></SelectTrigger>
              <SelectContent><SelectItem value={EMPTY}>{t('researchData.indicator')}</SelectItem>
                {definitions.map(row => <SelectItem key={String(row.indicator_code)} value={String(row.indicator_code)}>
                  {String(row.indicator_name || row.indicator_code)}
                </SelectItem>)}</SelectContent>
            </Select>
            <Select value={rule.operator || EMPTY} onValueChange={operator => update(side, index, { operator: operator === EMPTY ? '' : operator })}
              disabled={!operators.length}>
              <SelectTrigger aria-label={t('researchData.operator')}><SelectValue /></SelectTrigger>
              <SelectContent><SelectItem value={EMPTY}>{t('researchData.operator')}</SelectItem>
                {operators.map(operator => <SelectItem key={operator} value={operator}>{operator}</SelectItem>)}</SelectContent>
            </Select>
            <Input aria-label={t('researchData.threshold')} placeholder={t('researchData.threshold')}
              value={rule.value} disabled={!definition} maxLength={128}
              onChange={event => update(side, index, { value: event.target.value })} />
          </div>
          {typeof definition?.state_rules === 'string' && <p className="break-words text-xs text-muted-foreground">{definition.state_rules}</p>}
          {value[side].length > 1 && <Button type="button" variant="ghost" size="sm" onClick={() =>
            onChange({ ...value, [side]: value[side].filter((_, i) => index !== i) })}>{t('researchData.removeRule')}</Button>}
        </div>
      })}
      <Button type="button" variant="outline" size="sm" disabled={!definitions.length || value[side].length >= 8}
        onClick={() => onChange({ ...value, [side]: [...value[side], blankRule()] })}>{t('researchData.addRule')}</Button>
    </fieldset>)}
  </div>
}
