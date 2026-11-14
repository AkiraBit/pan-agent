import { lazy, Suspense, useCallback, useEffect, useRef, useState } from 'react'
import { Link, useLocation, useNavigate, useSearchParams } from 'react-router-dom'
import { Activity, Bot, Clock3, Compass, FileCheck2, GitBranch, History, ListChecks, Plus, RefreshCw, Settings2 } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Button } from '@panwatch/base-ui/components/ui/button'
import { Input } from '@panwatch/base-ui/components/ui/input'
import { Label } from '@panwatch/base-ui/components/ui/label'
import { Switch } from '@panwatch/base-ui/components/ui/switch'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@panwatch/base-ui/components/ui/select'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@panwatch/base-ui/components/ui/dialog'
import { useToast } from '@panwatch/base-ui/components/ui/toast'
import { useConfirm } from '@panwatch/base-ui/components/ui/confirm-dialog'
import { emotionApi, type EmotionPage, type EmotionPublication, type EmotionSettings, type EmotionWorkspace, type Evidence } from '@panwatch/api/emotion'
import EmotionSessionValidation from '@/components/EmotionSessionValidation'
import EmotionRegulatory from '@/components/EmotionRegulatory'
import EmotionConstraints from '@/components/EmotionConstraints'
import EmotionLifecycle from '@/components/EmotionLifecycle'
import EmotionBlockRenderer, { EmotionCard, emotionStamp } from '@/components/EmotionBlocks'
import type { emotion } from '@/i18n/locales/zh-CN/emotion'

const LegacyObservations = lazy(() => import('./ShortTerm'))
const pages: Array<{ id: EmotionPage; icon: typeof Compass }> = [
  { id: 'overview', icon: Compass }, { id: 'cycle', icon: GitBranch }, { id: 'playbook', icon: ListChecks },
  { id: 'monitor', icon: Activity }, { id: 'validation', icon: FileCheck2 }, { id: 'stock', icon: Activity }, { id: 'evidence', icon: FileCheck2 }, { id: 'review', icon: History }, { id: 'agent', icon: Bot },
]
const defaultSettings: EmotionSettings = { focus_symbols: [], schedule_enabled: false, schedule_time: '08:45', language: 'zh-CN', monitoring_enabled: false, monitor_interval_seconds: 30, postmarket_enabled: false, postmarket_time: '15:10' }

export default function EmotionWorkbench() {
  const { t, i18n } = useTranslation('emotion')
  const { toast } = useToast()
  const requestConfirm = useConfirm()
  const location = useLocation(), navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const selected = params.get('publication') || 'latest'
  const current = location.pathname.split('/')[2] || 'overview'
  const page = pages.some(p => p.id === current) ? current as EmotionPage : 'overview'
  const stock = location.pathname.split('/')[3] || null
  const [data, setData] = useState<EmotionWorkspace | null>(null)
  const [historical, setHistorical] = useState<EmotionPublication | null>(null)
  const [failed, setFailed] = useState(false)
  const [historyFailed, setHistoryFailed] = useState(false)
  const [busy, setBusy] = useState(false)
  const [target, setTarget] = useState('')
  const customTarget = useRef(false)
  const pendingKey = useRef<string | null>(null)
  const [noteOpen, setNoteOpen] = useState(false)
  const [note, setNote] = useState(''), [url, setUrl] = useState('')
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [settings, setSettings] = useState<EmotionSettings>(defaultSettings)
  const [focus, setFocus] = useState('')
  const [detail, setDetail] = useState<Evidence | null>(null)
  const [rawOpen, setRawOpen] = useState(false)
  const [saving, setSaving] = useState(false)
  const loadSequence = useRef(0)
  const load = useCallback(async (signal?: AbortSignal) => {
    const sequence = ++loadSequence.current
    try {
      const next = await emotionApi.workspace(signal)
      if (signal?.aborted || sequence !== loadSequence.current) return
      setData(next); setFailed(false)
      if (!customTarget.current) setTarget((page === 'validation' ? next.validation_trade_date || next.target_trade_date : next.target_trade_date) || '')
    } catch { if (!signal?.aborted && sequence === loadSequence.current) setFailed(true) }
  }, [page])
  useEffect(() => {
    const controller = new AbortController()
    void load(controller.signal)
    const interval = window.setInterval(() => void load(controller.signal), 4000)
    return () => { controller.abort(); window.clearInterval(interval) }
  }, [load])
  useEffect(() => {
    setHistorical(null); setHistoryFailed(false)
    if (selected === 'latest') return
    const controller = new AbortController()
    emotionApi.publication(selected, controller.signal).then(p => { if (!controller.signal.aborted) setHistorical(p) })
      .catch(() => { if (!controller.signal.aborted) setHistoryFailed(true) })
    return () => controller.abort()
  }, [selected])
  const publication = selected === 'latest' ? data?.publication : historical
  const active = data?.runs.find(r => r.status === 'queued' || r.status === 'running')
  const lastRun = data?.runs[0]
  const language = i18n.resolvedLanguage === 'en-US' ? 'en-US' : 'zh-CN'
  const errorText = (code?: string | null) => t(`errors.${code && i18n.exists(`emotion:errors.${code}`) ? code : 'analysis_failed'}` as `errors.${keyof typeof emotion.errors}`)
  const reportError = (e: unknown) => { const message = e instanceof Error ? e.message : ''; const key = Object.keys(i18n.getResourceBundle(language, 'emotion').errors).find(k => message.includes(k)); toast(errorText(key), 'error') }
  const go = (id: EmotionPage, symbol?: string) => navigate(`/short-term${id === 'overview' ? '' : `/${id}`}${symbol ? `/${encodeURIComponent(symbol)}` : ''}${selected === 'latest' ? '' : `?publication=${encodeURIComponent(selected)}`}`)
  const choosePublication = (id: string) => { setParams(id === 'latest' ? {} : { publication: id }); setRawOpen(false) }
  const generate = async () => {
    setBusy(true)
    pendingKey.current ||= crypto.randomUUID()
    try {
      await emotionApi.run({ request_key: pendingKey.current, language, ...(target ? { target_trade_date: target } : {}) })
      pendingKey.current = null
      choosePublication('latest')
      await load()
    } catch (e) { reportError(e); await load() }
    finally { setBusy(false) }
  }
  const stop = async () => {
    if (!active || !await requestConfirm(t('cancelConfirm'))) return
    try { await emotionApi.cancel(active.id); await load(); toast(t('cancelled')) } catch (e) { reportError(e) }
  }
  const saveNote = async () => {
    if (!note.trim() || (url.trim() && !/^https?:\/\//.test(url.trim()))) { toast(t('noteValidation'), 'error'); return }
    setSaving(true)
    try { await emotionApi.context(note.trim(), url.trim() || null); setNoteOpen(false); setNote(''); setUrl(''); await load(); toast(t('saved'), 'success') }
    catch (e) { reportError(e) } finally { setSaving(false) }
  }
  const openSettings = () => { const s = data?.settings || defaultSettings; setSettings(s); setFocus(s.focus_symbols.map(s => s.split('.')[0]).join(', ')); setSettingsOpen(true) }
  const saveSettings = async () => {
    const codes = focus.trim() ? focus.trim().split(/[,，\s]+/) : []
    if (codes.length > 20 || new Set(codes).size !== codes.length || codes.some(c => !/^[036]\d{5}$/.test(c))) { toast(t('focusInvalid'), 'error'); return }
    if (settings.schedule_time < '06:00' || settings.schedule_time > '09:10') { toast(t('scheduleInvalid'), 'error'); return }
    setSaving(true)
    try { await emotionApi.settings({ ...settings, language, focus_symbols: codes.map(c => c + (c.startsWith('6') ? '.SH' : '.SZ')) }); setSettingsOpen(false); await load(); toast(t('saved'), 'success') }
    catch (e) { reportError(e) } finally { setSaving(false) }
  }
  const changeNote = async (id: string, status: 'open' | 'archived') => {
    if (status === 'archived' && !await requestConfirm(t('archiveConfirm'))) return
    try { await emotionApi.contextStatus(id, status); await load() } catch (e) { reportError(e) }
  }
  const exportSnapshot = () => {
    if (!publication) return
    const objectUrl = URL.createObjectURL(new Blob([JSON.stringify(publication, null, 2)], { type: 'application/json' }))
    const a = document.createElement('a'); a.href = objectUrl; a.download = `panwatch-sentiment-v${publication.revision}.json`; a.click()
    window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1000); toast(t('exported'))
  }
  if (current === 'observations') return <div className="space-y-5"><Link className="text-sm text-primary" to="/short-term">← {t('back')}</Link><Suspense fallback={<p>{t('loading')}</p>}><LegacyObservations /></Suspense></div>
  return <div className="max-w-[1500px] mx-auto min-w-0">
    <header className="flex flex-wrap justify-between gap-5 mb-6"><div><p className="text-[10px] tracking-widest text-muted-foreground uppercase mb-2">{t('eyebrow')}</p><h1 className="text-2xl font-semibold tracking-tight flex items-center gap-2"><Compass className="w-6 h-6 text-primary" />{page === 'overview' ? t('title') : t(`pages.${page}`)}</h1><p className="text-sm text-muted-foreground mt-2 max-w-xl leading-6">{t('subtitle')}</p></div><div className="flex flex-wrap items-start gap-2"><Button variant="outline" onClick={() => setNoteOpen(true)}><Plus className="w-4 h-4 mr-1" />{t('context')}</Button><Button variant="outline" onClick={openSettings} aria-label={t('settings')}><Settings2 className="w-4 h-4" /></Button><Button onClick={() => void generate()} disabled={busy || !!active || !target}><RefreshCw className={`w-4 h-4 mr-2 ${busy || active ? 'animate-spin motion-reduce:animate-none' : ''}`} />{busy || active ? t('running') : publication ? t('refresh') : t('generate')}</Button></div></header>
    <div className="grid lg:grid-cols-[180px_minmax(0,1fr)] gap-6">
      <aside className="min-w-0"><nav className="flex lg:flex-col gap-1 overflow-x-auto scrollbar pb-2" aria-label={t('title')}>{pages.map(({ id, icon: Icon }) => <button key={id} onClick={() => go(id)} aria-current={page === id ? 'page' : undefined} className={`flex items-center gap-2 px-3 py-3 rounded-xl text-sm whitespace-nowrap text-left focus-visible:ring-2 focus-visible:ring-primary ${page === id ? 'text-primary bg-primary/10 font-medium' : 'text-muted-foreground hover:bg-accent'}`}><Icon className="w-4 h-4 shrink-0" />{t(`pages.${id}`)}</button>)}</nav><div className="hidden lg:block border-t mt-6 pt-5 px-3 space-y-3"><p className="text-xs text-muted-foreground leading-6">{data?.settings.schedule_enabled ? t('scheduleOn', { time: data.settings.schedule_time }) : t('scheduleOff')}</p><Link to="/short-term/observations" className="text-xs text-primary inline-block">{t('raw')} ↗</Link></div></aside>
      <main className="min-w-0 space-y-5">
        <div className="flex flex-wrap justify-between items-center gap-3"><div className="flex flex-wrap gap-2 items-center"><Label htmlFor="emotion-target" className="text-xs text-muted-foreground">{t('target')}</Label><Input id="emotion-target" type="date" value={target} onChange={e => { customTarget.current = true; pendingKey.current = null; setTarget(e.target.value) }} className="w-40 h-9 text-xs" /></div><div className="flex flex-wrap items-center gap-2">{!!data?.history.length && <Select value={selected} onValueChange={choosePublication}><SelectTrigger className="w-56 max-w-full h-9" aria-label={t('history')}><SelectValue /></SelectTrigger><SelectContent><SelectItem value="latest">{t('latest')}</SelectItem>{data.history.map(h => <SelectItem key={h.id} value={h.id}>{t('version', { version: h.revision })} · {h.target_trade_date}</SelectItem>)}</SelectContent></Select>}{publication && <Button variant="ghost" size="sm" onClick={() => setRawOpen(true)}>{t('version', { version: publication.revision })}</Button>}</div></div>
        {(failed || historyFailed) && <div role="alert" className="rounded-xl border p-4 text-sm flex flex-wrap justify-between gap-3"><span>{t('loadFailed')}</span><Button size="sm" variant="outline" onClick={() => historyFailed ? choosePublication('latest') : void load()}>{t('retry')}</Button></div>}
        {active && <div role="status" className="rounded-xl border border-primary/25 bg-primary/5 p-4 flex flex-wrap justify-between gap-3 items-center"><div><p className="text-sm font-medium">{t('running')} · {t(`runStates.${active.status}`)}</p><p className="text-xs text-muted-foreground mt-1">{active.events.length ? t(`eventTypes.${active.events[active.events.length - 1].type}` as 'eventTypes.collecting') : t('stepFacts')}</p></div><Button variant="outline" size="sm" onClick={() => void stop()}>{t('cancel')}</Button></div>}
        {lastRun && ['failed', 'interrupted'].includes(lastRun.status) && !active && <div role="alert" className="rounded-xl border border-destructive/25 p-4"><h2 className="text-sm font-medium">{t('errorLabel')}</h2><p className="text-sm text-muted-foreground mt-2 leading-6">{errorText(lastRun.error_code)}</p></div>}
        {publication && <><div className="text-[11px] text-muted-foreground flex flex-wrap gap-x-4 gap-y-2"><span>{t('planTarget', { date: publication.target_trade_date })}</span><span className="flex items-center gap-1"><Clock3 className="w-3 h-3" />{t('marketDate', { date: publication.market_as_of })}</span><span>{t('cutoff', { time: emotionStamp(publication.knowledge_cutoff) })}</span><span>{t('published', { time: emotionStamp(publication.published_at) })}</span></div><div className="rounded-xl border bg-accent/20 px-4 py-3 text-xs text-muted-foreground leading-6">{selected !== 'latest' || (data?.target_trade_date && publication.target_trade_date < data.target_trade_date) ? <p>{t('historical')}</p> : null}<p>{t('lifecycle.boundary')}</p>{data && data.input_version !== publication.input_version && selected === 'latest' && <p className="text-primary mt-1">{t('pendingContext')}</p>}</div></>}
        {page === 'validation' && <EmotionSessionValidation target={target} />}
        {publication && page === 'evidence' && <EmotionRegulatory publication={publication} onEvidence={setDetail} />}
        {publication && page === 'evidence' && <EmotionConstraints publication={publication} onEvidence={setDetail} />}
        {publication && <EmotionLifecycle publication={publication} page={page} active={!!active} onRefresh={load} onEvidence={setDetail} />}
        {publication?.schema_version !== '1.0' && publication ? <p role="alert">{t('unsupportedVersion')}</p> : publication && data ? <div className="space-y-5">{publication.analysis.blocks.filter(b => b.page === page).map(block => <EmotionBlockRenderer key={`${publication.id}:${block.id}`} block={block} publication={publication} workspace={data} stock={stock} onEvidence={setDetail} onStock={symbol => go('stock', symbol)} onPublication={choosePublication} />)}</div> : !historyFailed && <section className="rounded-2xl border bg-card p-6 sm:p-10"><Bot className="w-9 h-9 text-primary mb-5" /><h2 className="text-xl font-semibold">{data && selected === 'latest' ? t('empty') : t('loading')}</h2><p className="mt-4 text-sm text-muted-foreground leading-7 max-w-2xl">{t('emptyHint')}</p><div className="grid sm:grid-cols-3 gap-3 mt-7">{(['stepFacts', 'stepAgent', 'stepMemory'] as const).map((key, i) => <div key={key} className="rounded-xl border p-4"><span className="text-xs text-primary">{String(i + 1).padStart(2, '0')}</span><h3 className="text-sm font-medium mt-2">{t(key)}</h3></div>)}</div></section>}
        {(page === 'evidence' || (!publication && page === 'overview')) && data && <EmotionCard title={t('notesTitle')} extra={<Button size="sm" variant="ghost" onClick={() => setNoteOpen(true)}>{t('context')}</Button>}><p className="text-xs text-muted-foreground leading-6 mb-4">{t('notesHint')}</p><div className="space-y-4">{data.notes.map(n => <article key={n.id} className="rounded-xl border p-4"><p className="text-sm leading-7 whitespace-pre-wrap break-words">{n.content}</p><div className="mt-3 flex flex-wrap items-center justify-between gap-3"><span className="text-xs text-muted-foreground">{t(n.status === 'open' ? 'open' : 'archived')} · {t('evidenceStates.user_unverified')} · {emotionStamp(n.created_at)}</span><Button size="sm" variant="ghost" onClick={() => void changeNote(n.id, n.status === 'open' ? 'archived' : 'open')}>{t(n.status === 'open' ? 'archive' : 'restore')}</Button></div></article>)}{!data.notes.length && <p className="text-sm text-muted-foreground">{t('noNotes')}</p>}</div></EmotionCard>}
        {!publication && page === 'agent' && data && <EmotionCard title={t('runDetails')}><div className="space-y-3">{data.runs.map(r => <div key={r.id} className="rounded-xl border p-4 text-sm"><p>{r.target_trade_date} · {t(`runStates.${r.status}`)}</p>{r.error_code && <p className="mt-2 text-muted-foreground">{errorText(r.error_code)}</p>}</div>)}{!data.runs.length && <p className="text-sm text-muted-foreground">{t('noRuns')}</p>}</div></EmotionCard>}
      </main>
    </div>
    <Dialog open={noteOpen} onOpenChange={setNoteOpen}><DialogContent className="max-w-xl"><DialogHeader><DialogTitle>{t('context')}</DialogTitle><DialogDescription>{t('notesHint')}</DialogDescription></DialogHeader><div className="space-y-4"><div><Label htmlFor="emotion-note">{t('noteLabel')}</Label><textarea id="emotion-note" value={note} maxLength={4000} onChange={e => setNote(e.target.value)} placeholder={t('notePlaceholder')} className="mt-2 w-full min-h-32 rounded-xl border bg-background px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary" /></div><div><Label htmlFor="emotion-url">{t('urlLabel')}</Label><Input id="emotion-url" type="url" value={url} maxLength={2048} onChange={e => setUrl(e.target.value)} placeholder={t('urlPlaceholder')} className="mt-2" /></div><Button onClick={() => void saveNote()} disabled={saving || !note.trim()}>{t('save')}</Button></div></DialogContent></Dialog>
    <Dialog open={settingsOpen} onOpenChange={setSettingsOpen}><DialogContent className="max-w-xl"><DialogHeader><DialogTitle>{t('settings')}</DialogTitle><DialogDescription>{t('focusHint')}</DialogDescription></DialogHeader><div className="space-y-5"><div><Label htmlFor="emotion-focus">{t('focusLabel')}</Label><Input id="emotion-focus" value={focus} onChange={e => setFocus(e.target.value)} placeholder={t('focusPlaceholder')} className="mt-2" /></div><div className="border-t pt-5"><div className="flex items-center justify-between gap-3"><Label htmlFor="emotion-schedule">{t('scheduleLabel')}</Label><Switch id="emotion-schedule" checked={settings.schedule_enabled} onCheckedChange={schedule_enabled => setSettings({ ...settings, schedule_enabled })} /></div><p className="text-xs leading-6 text-muted-foreground mt-3">{t('scheduleHint')}</p></div><div><Label htmlFor="emotion-time">{t('scheduleTime')}</Label><Input id="emotion-time" type="time" min="06:00" max="09:10" value={settings.schedule_time} onChange={e => setSettings({ ...settings, schedule_time: e.target.value })} className="mt-2" /></div><div className="border-t pt-4 space-y-4"><div className="flex justify-between gap-3"><Label htmlFor="emotion-monitor">{t('lifecycle.autoMonitor')}</Label><Switch id="emotion-monitor" checked={settings.monitoring_enabled} onCheckedChange={monitoring_enabled => setSettings({ ...settings, monitoring_enabled })} /></div><div className="flex justify-between gap-3"><Label htmlFor="emotion-review">{t('lifecycle.autoReview')}</Label><Switch id="emotion-review" checked={settings.postmarket_enabled} onCheckedChange={postmarket_enabled => setSettings({ ...settings, postmarket_enabled })} /></div><p className="text-xs text-muted-foreground leading-6">{t('lifecycle.autoHint')}</p></div><Button onClick={() => void saveSettings()} disabled={saving}>{t('save')}</Button></div></DialogContent></Dialog>
    <Dialog open={!!detail} onOpenChange={open => { if (!open) setDetail(null) }}><DialogContent className="max-w-2xl"><DialogHeader><DialogTitle>{detail?.title}</DialogTitle><DialogDescription>{detail ? `${detail.source} · ${t(`evidenceStates.${detail.status}` as 'evidenceStates.observed')}` : t('openEvidence')}</DialogDescription></DialogHeader>{detail && <div className="space-y-4 min-w-0"><p className="text-xs text-muted-foreground">{t('published', { time: emotionStamp(detail.published_at) })} · {t('observed', { time: emotionStamp(detail.observed_at) })}</p><pre className="rounded-xl border bg-accent/30 p-4 text-xs leading-6 whitespace-pre-wrap break-all max-h-80 overflow-y-auto scrollbar">{JSON.stringify(detail.content, null, 2)}</pre>{detail.url && /^https?:\/\//.test(detail.url) && <a className="text-sm text-primary" href={detail.url} target="_blank" rel="noopener noreferrer">{t('sourceLink')} ↗</a>}<p className="text-[10px] text-muted-foreground break-all">{t('hash')}：{detail.content_hash}</p></div>}</DialogContent></Dialog>
    <Dialog open={rawOpen} onOpenChange={setRawOpen}><DialogContent className="max-w-3xl"><DialogHeader><DialogTitle>{t('rawTitle')}</DialogTitle><DialogDescription>{t('cutoff', { time: emotionStamp(publication?.knowledge_cutoff || null) })}</DialogDescription></DialogHeader><pre className="max-h-[55vh] overflow-auto scrollbar rounded-xl border bg-accent/30 p-4 text-xs leading-6 whitespace-pre-wrap break-all">{JSON.stringify(publication, null, 2)}</pre><Button onClick={exportSnapshot}>{t('export')}</Button></DialogContent></Dialog>
  </div>
}
