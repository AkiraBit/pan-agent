import type { EtfPriceInstrument } from '@panwatch/api/etf'

export const priceInstrumentKey = (instrument: EtfPriceInstrument) =>
  instrument.kind === 'index' ? `index:${instrument.symbol}` : instrument.symbol

const palette = [
  ['#087d6b', '#53d3b6'],
  ['#7746c3', '#bd9aff'],
  ['#ae3b81', '#f19dd3'],
  ['#387e16', '#a8d575'],
  ['#237b9a', '#6ccbe9'],
  ['#ad5832', '#ffac80'],
  ['#675b99', '#ccc1f1'],
  ['#756900', '#e4d170'],
  ['#3469bf', '#86b6ff'],
]

export function etfPriceColor(index: number, dark: boolean) {
  return palette[index]?.[dark ? 1 : 0] ?? `hsl(${index * 137.508 % 360}, 64%, ${dark ? 69 : 35}%)`
}

export interface EtfChartPrice {
  instrument: EtfPriceInstrument
  closes: Record<string, number>
  colorIndex: number
  previousClose?: number | null
}
