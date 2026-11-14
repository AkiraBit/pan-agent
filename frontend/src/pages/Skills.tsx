import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { ArrowUpRight, Check, ChevronRight, ExternalLink } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { fetchAPI } from '@panwatch/api/client'
import { Button } from '@panwatch/base-ui/components/ui/button'
import { Switch } from '@panwatch/base-ui/components/ui/switch'
import { useToast } from '@panwatch/base-ui/components/ui/toast'
import LongbridgeIcon from '@/components/integrations/LongbridgeIcon'

type Localized = [string, string]
interface BuiltinSkill {
  id: string; title: Localized; description: Localized; version: string | null
  upstream_revision: string; upstream_version: string | null; source_url: string; docs_url: string; bundled_file_count: number
  enabled: boolean; available: boolean; support: 'partial' | 'unsupported'
  connection_status: 'ready' | 'authorization_required' | 'mcp_disabled' | 'test_required' | 'tools_missing'
  capabilities: Array<{ title: Localized; tools: string[]; tools_present: boolean }>
  unsupported_capabilities: Localized[]; workflow: Localized[]; examples: Localized[]
  tools: Array<{ name: string; title: Localized; present: boolean }>
}
type SkillLabel = keyof (typeof import('@/i18n/locales/zh-CN/configuration').configuration)['skills']

function SkillSource({ item }: { item: BuiltinSkill }) {
  const { t } = useTranslation('configuration')
  const [open, setOpen] = useState(false)
  const [content, setContent] = useState('')
  const [error, setError] = useState(false)
  useEffect(() => {
    if (!open || content) return
    let active = true
    fetchAPI<{ content: string }>(`/builtin-skills/${item.id}/source`).then(result => {
      if (active) setContent(result.content)
    }).catch(() => { if (active) setError(true) })
    return () => { active = false }
  }, [item.id, open, content])
  return <div className="space-y-3">
    <Button variant="secondary" size="sm" aria-expanded={open} aria-controls="skill-original" onClick={() => { setError(false); setOpen(!open) }}>
      {t(open ? 'skills.hideSource' : 'skills.showSource')}
    </Button>
    {open && <div id="skill-original" className="space-y-2">
      <p className="text-xs text-muted-foreground leading-relaxed">{t('skills.sourceHint', { count: item.bundled_file_count })}</p>
      {error ? <p role="alert" className="text-sm text-destructive">{t('skills.sourceFailed')}</p> : content ?
        <pre tabIndex={0} aria-label={t('skills.sourceContent')} className="scrollbar max-h-96 overflow-auto rounded-xl border border-border/60 bg-accent/30 p-4 whitespace-pre-wrap break-words text-xs leading-relaxed">{content}</pre> :
        <p role="status" className="text-xs text-muted-foreground">{t('skills.sourceLoading')}</p>}
    </div>}
  </div>
}

export default function SkillsPage() {
  const { t, i18n } = useTranslation(['configuration', 'common'])
  const { toast } = useToast()
  const [search, setSearch] = useSearchParams()
  const [items, setItems] = useState<BuiltinSkill[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const label = (key: SkillLabel) => t(`configuration:skills.${key}`)
  const local = (value: Localized) => value[i18n.language.startsWith('en') ? 1 : 0]
  const item = items.find(entry => entry.id === search.get('skill')) || items[0]
  const load = async () => {
    setBusy(true); setError('')
    try { setItems((await fetchAPI<{ items: BuiltinSkill[] }>('/builtin-skills')).items) }
    catch (e) { setError(e instanceof Error ? e.message : label('failed')) }
    finally { setBusy(false) }
  }
  useEffect(() => { void load() }, [])
  const select = (id: string) => {
    const next = new URLSearchParams(search)
    next.set('tab', 'skills'); next.set('skill', id)
    setError(''); setSearch(next)
  }
  const configure = async (enabled: boolean) => {
    setBusy(true); setError('')
    try {
      const updated = await fetchAPI<BuiltinSkill>(`/builtin-skills/${item.id}`, { method: 'PUT', body: JSON.stringify({ enabled }) })
      setItems(current => current.map(entry => entry.id === updated.id ? updated : entry))
      toast(label('saved'), 'success')
    } catch (e) { setError(e instanceof Error ? e.message : label('failed')) }
    finally { setBusy(false) }
  }
  const status = (entry: BuiltinSkill) => label(entry.support === 'unsupported' ? 'unsupported' : !entry.enabled ? 'disabled' : entry.available ? 'ready' : 'waiting')
  const partialCount = items.filter(entry => entry.support === 'partial').length
  return <div className="space-y-6">
    {error && <div role="alert" className="rounded-xl border border-destructive/30 p-4 text-sm text-destructive space-y-3">
      <p>{error}</p><Button variant="secondary" size="sm" onClick={() => void load()}>{label('retry')}</Button>
    </div>}
    {item ? <div className="grid md:grid-cols-[260px_minmax(0,1fr)] gap-6 items-start">
      <nav aria-label={label('services')} className="card p-3 space-y-3 md:sticky md:top-24">
        <div className="px-2 pt-1 space-y-2"><h2 className="text-sm font-medium">{label('services')}</h2>
          <p className="text-xs text-muted-foreground leading-relaxed">{t('configuration:skills.catalogCount', { count: items.length, partial: partialCount, unsupported: items.length - partialCount })}</p>
        </div>
        <div className="scrollbar max-h-72 md:max-h-[calc(100vh-300px)] overflow-y-auto space-y-1 p-1">
          {items.map(entry => <Button key={entry.id} variant="ghost" aria-current={entry.id === item.id ? 'page' : undefined} onClick={() => select(entry.id)}
            className={`w-full h-auto justify-start gap-3 rounded-xl border p-3 text-left ${entry.id === item.id ? 'border-primary/15 bg-primary/5' : 'border-transparent'}`}>
            <LongbridgeIcon className="w-9 h-9" /><span className="min-w-0 flex-1"><span className="block text-sm font-medium">{local(entry.title)}</span>
              <span className="block text-xs font-normal text-muted-foreground mt-1">{entry.support === 'partial' ? `${label('partial')} · ${status(entry)}` : status(entry)}</span></span>
            {entry.id === item.id && <ChevronRight className="w-4 h-4 text-primary shrink-0" />}
          </Button>)}
        </div>
        <p className="px-2 pb-1 text-xs text-muted-foreground leading-relaxed">{label('builtinHint')}</p>
      </nav>
      <section aria-labelledby="skill-detail-title" className="card min-w-0 p-5 md:p-7 space-y-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="flex items-center gap-3"><LongbridgeIcon className="w-12 h-12" /><div><h2 id="skill-detail-title" className="font-semibold">{local(item.title)}</h2><p className="text-xs text-muted-foreground mt-1">{label('builtin')}</p></div></div>
          <div className="flex flex-wrap gap-2 text-xs"><span className="rounded-full px-3 py-1 bg-accent text-foreground">{label(item.support)}</span>
            {item.support === 'partial' && <span className="rounded-full px-3 py-1 bg-primary/10 text-primary">{status(item)}</span>}
          </div>
        </div>
        <p className="text-sm text-muted-foreground leading-relaxed">{local(item.description)}</p>
        <dl className="grid sm:grid-cols-3 gap-5 rounded-xl bg-accent/40 p-4">
          <div><dt className="text-xs text-muted-foreground">{label('provider')}</dt><dd className="text-sm font-medium mt-2">{label('providerName')}</dd></div>
          <div><dt className="text-xs text-muted-foreground">{label('version')}</dt><dd className="text-sm font-medium mt-2">{item.version || label('notAdapted')}</dd>{item.version && <p className="text-xs text-muted-foreground mt-1">{label('adapted')}</p>}</div>
          <div><dt className="text-xs text-muted-foreground">{label('sourceVersion')}</dt><dd className="text-sm font-medium mt-2"><a href={item.source_url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-primary">{item.upstream_version ? `v${item.upstream_version} · ` : ''}{item.upstream_revision.slice(0, 7)}<ExternalLink className="w-3 h-3" /></a></dd></div>
        </dl>
        <div className="flex items-center justify-between gap-4"><div><label htmlFor="builtin-skill-enabled" className="text-sm">{label('enable')}</label><p className="text-xs text-muted-foreground mt-1 leading-relaxed">{label(item.support === 'unsupported' ? 'unsupportedHint' : 'enableHint')}</p></div>
          <Switch id="builtin-skill-enabled" checked={item.enabled} disabled={busy || item.support === 'unsupported'} onCheckedChange={value => void configure(value)} />
        </div>
        {item.support === 'partial' && <div className="rounded-xl border border-border/60 p-4 space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2"><h3 className="text-sm font-medium">{label('dependency')}</h3><Link to="/integrations/mcp" className="inline-flex items-center gap-1 text-xs text-primary">{label('manageMcp')}<ArrowUpRight className="w-3 h-3" /></Link></div>
          <p className="text-sm text-muted-foreground">{label(item.connection_status === 'ready' ? 'connectionReady' : item.connection_status)}</p>
          <p className="text-xs text-muted-foreground">{label('authorizationHint')}</p>
        </div>}
        <div className="border-t border-border/60 pt-5 space-y-4">
          <div className="space-y-3"><h3 className="text-sm font-medium">{label('capabilities')}</h3>
            {item.capabilities.length ? <><p className="text-xs text-muted-foreground leading-relaxed">{label('capabilitiesHint')}</p>
              <ul className="space-y-2">{item.capabilities.map(capability => <li key={capability.title[1]} className="flex items-start gap-2 text-sm">
                <Check className="w-4 h-4 text-primary mt-0.5 shrink-0" /><span>{local(capability.title)}
                  {['ready', 'tools_missing'].includes(item.connection_status) && !capability.tools_present && <span className="ml-2 text-xs text-muted-foreground">{label('missingTools')}</span>}
                </span></li>)}</ul>
              <div className="flex flex-wrap gap-2">{item.tools.map(tool => <span key={tool.name} className="rounded-lg bg-accent/60 px-3 py-1.5 text-xs">{local(tool.title)}</span>)}</div></> :
              <p className="text-sm text-muted-foreground leading-relaxed">{label('noCapabilities')}</p>}
          </div>
          <div className="rounded-xl bg-accent/40 p-4 space-y-2"><h3 className="text-sm font-medium">{label('unsupportedCapabilities')}</h3>
            <ul className="list-disc pl-4 space-y-2 text-sm text-muted-foreground leading-relaxed">{item.unsupported_capabilities.map(capability => <li key={capability[1]}>{local(capability)}</li>)}</ul>
          </div>
        </div>
        {item.workflow.length > 0 && <div className="space-y-3"><h3 className="text-sm font-medium">{label('workflow')}</h3><ol className="list-decimal pl-5 space-y-2 text-sm text-muted-foreground leading-relaxed">
          {item.workflow.map(step => <li key={step[1]}>{local(step)}</li>)}
        </ol></div>}
        {item.examples.length > 0 && <div className="border-t border-border/60 pt-5 space-y-3"><h3 className="text-sm font-medium">{label('examples')}</h3>
          <ul className="space-y-2 text-sm text-muted-foreground">{item.examples.map(example => <li key={example[1]} className="rounded-xl border border-border/60 px-4 py-3 leading-relaxed">{local(example)}</li>)}</ul>
          {item.available && <Button asChild size="sm"><Link to="/assistant">{label('openAssistant')}<ArrowUpRight className="w-4 h-4" /></Link></Button>}
        </div>}
        <div className="border-t border-border/60 pt-5 space-y-3 text-xs text-muted-foreground leading-relaxed"><p>{label('scopeHint')}</p>
          <SkillSource key={item.id} item={item} />
          <a href={item.docs_url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-primary">{label('docs')}<ExternalLink className="w-3 h-3" /></a>
        </div>
      </section>
    </div> : !error && <div className="card p-6 text-sm text-muted-foreground">{t('common:states.loading')}</div>}
  </div>
}
