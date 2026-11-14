import { useEffect, useState } from 'react'
import { reviewRequest, exchangeDate, type ReviewResponse } from './data'

export function useReview<T>(resource: string, date = '', refresh = 0, enabled = true) {
  const [state, setState] = useState<{ key: string; data?: ReviewResponse<T>; error?: string; loading: boolean }>({ key: '', loading: true })
  const key = `${resource}:${date}`
  const autoRefresh = !date || (resource.startsWith('minute/') && date === exchangeDate())
  useEffect(() => {
    if (!enabled) return
    const controller = new AbortController()
    let timer: ReturnType<typeof setTimeout>
    setState(previous => ({ key, loading: true, data: previous.key === key ? previous.data : undefined }))
    const load = async () => {
      try {
        const data = await reviewRequest<T>(resource, date, controller.signal)
        if (!controller.signal.aborted) setState({ key, data, loading: false })
      } catch (error) {
        if (!controller.signal.aborted) setState(previous => ({ key, data: previous.key === key ? previous.data : undefined,
          error: error instanceof Error ? error.message : 'unavailable', loading: false }))
      } finally {
        if (!controller.signal.aborted && autoRefresh) timer = setTimeout(() => { if (!document.hidden) void load(); else timer = setTimeout(load, 30000) }, resource === 'board' ? 15000 : 60000)
      }
    }
    void load()
    return () => { controller.abort(); clearTimeout(timer) }
  }, [resource, date, refresh, enabled, key, autoRefresh])
  return state.key === key ? state : { key, loading: true, data: undefined, error: undefined }
}
