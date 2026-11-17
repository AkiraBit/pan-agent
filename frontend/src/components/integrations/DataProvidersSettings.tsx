import { useEffect, useState, type FormEvent } from 'react'
import { ExternalLink, KeyRound, Pencil, Plus } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { fetchAPI } from '@panwatch/api/client'
import { Badge } from '@panwatch/base-ui/components/ui/badge'
import { Button } from '@panwatch/base-ui/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from '@panwatch/base-ui/components/ui/dialog'
import { Input } from '@panwatch/base-ui/components/ui/input'
import { Label } from '@panwatch/base-ui/components/ui/label'
import { useConfirm } from '@panwatch/base-ui/components/ui/confirm-dialog'
import { useToast } from '@panwatch/base-ui/components/ui/toast'

const PROVIDER_LINKS = {
  fuyao: [
    { href: 'https://fuyao.aicubes.cn/admin/', label: 'configuration:fuyao.issueKey', external: true },
    { href: '/datasources', label: 'configuration:fuyao.dataSources', external: false },
    { href: '/integrations/mcp?provider=fuyao', label: 'configuration:fuyao.mcpSettings', external: false },
  ],
  ftshare: [
    { href: 'https://ftai.chat/me/profile', label: 'configuration:ftshare.issueKey', external: true },
    { href: 'https://market.ft.tech/gateway/doc/p/pb8eizu3', label: 'configuration:ftshare.docs', external: true },
  ],
} as const

type CredentialStatus = { configured: boolean; masked_key: string | null }

function ProviderCard({ provider }: { provider: keyof typeof PROVIDER_LINKS }) {
  const { t } = useTranslation(['configuration', 'common'])
  const path = `/settings/data-providers/${provider}`
  const inputId = `${provider}-api-key`
  const { toast } = useToast()
  const confirmAction = useConfirm()
  const [credential, setCredential] = useState<CredentialStatus | null>(null)
  const [editing, setEditing] = useState(false)
  const [key, setKey] = useState('')
  const [busy, setBusy] = useState(false)
  const [loadFailed, setLoadFailed] = useState(false)
  const [revision, setRevision] = useState(0)
  const configured = credential?.configured ?? false
  const name = t(`configuration:${provider}.provider`)
  const dialogTitle = t(configured ? 'configuration:dataProviders.editKeyTitle' : 'configuration:dataProviders.addKeyTitle', { provider: name })

  useEffect(() => {
    const controller = new AbortController()
    fetchAPI<CredentialStatus>(path, { signal: controller.signal }).then(result => {
      if (!controller.signal.aborted) setCredential(result)
    }).catch(() => { if (!controller.signal.aborted) setLoadFailed(true) })
    return () => controller.abort()
  }, [path, revision])

  async function update(method: 'PUT' | 'DELETE') {
    setBusy(true)
    try {
      const result = await fetchAPI<CredentialStatus>(path, {
        method, ...(method === 'PUT' ? { body: JSON.stringify({ api_key: key.trim() }) } : {}),
      })
      setCredential(result)
      setKey('')
      setEditing(false)
      toast(t(`configuration:${provider}.${method === 'PUT' ? 'keySaved' : 'keyRemoved'}`), 'success')
    } catch (error) {
      toast(error instanceof Error ? error.message : t(`configuration:${provider}.loadFailed`), 'error')
    } finally { setBusy(false) }
  }

  function save(event: FormEvent) {
    event.preventDefault()
    if (!busy && key.trim()) void update('PUT')
  }

  function changeEditing(open: boolean) {
    if (busy) return
    setEditing(open)
    if (!open) setKey('')
  }

  return (
    <section aria-labelledby={`${provider}-provider-heading`} className="flex min-w-0 flex-col rounded-xl border border-border/70 p-4">
      <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
        <h4 id={`${provider}-provider-heading`} className="text-sm font-semibold">{name}</h4>
        {credential && <Badge variant={configured ? 'success' : 'secondary'} role="status" className={configured ? 'dark:text-emerald-400' : undefined}>
          {t(`configuration:${provider}.${configured ? 'configured' : 'notConfigured'}`)}
        </Badge>}
      </div>
      <Dialog open={editing} onOpenChange={changeEditing}>
        <div className="mt-3 flex min-h-12 flex-wrap items-center justify-between gap-x-3 gap-y-1 rounded-lg bg-muted/45 px-3 py-1">
          {loadFailed ? <>
            <p className="text-xs text-destructive" role="alert">{t(`configuration:${provider}.loadFailed`)}</p>
            <Button variant="ghost" size="sm" onClick={() => { setLoadFailed(false); setRevision(n => n + 1) }}>{t('configuration:dataProviders.retry')}</Button>
          </> : !credential ? <p className="text-xs text-muted-foreground" role="status">{t('common:states.loading')}</p> : <>
            <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1">
              <span className="text-xs font-medium text-muted-foreground">{t('configuration:dataProviders.keyLabel')}</span>
              {configured && <code dir="ltr" className="text-sm tabular-nums text-foreground">{credential.masked_key ?? '****'}</code>}
            </div>
            <DialogTrigger asChild>
              <Button type="button" variant={configured ? 'ghost' : 'outline'} size={configured ? 'icon' : 'sm'}
                aria-label={dialogTitle} title={configured ? dialogTitle : undefined}>
                {configured ? <Pencil className="h-4 w-4" aria-hidden="true" /> : <>
                  <Plus className="h-3.5 w-3.5" aria-hidden="true" />{t('configuration:dataProviders.addKey')}
                </>}
              </Button>
            </DialogTrigger>
          </>}
        </div>
        <DialogContent className="max-w-md">
          <DialogHeader className="pr-8">
            <DialogTitle>{dialogTitle}</DialogTitle>
            <DialogDescription>{t(`configuration:${provider}.keyHint`)}</DialogDescription>
          </DialogHeader>
          <form onSubmit={save} aria-busy={busy}>
            <Label htmlFor={inputId} className="mb-0">{t('configuration:dataProviders.keyLabel')}</Label>
            <Input id={inputId} type="password" autoComplete="new-password" maxLength={512} value={key}
              onChange={event => setKey(event.target.value)} disabled={busy} className="mt-2"
              placeholder={t(configured ? 'configuration:dataProviders.replacePlaceholder' : 'configuration:dataProviders.keyPlaceholder')} />
            <div className="mt-5 flex flex-wrap items-center justify-end gap-2">
              {configured && <Button type="button" variant="ghost" size="sm" className="mr-auto hover:text-destructive" disabled={busy} onClick={async () => {
                if (await confirmAction(t(`configuration:${provider}.clearConfirm`), { destructive: true })) await update('DELETE')
              }}>{t('configuration:dataProviders.clearKey')}</Button>}
              <Button type="button" variant="outline" size="sm" disabled={busy} onClick={() => changeEditing(false)}>{t('common:actions.cancel')}</Button>
              <Button type="submit" size="sm" disabled={busy || !key.trim()}>{t('common:actions.save')}</Button>
            </div>
          </form>
        </DialogContent>
      </Dialog>
      <div className="mt-3 flex flex-wrap gap-x-4 gap-y-2 text-xs">
        {PROVIDER_LINKS[provider].map(({ href, label, external }) => (
          <a className="inline-flex items-center gap-1 text-muted-foreground underline-offset-4 hover:text-primary hover:underline" key={href} href={href}
            {...(external ? { target: '_blank', rel: 'noopener noreferrer' } : {})}>
            {t(label)}{external && <ExternalLink className="h-3 w-3" aria-hidden="true" />}
          </a>
        ))}
      </div>
    </section>
  )
}

export default function DataProvidersSettings() {
  const { t } = useTranslation('configuration')
  return (
    <section id="sec-data-providers" aria-labelledby="data-provider-heading" className="card p-4 md:p-6 lg:col-span-12 scroll-mt-24">
      <div className="flex items-center gap-3">
        <div className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-primary/10 text-primary"><KeyRound className="h-4 w-4" /></div>
        <h3 id="data-provider-heading" className="text-[13px] font-semibold">{t('dataProviders.title')}</h3>
      </div>
      <div className="mt-4 grid min-w-0 grid-cols-1 gap-3 md:grid-cols-2">
        <ProviderCard provider="fuyao" />
        <ProviderCard provider="ftshare" />
      </div>
    </section>
  )
}
