import type { FuyaoParameter } from './fuyao-rest'

export interface TushareOperation {
  id: string
  group: '股票数据' | 'ETF专题' | '指数专题'
  subgroup?: string
  summary: string
  order: number
  docs_url: string
  parameters: FuyaoParameter[]
  require_any?: string[]
}
