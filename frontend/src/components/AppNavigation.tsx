import { Link, matchPath, useLocation } from 'react-router-dom'
import { Activity, BellRing, Bot, ClipboardCheck, Clock, Compass, Database, Github, LayoutDashboard, List, MessageCircle, Plug, ScrollText, Settings, Sparkles, TrendingUp, type LucideIcon } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import AccountMenu from '@/components/AccountMenu'
import { NotificationBell } from '@/components/notifications/NotificationProvider'
import type { ThemeMode } from '@/hooks/use-theme'
import type { NavigationItemKey } from '@/i18n/resources'
import { preloadRoute } from '@/router/page-loaders'

const NAV_ITEMS: Array<{ to: string; icon: LucideIcon; labelKey: NavigationItemKey }> = [
  { to: '/', icon: LayoutDashboard, labelKey: 'home' },
  { to: '/etf', icon: TrendingUp, labelKey: 'etf' },
  { to: '/workspace', icon: Activity, labelKey: 'workspace' },
  { to: '/portfolio', icon: List, labelKey: 'portfolio' },
  { to: '/assistant', icon: MessageCircle, labelKey: 'assistant' },
  { to: '/opportunities', icon: Sparkles, labelKey: 'opportunities' },
  { to: '/market-data', icon: Database, labelKey: 'researchData' },
  { to: '/short-term', icon: Compass, labelKey: 'shortTerm' },
  { to: '/paper-trading', icon: Activity, labelKey: 'paperTrading' },
  { to: '/alerts', icon: BellRing, labelKey: 'alerts' },
  { to: '/agents', icon: Bot, labelKey: 'agents' },
  { to: '/evaluations', icon: ClipboardCheck, labelKey: 'evaluations' },
  { to: '/history', icon: Clock, labelKey: 'history' },
  { to: '/datasources', icon: Database, labelKey: 'dataSources' },
  { to: '/integrations/mcp', icon: Plug, labelKey: 'mcp' },
  { to: '/settings', icon: Settings, labelKey: 'settings' },
  { to: '/getting-started', icon: Compass, labelKey: 'gettingStarted' },
]

const MOBILE_COUNT = 5
const DESKTOP_COUNT = 7

interface AppNavigationProps {
  version: string
  mode: ThemeMode
  onSetMode: (mode: ThemeMode) => void
  onOpenLogs: () => void
  onOpenSelfCheck: () => void
}

export default function AppNavigation({ version, mode, onSetMode, onOpenLogs, onOpenSelfCheck }: AppNavigationProps) {
  const { t } = useTranslation(['navigation', 'common'])
  const { pathname } = useLocation()
  const items = NAV_ITEMS.map(({ to, icon, labelKey }) => ({ to, icon, label: t(`navigation:items.${labelKey}`) }))
  const renderLink = ({ to, icon: Icon, label }: typeof items[number], mobile: boolean) => {
    const isCurrent = !!matchPath({ path: to, end: to === '/' }, pathname)
      || (to === '/' && !!matchPath('/limit-up', pathname))
    return (
      <Link
        key={to}
        to={to}
        aria-label={label}
        aria-current={isCurrent ? 'page' : undefined}
        title={mobile ? undefined : label}
        onMouseEnter={() => preloadRoute(to)}
        onFocus={() => preloadRoute(to)}
        className={mobile
          ? 'app-nav-control min-h-11 min-w-0 flex-col gap-0.5 px-0.5 text-[10px] font-medium aria-[current=page]:bg-primary/10 aria-[current=page]:text-foreground'
          : 'app-nav-control relative h-10 min-w-10 gap-1.5 whitespace-nowrap px-2.5 text-[13px] font-medium aria-[current=page]:bg-primary/10 aria-[current=page]:text-foreground aria-[current=page]:after:absolute aria-[current=page]:after:-bottom-[9px] aria-[current=page]:after:inset-x-2.5 aria-[current=page]:after:h-0.5 aria-[current=page]:after:rounded-full aria-[current=page]:after:bg-primary'}
      >
        <Icon aria-hidden="true" className={`shrink-0 ${mobile ? 'size-[18px]' : 'size-4'} ${isCurrent ? 'text-primary' : ''}`} />
        <span className={mobile ? 'max-w-full truncate' : 'hidden xl:inline'}>{label}</span>
      </Link>
    )
  }

  return (
    <>
      <header className="sticky top-0 z-40 shrink-0 border-b border-border bg-card pt-[env(safe-area-inset-top)]">
        <div className="flex h-14 items-center justify-between gap-1 pl-[max(0.625rem,env(safe-area-inset-left))] pr-[max(0.625rem,env(safe-area-inset-right))] md:grid md:grid-cols-[minmax(max-content,1fr)_auto_minmax(max-content,1fr)] md:gap-3 md:pl-[max(1.5rem,env(safe-area-inset-left))] md:pr-[max(1.5rem,env(safe-area-inset-right))]">
          <div className="flex min-w-0 items-center gap-2.5">
            <Link to="/" className="app-nav-focus inline-flex shrink-0 items-center gap-2.5 rounded-lg font-bold tracking-tight text-foreground">
              <span className="grid size-8 place-items-center rounded-lg bg-gradient-to-br from-primary to-primary/75 text-primary-foreground shadow-sm">
                <TrendingUp aria-hidden="true" className="size-[17px]" />
              </span>
              <span>PanWatch</span>
            </Link>
            {version && <span title={`v${version}`} className="hidden max-w-24 truncate rounded-md bg-muted px-1.5 py-0.5 text-[10px] font-medium tabular-nums text-muted-foreground 2xl:inline">v{version}</span>}
          </div>

          <nav aria-label={t('navigation:primaryLabel')} className="hidden items-center gap-0.5 md:flex xl:gap-1">
            {items.slice(0, DESKTOP_COUNT).map(item => renderLink(item, false))}
          </nav>

          <div className="flex shrink-0 items-center gap-0.5 md:justify-self-end">
            <NotificationBell />
            <a
              href="https://github.com/TNT-Likely/PanWatch"
              target="_blank"
              rel="noopener noreferrer"
              aria-label={t('common:links.github')}
              title={t('common:links.github')}
              className="app-nav-control hidden size-10 min-[360px]:flex"
            >
              <Github aria-hidden="true" className="size-[17px]" />
            </a>
            <button type="button" onClick={onOpenLogs} aria-label={t('common:links.logs')} title={t('common:links.logs')} className="app-nav-control size-10">
              <ScrollText aria-hidden="true" className="size-[17px]" />
            </button>
            <div className="ml-1 border-l border-border pl-1 md:ml-1.5 md:pl-1.5">
              <AccountMenu
                navItems={items.slice(MOBILE_COUNT).map((item, index) => ({ ...item, mobileOnly: index < DESKTOP_COUNT - MOBILE_COUNT }))}
                mode={mode}
                onSetMode={onSetMode}
                onOpenSelfCheck={onOpenSelfCheck}
              />
            </div>
          </div>
        </div>
      </header>

      <nav aria-label={t('navigation:primaryLabel')} className="fixed inset-x-0 bottom-0 z-40 border-t border-border bg-card pb-[env(safe-area-inset-bottom)] pl-[max(0.5rem,env(safe-area-inset-left))] pr-[max(0.5rem,env(safe-area-inset-right))] md:hidden">
        <div className="grid h-14 grid-cols-5 items-center gap-0.5">
          {items.slice(0, MOBILE_COUNT).map(item => renderLink(item, true))}
        </div>
      </nav>
    </>
  )
}
