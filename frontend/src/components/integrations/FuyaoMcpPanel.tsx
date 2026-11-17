import { useEffect, useState } from 'react'
import { ExternalLink, KeyRound, RefreshCw } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { fetchAPI } from '@panwatch/api/client'
import { Badge } from '@panwatch/base-ui/components/ui/badge'
import { Button } from '@panwatch/base-ui/components/ui/button'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@panwatch/base-ui/components/ui/select'
import { Switch } from '@panwatch/base-ui/components/ui/switch'

type ServiceId = keyof (typeof import('@/i18n/locales/zh-CN/configuration').configuration)['fuyao']['services']
type Status = {
  configured: boolean
  services: Array<{
    id: ServiceId; endpoint: string; enabled: boolean; checked_at: number | null
    tools: Array<{ name: string; title: string }>
  }>
}
const PATH = '/mcp-connections/fuyao'

export default function FuyaoMcpPanel() {
  const { t, i18n } = useTranslation(['configuration', 'common'])
  const [data, setData] = useState<Status | null>(null)
  const [service, setService] = useState<ServiceId>('a-share')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [revision, setRevision] = useState(0)

  useEffect(() => {
    const controller = new AbortController()
    fetchAPI<Status>(PATH, { signal: controller.signal }).then(result => {
      if (!controller.signal.aborted) setData(result)
    }).catch(() => {
      if (!controller.signal.aborted) setError(t('configuration:fuyao.loadFailed'))
    })
    return () => controller.abort()
  }, [revision, t])

  const selected = data?.services.find(item => item.id === service)
  async function change(enabled?: boolean) {
    setBusy(true)
    setError('')
    try {
      setData(await fetchAPI<Status>(`${PATH}/${service}${enabled === undefined ? '/test' : ''}`, enabled === undefined
        ? { method: 'POST', timeoutMs: 35000 }
        : { method: 'PUT', body: JSON.stringify({ enabled }) }))
    } catch (error) {
      setError(error instanceof Error ? error.message : t('configuration:mcp.failed'))
    } finally { setBusy(false) }
  }

  return <section id="fuyao-details" aria-labelledby="fuyao-mcp-title" className="card min-w-0 p-5 md:p-7 space-y-5">
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div className="flex items-center gap-3">
        <div className="grid h-11 w-11 shrink-0 place-items-center rounded-xl bg-primary/10 text-primary"><KeyRound className="h-5 w-5" /></div>
        <div>
          <h2 id="fuyao-mcp-title" className="font-semibold">{t('configuration:fuyao.mcpTitle')}</h2>
          <p className="mt-1 text-xs text-muted-foreground">{t('configuration:mcp.builtin')}</p>
        </div>
      </div>
      <Button variant="outline" size="sm" asChild><a href="/settings#sec-data-providers">
        {t(data?.configured ? 'configuration:fuyao.manageKey' : 'configuration:fuyao.configureKey')}
      </a></Button>
    </div>
    <p className="text-sm text-muted-foreground">{t('configuration:fuyao.mcpHint')}</p>
    {error && <div role="alert" className="flex items-center gap-2 text-sm text-destructive">
      <p>{error}</p>
      {!data && <Button variant="ghost" size="sm" onClick={() => { setError(''); setRevision(n => n + 1) }}>{t('configuration:fuyao.retry')}</Button>}
    </div>}
    {!data && !error && <p role="status" className="text-sm text-muted-foreground">{t('common:states.loading')}</p>}
    {selected && data && <div className="space-y-4 rounded-xl border border-border/60 p-4">
      <div className="flex flex-wrap items-end gap-3">
        <div className="w-full max-w-xs space-y-2">
          <label id="fuyao-service-label" className="text-sm">{t('configuration:fuyao.service')}</label>
          <Select value={service} onValueChange={value => { setService(value as ServiceId); setError('') }} disabled={busy}>
            <SelectTrigger aria-labelledby="fuyao-service-label"><SelectValue /></SelectTrigger>
            <SelectContent>{data.services.map(item => <SelectItem key={item.id} value={item.id}>{t(`configuration:fuyao.services.${item.id}`)}</SelectItem>)}</SelectContent>
          </Select>
        </div>
        <Badge variant="outline" role="status" className="mb-2">
          {t(!data.configured ? 'configuration:fuyao.notConfigured' : selected.enabled ? 'configuration:fuyao.enabled' : selected.checked_at ? 'configuration:fuyao.ready' : 'configuration:fuyao.untested')}
        </Badge>
      </div>
      <p className="break-all text-xs text-muted-foreground">{selected.endpoint}</p>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Button variant="secondary" size="sm" disabled={busy || !data.configured} onClick={() => void change()}>
          <RefreshCw className={`h-4 w-4 ${busy ? 'animate-spin' : ''}`} />{t('configuration:mcp.test')}
        </Button>
        <div className="flex items-center gap-2">
          <label htmlFor="fuyao-mcp-enabled" className="text-sm">{t('configuration:fuyao.enable')}</label>
          <Switch id="fuyao-mcp-enabled" checked={selected.enabled} disabled={busy || !data.configured || !selected.tools.length}
            onCheckedChange={enabled => void change(enabled)} />
        </div>
      </div>
      {selected.tools.length > 0 && <details key={selected.id} className="text-sm">
        <summary className="cursor-pointer text-primary">{t('configuration:fuyao.tools', { count: selected.tools.length })}</summary>
        <ul className="mt-2 space-y-1.5">{selected.tools.map(tool => <li key={tool.name}>
          {!i18n.language.startsWith('en') && <span className="mr-2">{tool.title}</span>}
          <code className="break-all text-xs text-muted-foreground">{tool.name}</code>
        </li>)}</ul>
      </details>}
    </div>}
    <a href="https://fuyao.aicubes.cn/docs/mcp/overview/" target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-xs text-primary hover:underline">
      {t('configuration:fuyao.mcpTitle')}<ExternalLink className="w-3 h-3" />
    </a>
  </section>
}
