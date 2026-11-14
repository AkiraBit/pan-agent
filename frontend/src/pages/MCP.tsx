import { useEffect, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { ExternalLink, Link2, Loader2, Plug, RefreshCw, Unplug } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { fetchAPI } from '@panwatch/api/client'
import { Button } from '@panwatch/base-ui/components/ui/button'
import { Switch } from '@panwatch/base-ui/components/ui/switch'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@panwatch/base-ui/components/ui/select'
import { useConfirm } from '@panwatch/base-ui/components/ui/confirm-dialog'
import { useToast } from '@panwatch/base-ui/components/ui/toast'
import { formatDate } from '@/i18n/format'

interface Connection {
  id: string; region: 'cn' | 'global'; endpoint: string; authorized: boolean; enabled: boolean
  pending: boolean; checked_at: number | null; error_code: string; docs_url: string
  tools: Array<{ name: string; title: [string, string] }>
}
const BASE = '/mcp-connections/longbridge'
const STORAGE = 'panwatch-longbridge-oauth'
type MCPLabel = keyof (typeof import('@/i18n/locales/zh-CN/configuration').configuration)['mcp']

export default function MCPPage() {
  const { t, i18n } = useTranslation(['configuration', 'common'])
  const { toast } = useToast()
  const showConfirm = useConfirm()
  const location = useLocation()
  const navigate = useNavigate()
  const [item, setItem] = useState<Connection | null>(null)
  const [region, setRegion] = useState<'cn' | 'global'>('cn')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const callbackStarted = useRef(false)
  const callback = location.pathname.endsWith('/callback')
  const label = (key: MCPLabel) => t(`configuration:mcp.${key}`)
  const load = async () => {
    const result = await fetchAPI<{ items: Connection[] }>('/mcp-connections')
    setItem(result.items[0]); setRegion(result.items[0].region)
  }
  const act = async (operation: () => Promise<void>) => {
    setBusy(true); setError('')
    try { await operation() } catch (e) { setError(e instanceof Error ? e.message : label('failed')) }
    finally { setBusy(false) }
  }
  useEffect(() => {
    if (!callback) { callbackStarted.current = false; void act(load); return }
    if (callbackStarted.current) return
    callbackStarted.current = true
    const query = new URLSearchParams(location.search)
    // Remove the short-lived code from browser history before any other work.
    window.history.replaceState(window.history.state, '', '/integrations/mcp/callback')
    void act(async () => {
      const saved = JSON.parse(sessionStorage.getItem(STORAGE) || 'null')
      sessionStorage.removeItem(STORAGE)
      if (!saved || saved.state !== query.get('state')) throw new Error(label('invalidCallback'))
      await fetchAPI(BASE + '/callback', { method: 'POST', body: JSON.stringify({
        state: saved.state, browser_key: saved.browserKey, code: query.get('code'), error: query.get('error'),
      }) })
      toast(label(query.has('error') ? 'cancelled' : 'authorized'), query.has('error') ? 'info' : 'success')
      navigate('/integrations/mcp', { replace: true })
    })
  }, [callback])
  const authorize = () => act(async () => {
    const browserKey = Array.from(crypto.getRandomValues(new Uint8Array(32)), b => b.toString(16).padStart(2, '0')).join('')
    const result = await fetchAPI<{ authorization_url: string; state: string }>(BASE + '/authorize', {
      method: 'POST', body: JSON.stringify({ region, browser_key: browserKey }), timeoutMs: 45000,
    })
    sessionStorage.setItem(STORAGE, JSON.stringify({ browserKey, state: result.state }))
    window.location.assign(result.authorization_url)
  })
  const change = (path: string, method: string, body?: object) => act(async () => {
    setItem(await fetchAPI<Connection>(BASE + path, { method, body: body ? JSON.stringify(body) : undefined, timeoutMs: 45000 }))
    toast(label(path === '/test' ? 'tested' : 'saved'), 'success')
  })
  const disconnect = async () => {
    if (await showConfirm(label('disconnectConfirm'), { destructive: true })) {
      sessionStorage.removeItem(STORAGE)
      await change('', 'DELETE')
    }
  }
  return <div className="max-w-4xl mx-auto space-y-6">
    <div><h1 className="text-xl font-semibold flex items-center gap-2"><Plug className="w-5 h-5 text-primary" />{label('title')}</h1>
      <p className="text-sm text-muted-foreground mt-2">{label('subtitle')}</p></div>
    {error && <div role="alert" className="rounded-xl border border-destructive/30 p-4 text-sm text-destructive space-y-3">
      <p>{error}</p><Button variant="secondary" size="sm" onClick={() => callback ? navigate('/integrations/mcp', { replace: true }) : void act(load)}>{label('retry')}</Button>
    </div>}
    {callback ? <div className="card p-6" aria-live="polite">{busy ? label('completing') : label('returnHint')}</div> : item ? <section className="card p-5 md:p-7 space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex items-center gap-3"><div className="w-11 h-11 rounded-2xl bg-primary/10 text-primary grid place-items-center"><Link2 className="w-5 h-5" /></div>
          <div><h2 className="font-semibold">{label('longbridge')}</h2><p className="text-xs text-muted-foreground">{label('builtin')}</p></div></div>
        <span className="text-xs rounded-full px-3 py-1 bg-accent text-foreground">{label(item.error_code === 'mcp_authorization_required' ? 'reauthorize' : item.authorized ? item.enabled ? 'enabled' : 'disabled' : item.pending ? 'pending' : 'notAuthorized')}</span>
      </div>
      <p className="text-sm text-muted-foreground">{label('description')}</p>
      <div className="grid sm:grid-cols-2 gap-5">
        <div className="space-y-2"><label className="text-sm" id="mcp-region-label">{label('region')}</label>
          <Select value={region} onValueChange={value => setRegion(value as 'cn' | 'global')} disabled={busy || item.authorized}>
            <SelectTrigger aria-labelledby="mcp-region-label"><SelectValue /></SelectTrigger><SelectContent>
              <SelectItem value="cn">{label('cn')}</SelectItem><SelectItem value="global">{label('global')}</SelectItem>
            </SelectContent></Select><p className="text-xs text-muted-foreground break-all">{item.authorized ? item.endpoint : region === 'cn' ? 'https://mcp.longbridge.cn' : 'https://mcp.longbridge.com'}</p>
        </div>
        <div className="flex items-center justify-between gap-4"><div><label htmlFor="mcp-enabled" className="text-sm">{label('useAssistant')}</label><p className="text-xs text-muted-foreground mt-1">{label('enableHint')}</p></div>
          <Switch id="mcp-enabled" checked={item.enabled} disabled={busy || !item.authorized || !item.tools.length || !item.checked_at} onCheckedChange={enabled => void change('', 'PUT', { enabled })} />
        </div>
      </div>
      {item.error_code && <p role="status" className="text-sm text-destructive">{label('connectionError')}</p>}
      <div className="flex flex-wrap gap-2">
        <Button onClick={() => void authorize()} disabled={busy}>{busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <ExternalLink className="w-4 h-4" />}{label(item.authorized ? 'authorizeAgain' : 'authorize')}</Button>
        {item.authorized && <><Button variant="secondary" onClick={() => void change('/test', 'POST')} disabled={busy}><RefreshCw className="w-4 h-4" />{label('test')}</Button>
          <Button variant="ghost" onClick={() => void disconnect()} disabled={busy}><Unplug className="w-4 h-4" />{label('disconnect')}</Button></>}
        {item.pending && <Button variant="ghost" disabled={busy} onClick={() => { sessionStorage.removeItem(STORAGE); void change('/authorization', 'DELETE') }}>{label('cancelAuthorization')}</Button>}
      </div>
      <div className="border-t border-border/60 pt-5 space-y-3"><div className="flex justify-between gap-3 flex-wrap"><h3 className="text-sm font-medium">{label('tools')}</h3>
        {item.checked_at && <p className="text-xs text-muted-foreground">{t('configuration:mcp.checkedAt', { time: formatDate(item.checked_at * 1000, { dateStyle: 'short', timeStyle: 'short' }) })}</p>}</div>
        {item.tools.length ? <div className="grid sm:grid-cols-2 gap-2">{item.tools.map(tool => <div key={tool.name} className="rounded-xl bg-accent/40 px-3 py-2 text-sm">{tool.title[i18n.language.startsWith('en') ? 1 : 0]}</div>)}</div> : <p className="text-sm text-muted-foreground">{label('emptyTools')}</p>}
      </div>
      <div className="border-t border-border/60 pt-5 space-y-2 text-xs text-muted-foreground"><p>{label('privacy')}</p><p>{label('disconnectHint')}</p>
        <a href={item.docs_url} target="_blank" rel="noopener noreferrer" className="inline-flex gap-1 items-center text-primary">{label('docs')}<ExternalLink className="w-3 h-3" /></a>
      </div>
    </section> : !error && <div className="card p-6 text-sm text-muted-foreground">{t('common:states.loading')}</div>}
  </div>
}
