import { useEffect, useState } from 'react'

export function useEtf<T>(key: string, loader: (signal: AbortSignal) => Promise<T>, enabled: boolean, refresh: number, poll?: (data: T) => number) {
  const [state, setState] = useState<{ key: string; data?: T; error?: boolean; loading: boolean }>({ key: '', loading: true })
  useEffect(() => {
    if (!enabled) return
    const controller = new AbortController()
    let timer: ReturnType<typeof setTimeout>
    const load = async () => {
      let delay = 60000
      setState(previous => ({ key, data: previous.key === key ? previous.data : undefined, loading: !previous.data || previous.key !== key }))
      try {
        const data = await loader(controller.signal)
        delay = poll?.(data) ?? 60000
        if (!controller.signal.aborted) setState({ key, data, loading: false })
      } catch {
        if (!controller.signal.aborted) setState(previous => ({ key, data: previous.key === key ? previous.data : undefined, error: true, loading: false }))
      } finally {
        if (!controller.signal.aborted) timer = setTimeout(() => { if (!document.hidden) void load(); else timer = setTimeout(load, 60000) }, delay)
      }
    }
    void load()
    return () => { controller.abort(); clearTimeout(timer) }
    // loader is bound to this resource key; refresh explicitly reloads it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, enabled, refresh])
  return state.key === key ? state : { key, loading: true, data: undefined, error: false }
}

