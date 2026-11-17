import { Suspense, useState, useEffect, useRef } from 'react'
import { Routes, Route, useLocation, Navigate } from 'react-router-dom'
import { useTheme } from '@/hooks/use-theme'
import { appApi } from '@panwatch/api/app'
import { fetchAPI, isAuthenticated } from '@panwatch/api/client'
import LogsModal from '@panwatch/biz-ui/components/logs-modal'
import AmbientBackground from '@panwatch/biz-ui/components/AmbientBackground'
import AppNavigation from '@/components/AppNavigation'
import { GuidedTourProvider } from '@/components/onboarding/GuidedTour'
import AssistantOpenBridge from '@/components/AssistantOpenBridge'
import SelfCheckModal from '@/components/SelfCheckModal'
import { RouteErrorBoundary, RouteLoadingFallback } from '@/components/RouteBoundary'
import { routePages } from '@/router/page-loaders'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@panwatch/base-ui/components/ui/dialog'
import { Button } from '@panwatch/base-ui/components/ui/button'
import { useTranslation } from 'react-i18next'
import { NotificationProvider } from '@/components/notifications/NotificationProvider'

const {
  LoginPage,
  DashboardPage,
  BroadEtfPage,
  WorkspacePage,
  GettingStartedPage,
  OpportunitiesPage,
  ShortTermPage,
  StocksPage,
  AgentsPage,
  SettingsPage,
  DataSourcesPage,
  ResearchDataPage,
  FuyaoRestPage,
  FtshareRestPage,
  MCPPage,
  HistoryPage,
  AnalysisDetailPage,
  PriceAlertsPage,
  PaperTradingPage,
  EvaluationsPage,
  AssistantPage,
} = routePages

// 认证守卫组件
function RequireAuth({ children }: { children: React.ReactNode }) {
  const [authState, setAuthState] = useState<'checking' | 'authenticated' | 'unauthenticated'>('checking')
  const location = useLocation()

  useEffect(() => {
    // 检查本地 token
    if (isAuthenticated()) {
      setAuthState('authenticated')
      return
    }

    // 没有 token，需要去登录页（设置密码或登录）
    setAuthState('unauthenticated')
  }, [])

  if (authState === 'checking') {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background">
        <span className="w-6 h-6 border-2 border-primary/30 border-t-primary rounded-full animate-spin" />
      </div>
    )
  }

  if (authState === 'unauthenticated') {
    return <Navigate to="/login" state={{ from: location }} replace />
  }

  return <>{children}</>
}

function App() {
  const { t } = useTranslation('common')
  const { mode, setMode } = useTheme()
  const location = useLocation()
  const isAssistantRoute = location.pathname === '/assistant' || location.pathname.startsWith('/assistant/')
  const isDataSourcesRoute = /^\/datasources\/?$/.test(location.pathname)
  const [version, setVersion] = useState('')
  const [logsOpen, setLogsOpen] = useState(false)
  const [selfCheckOpen, setSelfCheckOpen] = useState(false)
  const [upgradeOpen, setUpgradeOpen] = useState(false)
  const [upgradeInfo, setUpgradeInfo] = useState<{ latest: string; url: string } | null>(null)
  const checkedUpdateRef = useRef(false)

  useEffect(() => {
    appApi.version()
      .then(data => setVersion(data?.version || ''))
      .catch(() => {})
  }, [])

  useEffect(() => {
    if (checkedUpdateRef.current) return
    if (!isAuthenticated()) return
    const current = String(version || '').trim()
    if (!current || current === 'dev') return
    checkedUpdateRef.current = true

    fetchAPI<any>('/settings/update-check')
      .then((res) => {
        const latest = String(res?.latest_version || '').trim()
        const shouldOpen = !!res?.update_available && !!latest
        if (!shouldOpen) return
        const dismissed = localStorage.getItem('panwatch_upgrade_dismissed_version') || ''
        if (dismissed === latest) return
        setUpgradeInfo({ latest, url: String(res?.release_url || 'https://github.com/sunxiao0721/PanWatch/releases') })
        setUpgradeOpen(true)
      })
      .catch(() => {})
  }, [version])

  // 登录页面不显示导航
  if (location.pathname === '/login') {
    return (
      <RouteErrorBoundary>
        <Suspense fallback={<RouteLoadingFallback />}>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
          </Routes>
        </Suspense>
      </RouteErrorBoundary>
    )
  }

  return (
    <RequireAuth>
    <GuidedTourProvider>
    <NotificationProvider>
    <div
      className={isAssistantRoute
        ? 'relative flex h-dvh flex-col overflow-hidden bg-background'
        : `relative min-h-screen overflow-x-clip bg-background pb-[calc(3.5rem+env(safe-area-inset-bottom))] md:pb-0 ${isDataSourcesRoute ? 'md:flex md:h-dvh md:min-h-0 md:flex-col' : ''}`}
    >
      <AmbientBackground />
      <AppNavigation
        version={version}
        mode={mode}
        onSetMode={setMode}
        onOpenLogs={() => setLogsOpen(true)}
        onOpenSelfCheck={() => setSelfCheckOpen(true)}
      />

      {/* Content */}
      <main
        className={`${isAssistantRoute
          ? 'flex min-h-0 flex-1 flex-col overflow-hidden pb-[calc(3.5rem+env(safe-area-inset-bottom))] md:pb-6'
          : `pb-4 md:pb-6 ${isDataSourcesRoute ? 'md:flex md:min-h-0 md:flex-1 md:flex-col' : ''}`} px-4 pt-4 md:px-6 md:pt-6 w-full`}
      >
        <AssistantOpenBridge />
        <RouteErrorBoundary>
          <Suspense fallback={<RouteLoadingFallback />}>
            <Routes>
              <Route path="/" element={<DashboardPage />} />
              <Route path="/limit-up" element={<DashboardPage />} />
              <Route path="/etf" element={<BroadEtfPage />} />
              <Route path="/workspace" element={<WorkspacePage />} />
              <Route path="/getting-started" element={<GettingStartedPage />} />
              <Route path="/short-term/*" element={<ShortTermPage />} />
              <Route path="/opportunities" element={<OpportunitiesPage />} />
              <Route path="/portfolio" element={<StocksPage />} />
              <Route path="/agents" element={<AgentsPage />} />
              <Route path="/evaluations" element={<EvaluationsPage />} />
              <Route path="/history" element={<HistoryPage />} />
              <Route path="/paper-trading" element={<PaperTradingPage />} />
              <Route path="/alerts" element={<PriceAlertsPage />} />
              <Route path="/assistant" element={<AssistantPage />} />
              <Route path="/assistant/:conversationId" element={<AssistantPage />} />
              <Route path="/datasources" element={<DataSourcesPage />} />
              <Route path="/market-data/:kind?" element={<ResearchDataPage />} />
              <Route path="/datasources/fuyao" element={<FuyaoRestPage />} />
              <Route path="/datasources/ftshare" element={<FtshareRestPage />} />
              <Route path="/integrations/mcp" element={<MCPPage />} />
              <Route path="/integrations/mcp/callback" element={<MCPPage />} />
              <Route path="/settings" element={<SettingsPage />} />
              <Route path="/analysis/:symbol/:date" element={<AnalysisDetailPage />} />
            </Routes>
          </Suspense>
        </RouteErrorBoundary>
      </main>
      <LogsModal open={logsOpen} onOpenChange={setLogsOpen} />
      <SelfCheckModal open={selfCheckOpen} onClose={() => setSelfCheckOpen(false)} />
      <Dialog open={upgradeOpen} onOpenChange={setUpgradeOpen}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>{t('update.title')}</DialogTitle>
            <DialogDescription>
              {t('update.description', { current: version, latest: upgradeInfo?.latest ?? '' })}
            </DialogDescription>
          </DialogHeader>
          <div className="text-[12px] text-muted-foreground">
            {t('update.recommendation')}
          </div>
          <div className="flex items-center justify-end gap-2">
            <Button
              variant="secondary"
              onClick={() => {
                if (upgradeInfo?.latest) localStorage.setItem('panwatch_upgrade_dismissed_version', upgradeInfo.latest)
                setUpgradeOpen(false)
              }}
            >
              {t('actions.remindLater')}
            </Button>
            <Button
              onClick={() => {
                const url = upgradeInfo?.url || 'https://github.com/sunxiao0721/PanWatch/releases'
                window.open(url, '_blank', 'noopener,noreferrer')
              }}
            >
              {t('actions.upgrade')}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
    </NotificationProvider>
    </GuidedTourProvider>
    </RequireAuth>
  )
}

export default App
