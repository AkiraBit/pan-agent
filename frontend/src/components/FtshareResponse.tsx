import { Download } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import type { FtshareResult } from '@panwatch/api'
import { Badge } from '@panwatch/base-ui/components/ui/badge'
import { Button } from '@panwatch/base-ui/components/ui/button'

const PREVIEW_LIMIT = 80_000

export function FtshareResponse({ result, name, successful }: { result: FtshareResult; name: string; successful?: boolean }) {
  const { t } = useTranslation('configuration')
  const success = successful ?? (result.http_status < 400 && [null, 0, 200].includes(result.business_code))
  const raw = result.response_json
  return <section aria-label={t('fuyao.rest.response')} className="space-y-2 border-t border-border/60 pt-3">
    <div className="flex flex-wrap items-center justify-between gap-2">
      <div className="flex flex-wrap gap-1.5" role="status">
        <Badge variant={success ? 'outline' : 'destructive'}>{t('fuyao.rest.httpStatus', { status: result.http_status })}</Badge>
        {result.business_code !== null && <Badge variant={success ? 'outline' : 'destructive'}>{t('fuyao.rest.businessCode', { code: result.business_code })}</Badge>}
      </div>
      {raw !== null && <Button type="button" variant="outline" size="sm" onClick={() => {
        const url = URL.createObjectURL(new Blob([raw], { type: 'application/json' }))
        const link = document.createElement('a')
        link.href = url
        link.download = name + '.json'
        link.click()
        window.setTimeout(() => URL.revokeObjectURL(url), 1000)
      }}><Download className="size-4" />{t('fuyao.rest.download')}</Button>}
    </div>
    {raw === null ? <p className="text-xs text-muted-foreground">{result.message || t('fuyao.rest.noResponse')}</p>
      : <pre className="scrollbar max-h-96 overflow-auto whitespace-pre-wrap break-all rounded-lg bg-muted p-3 text-xs">{raw.slice(0, PREVIEW_LIMIT)}</pre>}
    {(raw?.length ?? 0) > PREVIEW_LIMIT && <p className="text-xs text-muted-foreground">{t('fuyao.rest.preview', { count: PREVIEW_LIMIT })}</p>}
  </section>
}
