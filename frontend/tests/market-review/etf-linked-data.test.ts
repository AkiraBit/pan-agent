import { describe, expect, it } from 'vitest'
import { baselineAmount, rangeAmounts } from '@/components/etf/linked-data'

describe('linked ETF interval statistics', () => {
  it('includes both endpoints and refuses to turn a missing minute into zero', () => {
    expect(rangeAmounts({ '09:30': 3, '09:31': 7 }, ['09:30', '09:31'])).toBe(10)
    expect(rangeAmounts({ '09:30': 3 }, ['09:30', '09:31'])).toBeNull()
    expect(rangeAmounts({ '09:30': 0 }, ['09:30', '09:30'])).toBe(0)
  })
  it('subtracts the cumulative value preceding the selected interval', () => {
    const cumulative = { '09:30': 3, '09:31': 10, '09:32': 15 }
    expect(baselineAmount(cumulative, ['09:31', '09:32'])).toBe(12)
    expect(baselineAmount(cumulative, ['09:30', '09:31'])).toBe(10)
    expect(baselineAmount(cumulative, ['09:32', '09:33'])).toBeNull()
  })
})
