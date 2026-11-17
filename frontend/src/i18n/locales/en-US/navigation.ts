import type { TranslationShape } from '../../resource-types'
import { navigation as zhNavigation } from '../zh-CN/navigation'

export const navigation = {
  primaryLabel: 'Main navigation',
  items: {
    workspace: 'Workspace',
    gettingStarted: 'Guide center',
    home: 'Home',
    etf: 'Broad-market ETFs',
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
    researchData: 'Market research',
    mcp: 'MCP & Skills',
    settings: 'Settings',
  },
} as const satisfies TranslationShape<typeof zhNavigation>
