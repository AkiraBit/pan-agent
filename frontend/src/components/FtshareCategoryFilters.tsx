import { useTranslation } from 'react-i18next'
import type { FtshareOperation } from '@panwatch/api'
import { Button } from '@panwatch/base-ui/components/ui/button'

type CategoryFields = Pick<FtshareOperation, 'group' | 'subgroup'>
export type FtshareCategorySelection = { group: string; subgroup: string }
export const ALL_FTSHARE_CATEGORIES: FtshareCategorySelection = { group: '', subgroup: '' }

export function matchesFtshareCategory(operation: CategoryFields | undefined | null, selection: FtshareCategorySelection) {
  return (!selection.group || operation?.group === selection.group)
    && (!selection.subgroup || operation?.subgroup === selection.subgroup)
}

function orderedCategories(items: CategoryFields[], field: 'group' | 'subgroup') {
  const counts = new Map<string, number>()
  for (const item of items) {
    const name = item[field]
    if (name) counts.set(name, (counts.get(name) ?? 0) + 1)
  }
  return [...counts].sort(([a, n], [b, m]) => m - n || a.localeCompare(b, 'zh-CN')).map(([name]) => name)
}

const STOCK_SUBCATEGORY_ORDER = ['行情数据', '财务数据', '资金流向数据']

function CategoryRow({ options, current, label, getName, onChange, compact = false }: {
  options: string[]
  current: string
  label: string
  getName: (id: string) => string
  onChange: (id: string) => void
  compact?: boolean
}) {
  return <div role="group" aria-label={label} className="scrollbar flex min-w-0 gap-1 overflow-x-auto overscroll-x-contain pb-1">
    {['', ...options].map(id => <Button key={id} type="button" variant="ghost" size="sm"
      aria-pressed={id === current}
      className={`shrink-0 ${compact ? 'h-7 px-2.5 text-xs' : ''} ${id === current ? 'bg-primary/10 text-primary hover:bg-primary/10 hover:text-primary' : 'text-muted-foreground'}`}
      onClick={() => onChange(id)}>{getName(id)}</Button>)}
  </div>
}

export function FtshareCategoryFilters({ operations, value, onChange, groupName, subgroupName }: {
  operations: CategoryFields[]
  value: FtshareCategorySelection
  onChange: (selection: FtshareCategorySelection) => void
  groupName?: (group: string) => string
  subgroupName?: (subgroup: string) => string
}) {
  const { t } = useTranslation('configuration')
  const groups = orderedCategories(operations, 'group')
  const inGroup = value.group ? operations.filter(op => op.group === value.group) : []
  const availableSubgroups = orderedCategories(inGroup, 'subgroup')
  const subgroups = value.group === '股票数据'
    ? [...STOCK_SUBCATEGORY_ORDER.filter(name => availableSubgroups.includes(name)),
      ...availableSubgroups.filter(name => !STOCK_SUBCATEGORY_ORDER.includes(name))]
    : availableSubgroups
  if (!groups.length) return null

  const all = t('dataSources.categories.all')
  return <div className="min-w-0 space-y-1">
    <CategoryRow options={groups} current={value.group} label={t('ftshare.categoryFilter')}
      getName={group => group ? groupName?.(group) ?? group : all} onChange={group => onChange({ group, subgroup: '' })} />
    {(subgroups.length > 1 || (subgroups.length === 1 && inGroup.some(op => !op.subgroup))) && <CategoryRow
      key={value.group} compact options={subgroups} current={value.subgroup} label={t('ftshare.subcategoryFilter')}
      getName={subgroup => subgroup ? subgroupName?.(subgroup) ?? (subgroup === '资金流向数据' ? t('ftshare.capitalFlowSubcategory') : subgroup) : all}
      onChange={subgroup => onChange({ group: value.group, subgroup })} />}
  </div>
}
