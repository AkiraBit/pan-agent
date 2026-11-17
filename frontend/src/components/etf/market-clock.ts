import { useEffect, useState } from 'react'
import type { EtfIntraday, EtfMarketClock } from '@panwatch/api/etf'
import { ETF_SESSION_MINUTES } from './session'

export const SHANGHAI_TIMEZONE = 'Asia/Shanghai'
export const DEFAULT_REFRESH_DELAY = 12_000
export const MAX_REFRESH_DELAY = 42_000
const MINUTE = 60_000

export type EtfRefreshSlot = { day: string; minute: string; at: number }

export function shanghaiDate(now: number, timeZone = SHANGHAI_TIMEZONE) {
  const parts = new Intl.DateTimeFormat('en', { timeZone, year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(now)
  return ['year', 'month', 'day'].map(part => parts.find(value => value.type === part)?.value).join('-')
}

function slotStart(day: string, minute: string) {
  return Date.parse(`${day}T${minute}:00+08:00`)
}

export function marketPhase(now: number, day: string, market?: EtfMarketClock) {
  if (!market || (market.next_trading_day && day > market.next_trading_day)) return null
  if (!(market.date === day ? market.trading_day : market.next_trading_day === day)) return 'marketHoliday'
  if (now < slotStart(day, '09:30')) return 'marketPreopen'
  if (now >= slotStart(day, '15:00')) return 'marketClosed'
  return 'marketOpen'
}

export function hasEtfMinute(data: EtfIntraday | undefined, day: string, minute: string) {
  return data?.date === day && data.points.some(point => point.minute === minute && point.turnover_cny != null
    && point.etf_count === data.symbols.length && point.index_close != null)
}

export function nextEtfRefresh(now: number, market: EtfMarketClock, date: string, delay: number,
  last: EtfRefreshSlot | undefined, data: EtfIntraday | undefined): EtfRefreshSlot | undefined {
  const today = shanghaiDate(now, market.timezone)
  const days = [market.trading_day ? market.date : null, market.next_trading_day]
  for (const day of days) {
    if (!day || day < today || (date && (day !== date || day !== today))) continue
    for (const minute of ETF_SESSION_MINUTES) {
      const start = slotStart(day, minute)
      if (now >= start + MINUTE || (last?.day === day && minute <= last.minute) || hasEtfMinute(data, day, minute)) continue
      const lag = day === today ? delay : DEFAULT_REFRESH_DELAY
      const afterSession = minute === '11:30' || minute === '15:00'
      return { day, minute, at: start + (afterSession ? Math.max(lag, 32_000) : lag) }
    }
  }
}

export function useMarketTime(offset: number) {
  const [now, setNow] = useState(Date.now)
  useEffect(() => {
    let timer: number
    const tick = () => {
      window.clearTimeout(timer)
      const localTime = Date.now()
      setNow(localTime)
      timer = window.setTimeout(tick, MINUTE - (localTime + offset) % MINUTE)
    }
    tick()
    window.addEventListener('focus', tick)
    document.addEventListener('visibilitychange', tick)
    return () => {
      window.clearTimeout(timer)
      window.removeEventListener('focus', tick)
      document.removeEventListener('visibilitychange', tick)
    }
  }, [offset])
  return now + offset
}
