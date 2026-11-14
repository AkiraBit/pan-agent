import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { ArrowUpRight, Check, ChevronDown, ChevronRight, ExternalLink } from 'lucide-react'
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

function SkillDetails({ item }: { item: BuiltinSkill }) {
  const { t, i18n } = useTranslation('configuration')
  const label = (key: SkillLabel) => t(`skills.${key}`)
  const local = (value: Localized) => value[i18n.language.startsWith('en') ? 1 : 0]
  return <div id={`skill-details-${item.id}`} className="border-t border-border/60 p-4 md:p-5 space-y-5">
    <p className="text-sm text-muted-foreground leading-relaxed">{local(item.description)}</p>
    <p className="text-xs text-muted-foreground leading-relaxed">{label(item.support === 'unsupported' ? 'unsupportedHint' : 'enableHint')}</p>
        <dl className="grid sm:grid-cols-3 gap-5 rounded-xl bg-accent/40 p-4">
          <div><dt className="text-xs text-muted-foreground">{label('provider')}</dt><dd className="text-sm font-medium mt-2">{label('providerName')}</dd></div>
          <div><dt className="text-xs text-muted-foreground">{label('version')}</dt><dd className="text-sm font-medium mt-2">{item.version || label('notAdapted')}</dd>{item.version && <p className="text-xs text-muted-foreground mt-1">{label('adapted')}</p>}</div>
          <div><dt className="text-xs text-muted-foreground">{label('sourceVersion')}</dt><dd className="text-sm font-medium mt-2"><a href={item.source_url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-primary">{item.upstream_version ? `v${item.upstream_version} · ` : ''}{item.upstream_revision.slice(0, 7)}<ExternalLink className="w-3 h-3" /></a></dd></div>
        </dl>
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
        <div className="border-t border-border/60 pt-5 space-y-3 text-xs text-muted-foreground leading-relaxed">
          <SkillSource key={item.id} item={item} />
          <a href={item.docs_url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-primary">{label('docs')}<ExternalLink className="w-3 h-3" /></a>
        </div>
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
  const selectedId = search.get('skill')
  const load = async () => {
    setBusy(true); setError('')
    try { setItems((await fetchAPI<{ items: BuiltinSkill[] }>('/builtin-skills')).items) }
    catch (e) { setError(e instanceof Error ? e.message : label('failed')) }
    finally { setBusy(false) }
  }
  useEffect(() => { void load() }, [])
  const select = (id: string) => {
    const next = new URLSearchParams(search)
    next.set('tab', 'skills')
    if (id === selectedId) next.delete('skill')
    else next.set('skill', id)
    setError(''); setSearch(next)
  }
  const configure = async (id: string, enabled: boolean) => {
    setBusy(true); setError('')
    try {
      const updated = await fetchAPI<BuiltinSkill>(`/builtin-skills/${id}`, { method: 'PUT', body: JSON.stringify({ enabled }) })
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
    {items.length > 0 ? <div className="grid md:grid-cols-[240px_minmax(0,1fr)] gap-6 items-start">
      <nav aria-label={label('sources')} className="card p-3 space-y-3 md:sticky md:top-24">
        <h2 className="px-2 pt-1 text-sm font-medium">{label('services')}</h2>
        <a href="#longbridge-skills" aria-current="page" className="flex items-center gap-3 rounded-xl border border-primary/15 bg-primary/5 p-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
          <LongbridgeIcon className="w-10 h-10" />
          <span className="min-w-0 flex-1"><span className="block font-medium">{label('providerTitle')}</span>
            <span className="block text-xs text-muted-foreground mt-1">{t('configuration:skills.skillCount', { count: items.length })}</span>
          </span><ChevronRight className="w-4 h-4 text-primary shrink-0" />
        </a>
        <p className="px-2 pb-1 text-xs text-muted-foreground leading-relaxed">{label('builtinHint')}</p>
      </nav>
      <section id="longbridge-skills" aria-labelledby="skill-provider-title" className="card min-w-0 p-5 md:p-7 space-y-6 scroll-mt-24">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div className="flex items-center gap-3"><LongbridgeIcon className="w-12 h-12" /><div><h2 id="skill-provider-title" className="font-semibold">{label('providerTitle')}</h2><p className="text-xs text-muted-foreground mt-1">{label('builtin')}</p></div></div>
          <a href={items[0].docs_url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-xs text-primary">{label('docs')}<ExternalLink className="w-3 h-3" /></a>
        </div>
        <p className="text-sm text-muted-foreground leading-relaxed">{label('providerDescription')}</p>
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl bg-accent/40 p-4 text-xs text-muted-foreground">
          <p>{t('configuration:skills.catalogCount', { count: items.length, partial: partialCount, unsupported: items.length - partialCount })}</p>
          <p>{t('configuration:skills.enabledCount', { count: items.filter(entry => entry.enabled).length })}</p>
        </div>
        <div className="space-y-3">
          <div className="flex items-center justify-between gap-3"><h3 className="text-sm font-medium">{label('includedSkills')}</h3><p className="text-xs text-muted-foreground">{label('expandHint')}</p></div>
          {items.map(entry => <section key={entry.id} aria-labelledby={`skill-title-${entry.id}`} className={`rounded-xl border ${selectedId === entry.id ? 'border-primary/25' : 'border-border/60'} overflow-hidden`}>
            <div className="flex items-center gap-2 pr-4">
              <Button variant="ghost" aria-label={local(entry.title)} aria-expanded={selectedId === entry.id} aria-controls={`skill-details-${entry.id}`} onClick={() => select(entry.id)}
                className="flex-1 min-w-0 h-auto justify-start gap-3 rounded-none px-4 py-4 text-left">
                <ChevronDown aria-hidden="true" className={`w-4 h-4 shrink-0 text-muted-foreground transition-transform ${selectedId === entry.id ? '' : '-rotate-90'}`} />
                <span className="min-w-0 flex-1"><span id={`skill-title-${entry.id}`} className="block text-sm font-medium">{local(entry.title)}</span>
                  <span className="block truncate text-xs font-normal text-muted-foreground mt-1">{local(entry.description)}</span>
                  <span className="block text-xs font-normal text-muted-foreground mt-1">{entry.support === 'partial' ? `${label('partial')} · ${status(entry)}` : status(entry)}</span>
                </span>
              </Button>
              <Switch aria-label={t('configuration:skills.enableNamed', { name: local(entry.title) })} checked={entry.enabled} disabled={busy || entry.support === 'unsupported'}
                onCheckedChange={value => void configure(entry.id, value)} />
            </div>
            {selectedId === entry.id && <SkillDetails item={entry} />}
          </section>)}
        </div>
        <p className="border-t border-border/60 pt-5 text-xs text-muted-foreground leading-relaxed">{label('scopeHint')}</p>
      </section>
    </div> : !error && <div className="card p-6 text-sm text-muted-foreground">{t('common:states.loading')}</div>}
  </div>
}
