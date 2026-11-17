import { createContext, lazy, Suspense, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from 'react'
import { Bell, MessageCircle, AlertCircle } from 'lucide-react'
import { useLocation, useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { notificationsApi, type AssistantActivityTask, type NotificationItem, type NotificationTarget } from '@panwatch/api'
import { Popover, PopoverContent, PopoverTrigger } from '@panwatch/base-ui/components/ui/popover'
import { useToast } from '@panwatch/base-ui/components/ui/toast'
import { useNotifications } from '@/hooks/useNotifications'
import { useAssistantActivity } from '@/hooks/useAssistantActivity'
import { claimNotifications, notificationTitle } from '@/lib/notifications'
import NotificationInbox from './NotificationInbox'

const NotificationPanel = lazy(() => import('./NotificationPanel'))
const SourceDialog = lazy(() => import('./NotificationSourceDialog'))
const TaskPanel = lazy(() => import('@/components/assistant/AssistantActivityPanel'))
const ExportDialog = lazy(() => import('@/components/assistant/AssistantContextExportDialog').then(module => ({ default: module.AssistantContextExportDialog })))
const Context = createContext({ unread: 0, pending: 0, active: 0, tasks: [] as AssistantActivityTask[], disconnected: false,
  monitor: null as ReturnType<typeof useNotifications> | null, open: () => {}, openTasks: () => {}, openItem: async (_item: NotificationItem) => {} })
export function useActiveAssistantTasks() { return useContext(Context).tasks }
const foreground = () => document.visibilityState === 'visible' && document.hasFocus()
export function NotificationBell() {
  const { unread, pending, active, disconnected, monitor, open, openTasks, openItem } = useContext(Context)
  const { pathname } = useLocation()
  const onAssistantPage = pathname === '/assistant' || pathname.startsWith('/assistant/')
  const [previewOpen, setPreviewOpen] = useState(false)
  const handingOff = useRef(false)
  const handoffTimer = useRef<ReturnType<typeof setTimeout>>()
  const closeTimer = useRef<ReturnType<typeof setTimeout>>()
  const openedByHover = useRef(false)
  const restoreBellFocus = useRef(false)
  const bellRef = useRef<HTMLButtonElement>(null)
  const previewRef = useRef<HTMLDivElement>(null)
  useEffect(() => () => { clearTimeout(handoffTimer.current); clearTimeout(closeTimer.current) }, [])
  const keepPreviewOpen = () => clearTimeout(closeTimer.current)
  const openOnHover = () => {
    keepPreviewOpen()
    if (!previewOpen) {
      handingOff.current = false
      openedByHover.current = true
      setPreviewOpen(true)
    }
  }
  const closeAfterHover = () => {
    keepPreviewOpen()
    if (!openedByHover.current) return
    // Allow the pointer to cross the gap between the bell and its portal.
    closeTimer.current = setTimeout(() => {
      if (!previewRef.current?.contains(document.activeElement)) setPreviewOpen(false)
    }, 180)
  }
  const { t } = useTranslation('configuration')
  return <>
    {active > 0 && !onAssistantPage && <button type="button" className="app-nav-control relative h-10 min-w-10 gap-1.5 2xl:px-2.5" onClick={openTasks} title={t('notifications.taskEntry', { count: active }) as string} aria-label={t('notifications.taskEntry', { count: active }) as string} data-testid="assistant-task-entry">
      <MessageCircle aria-hidden className="h-4 w-4 text-primary" />
      <span aria-hidden className="absolute right-1.5 top-1.5 size-1.5 rounded-full bg-primary 2xl:hidden" />
      <span aria-hidden className="hidden text-[12px] 2xl:inline">{t('notifications.taskEntryShort', { count: active })}</span>
    </button>}
    <Popover open={previewOpen} onOpenChange={next => { keepPreviewOpen(); if (next) { handingOff.current = false; openedByHover.current = false }; setPreviewOpen(next) }}>
      <PopoverTrigger asChild>
        <button
          ref={bellRef}
          type="button"
          className="app-nav-control relative size-10"
          onPointerEnter={event => { if (event.pointerType === 'mouse') openOnHover() }}
          onPointerLeave={event => { if (event.pointerType === 'mouse') closeAfterHover() }}
          onClick={event => {
            if (!previewOpen || !openedByHover.current) return
            // A click pins an already visible preview; the next click dismisses it.
            event.preventDefault()
            keepPreviewOpen()
            openedByHover.current = false
            previewRef.current?.focus()
          }}
          aria-label={t('notifications.bell', { count: unread }) as string}
          data-testid="notification-bell"
        >
          {disconnected ? <AlertCircle aria-hidden className="size-[17px]" /> : <Bell aria-hidden className="size-[17px]" />}
          {unread > 0 && <span data-testid="notification-badge" aria-hidden className="absolute right-0.5 top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-primary px-0.5 text-[9px] font-semibold tabular-nums text-primary-foreground ring-2 ring-card">{unread > 99 ? '99+' : unread}</span>}
          {unread === 0 && pending > 0 && <span aria-label={t('notifications.pending') as string} className="absolute right-1.5 top-1.5 size-1.5 rounded-full bg-primary" />}
        </button>
      </PopoverTrigger>
      <PopoverContent
        ref={previewRef}
        data-testid="notification-preview"
        align="end"
        sideOffset={10}
        collisionPadding={8}
        onPointerEnter={event => { if (event.pointerType === 'mouse') keepPreviewOpen() }}
        onPointerLeave={event => { if (event.pointerType === 'mouse') closeAfterHover() }}
        onOpenAutoFocus={event => { if (openedByHover.current) event.preventDefault() }}
        onEscapeKeyDown={() => { restoreBellFocus.current = !openedByHover.current }}
        onCloseAutoFocus={event => {
          if (restoreBellFocus.current) {
            restoreBellFocus.current = false
            event.preventDefault()
            bellRef.current?.focus({ preventScroll: true })
          } else if (handingOff.current || openedByHover.current) {
            event.preventDefault()
          }
        }}
        className="w-[min(23rem,calc(100vw-1rem))] overflow-hidden p-0 shadow-lg !animate-none"
      >
        <Suspense fallback={<p role="status" className="p-4 text-[12px]">{t('notifications.loading')}</p>}>
          {monitor && <NotificationInbox monitor={monitor} onHistory={() => { handingOff.current = true; setPreviewOpen(false); handoffTimer.current = setTimeout(open, 0) }} onOpen={async item => { handingOff.current = true; setPreviewOpen(false); await openItem(item) }} />}
        </Suspense>
      </PopoverContent>
    </Popover>
  </>
}
export function NotificationProvider({ children }: { children: ReactNode }) {
  const tasks = useAssistantActivity(true)
  const monitor = useNotifications(tasks.activity.active_tasks.length)
  const { unread, changing, error, mutate } = monitor
  const [open, setOpen] = useState(false)
  const [tasksOpen, setTasksOpen] = useState(false)
  const [target, setTarget] = useState<Exclude<NotificationTarget, { kind: 'assistant_conversation' }> | null>(null)
  const [focused, setFocused] = useState(foreground)
  const location = useLocation(); const navigate = useNavigate()
  const { t } = useTranslation('configuration'); const { toast } = useToast()
  const mounted = useRef(true)
  const currentConversation = Number(/^\/assistant\/(\d+)$/.exec(location.pathname)?.[1]) || null
  const tr = useCallback((key: string, options?: Record<string, unknown>) => (t as unknown as (key: string, options?: Record<string, unknown>) => string)(`notifications.${key}`, options), [t])
  useEffect(() => {
    mounted.current = true
    const update = () => setFocused(foreground())
    window.addEventListener('focus', update); window.addEventListener('blur', update); document.addEventListener('visibilitychange', update)
    return () => { mounted.current = false; window.removeEventListener('focus', update); window.removeEventListener('blur', update); document.removeEventListener('visibilitychange', update) }
  }, [])
  const openItem = useCallback(async (item: NotificationItem) => {
    try {
      const resource = await notificationsApi.target(item.id)
      if (!mounted.current) return
      void mutate({ ids: [item.id] }).catch(() => {})
      setOpen(false)
      if (resource.kind === 'assistant_conversation') navigate(`/assistant/${resource.conversation_id}`)
      else setTarget(resource)
    } catch {
      if (mounted.current) { toast(tr('sourceGone'), 'error'); void monitor.refresh() }
    }
  }, [mutate, navigate, toast, tr, monitor.refresh])
  useEffect(() => {
    if (!focused) return
    const visible = unread.filter(item => item.source === 'assistant' && item.actions.some(action => action.kind === 'assistant_conversation' && action.conversation_id === currentConversation))
    if (visible.length && !changing && !error) void mutate({ ids: visible.map(item => item.id) }).catch(() => {})
    const candidates = unread.filter(item => item.toast_eligible && item.available && !item.resolved_at && !visible.includes(item))
    const claimed = claimNotifications(candidates.map(item => item.id))
    const fresh = candidates.filter(item => claimed.includes(item.id))
    if (fresh.length === 1) {
      const item = fresh[0]
      toast(tr(`toasts.${item.event_type}`, { title: notificationTitle(item, t as unknown as (key: string) => string) }), item.event_type.endsWith('_failed') ? 'error' : item.event_type.endsWith('_completed') ? 'success' : 'info', { label: tr('view'), onClick: () => void openItem(item) })
    } else if (fresh.length > 1) toast(tr('multiple', { count: fresh.length }), 'info', { label: tr('view'), onClick: () => setOpen(true) })
  }, [unread, focused, currentConversation, changing, error, mutate, openItem, toast, tr])
  return <Context.Provider value={{ unread: monitor.summary.unread_count, pending: monitor.summary.pending_action_count, active: tasks.activity.active_tasks.length, tasks: tasks.activity.active_tasks, monitor, disconnected: monitor.disconnected, openItem, open: () => { setOpen(true); void monitor.refresh() }, openTasks: () => { setTasksOpen(true); void tasks.refresh() } }}>
    {children}
    <Suspense fallback={null}>
      {open && <NotificationPanel monitor={monitor} onClose={() => setOpen(false)} onOpen={openItem} />}
      {target?.kind === 'assistant_export' ? <ExportDialog conversationId={target.conversation_id} exportId={target.export_id} onClose={() => setTarget(null)} /> : target && <SourceDialog target={target} onClose={() => setTarget(null)} />}
      {tasksOpen && <TaskPanel open onOpenChange={setTasksOpen} monitor={tasks} progressOnly onOpenConversation={id => { setTasksOpen(false); navigate(`/assistant/${id}`) }} />}
    </Suspense>
  </Context.Provider>
}
