import type { TranslationShape } from '../../resource-types'
import { navigation as zhNavigation } from '../zh-CN/navigation'

export const navigation = {
  items: {
    workspace: 'Workspace',
    gettingStarted: 'Guide center',
    home: 'Home',
    portfolio: 'Portfolio',
    shortTerm: 'Sentiment',
    opportunities: 'Opportunities',
    paperTrading: 'Paper trading',
    assistant: 'Assistant',
    alerts: 'Alerts',
    agents: 'Agents',
    evaluations: 'Evaluation',
    history: 'History',
    dataSources: 'Data sources',
    mcp: 'MCP',
    settings: 'Settings',
  },
} as const satisfies TranslationShape<typeof zhNavigation>
