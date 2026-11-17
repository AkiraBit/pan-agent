export const ETF_SESSION_MINUTES = [[570, 691], [781, 901]].flatMap(([start, end]) =>
  Array.from({ length: end - start }, (_, i) => {
    const minute = start + i
    return `${String(Math.floor(minute / 60)).padStart(2, '0')}:${String(minute % 60).padStart(2, '0')}`
  }),
)

export const CNY_PER_YI = 100_000_000
export const VOLUME_THRESHOLD = .2

export function etfIntradayMove(closes: Record<string, number>) {
  const values = ETF_SESSION_MINUTES.map(minute => {
    const close = closes[minute]
    return Number.isFinite(close) && close > 0 ? close : null
  })
  const first = values.findIndex(close => close !== null)
  const base = values[first]
  if (base == null) return null
  return {
    baseMinute: ETF_SESSION_MINUTES[first],
    values: values.map(close => close == null ? null : (close - base) / base),
  }
}

export function minuteTurnoverFromCumulative(cumulative?: Record<string, number>) {
  return ETF_SESSION_MINUTES.map((minute, index) => {
    const total = cumulative?.[minute]
    const previous = index === 0 ? 0 : cumulative?.[ETF_SESSION_MINUTES[index - 1]]
    return total != null && previous != null && total >= previous ? total - previous : null
  })
}
