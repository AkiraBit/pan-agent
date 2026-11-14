import { useLocation, useSearchParams } from 'react-router-dom'
import { BookOpen, Plug } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@panwatch/base-ui/components/ui/tabs'
import MCPPage from './MCP'
import SkillsPage from './Skills'

export default function IntegrationsPage() {
  const { t } = useTranslation('configuration')
  const [search, setSearch] = useSearchParams()
  const callback = useLocation().pathname.endsWith('/callback')
  const tab = !callback && search.get('tab') === 'skills' ? 'skills' : 'mcp'
  return <div className="max-w-7xl mx-auto space-y-6">
    <div><h1 className="text-xl font-semibold flex items-center gap-2"><Plug className="w-5 h-5 text-primary" />{t('mcp.title')}</h1>
      <p className="text-sm text-muted-foreground mt-2">{t('mcp.subtitle')}</p></div>
    <Tabs value={tab} onValueChange={value => setSearch(value === 'skills' ? { tab: 'skills' } : {})}>
      <TabsList aria-label={t('skills.tabsLabel')} className="mb-6">
        <TabsTrigger value="mcp" className="flex items-center gap-2 rounded-xl px-4 py-2 text-sm"><Plug className="w-4 h-4" />{t('skills.mcpTab')}</TabsTrigger>
        <TabsTrigger value="skills" disabled={callback} className="flex items-center gap-2 rounded-xl px-4 py-2 text-sm"><BookOpen className="w-4 h-4" />{t('skills.tab')}</TabsTrigger>
      </TabsList>
      <TabsContent value="mcp"><MCPPage /></TabsContent>
      <TabsContent value="skills"><SkillsPage /></TabsContent>
    </Tabs>
  </div>
}
