import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, expect, it } from 'vitest'
import i18n from '@/i18n'
import SpeculationTabs, { type Speculation } from './SpeculationTabs'
const data: Speculation = {
  relay: { complete:true,height:3,previous_height:4,ungraded_up:0,ungraded_previous:0,
    ladder:[{level:3,count:1,stocks:[{code:'000001',name:'梯队样本',change:10,streak:3,first_time:'09:30:00',last_time:'10:10:00',breaks:2}]}],
    promotion:[{level:2,total:4,promoted:1,rate:.25}],
    anchors:[{code:'000002',name:'昨日高标样本',change:-5,streak:null,previous_streak:4,state:'not_sealed'}],negative_feedback:[] },
  themes:{scanned:12,available:531,candidates:[{code:'T',name:'题材样本',complete:true,limit_up:6,first_boards:4,relay_boards:2,height:3,previous_mean:2,core:[],overlaps:[]}]},
  trends:[{code:'000003',name:'容量样本',amount:2e9,change:1,themes:['题材样本'],structure:{state:'aligned',as_of:'2026-11-10',distance_ma20:2,ma20_change:1,drawdown20:-3,return5:5}}],
}
beforeEach(async()=>{await i18n.loadNamespaces('shortTerm')})
afterEach(cleanup)
it('switches among distinct speculative evidence, relay cohorts and completed-bar trends',async()=>{
  const user=userEvent.setup();render(<SpeculationTabs data={data}/> )
  expect(screen.getByRole('heading',{name:'资金在炒哪些方向'})).toBeTruthy()
  expect(screen.queryByRole('heading',{name:'各高度晋级情况'})).toBeNull()
  await user.click(screen.getByRole('tab',{name:'连板接力'}))
  expect(screen.getByText('1 / 4')).toBeTruthy()
  expect(screen.getByText(/当前未封板/)).toBeTruthy()
  expect(screen.queryByText('已断板')).toBeNull()
  await user.keyboard('{ArrowRight}')
  await screen.findByRole('heading',{name:'题材内的成交额核心与趋势结构'})
  expect(screen.getByText('均线多头排列')).toBeTruthy()
  expect(screen.getByText('已收盘日线截至 2026-11-10')).toBeTruthy()
})
it('does not invent relay data for older immutable records',()=>{
  render(<SpeculationTabs/>)
  expect(screen.getByText(/旧记录保持原样/)).toBeTruthy()
  expect(screen.queryByText('0 → 0')).toBeNull()
})
it('discloses partial pools and missing rate instead of a zero success rate',async()=>{
  const user=userEvent.setup();render(<SpeculationTabs data={{...data,relay:{...data.relay,complete:false,promotion:[{level:2,total:4,promoted:null,rate:null}]}}}/> )
  expect(screen.getByRole('status')).toBeTruthy()
  await user.click(screen.getByRole('tab',{name:'连板接力'}))
  expect(screen.getByText('— / 4')).toBeTruthy()
  expect(screen.queryByText('0%')).toBeNull()
})
it('provides English tab labels and domain explanations',async()=>{
  await i18n.changeLanguage('en-US');render(<SpeculationTabs data={data}/>)
  expect(screen.getByRole('tab',{name:'Limit-up relay'})).toBeTruthy()
  expect(screen.getByText(/One snapshot cannot establish/)).toBeTruthy()
})
