import { useEffect, useState } from 'react'
import { NavLink, useLocation } from 'react-router-dom'
import { Moon, Sun, Monitor, Check, LogOut, Stethoscope, Languages, type LucideIcon } from 'lucide-react'
import { isAuthenticated, logout } from '@panwatch/api'
import { Popover, PopoverContent, PopoverTrigger } from '@panwatch/base-ui/components/ui/popover'
import type { ThemeMode } from '@/hooks/use-theme'
import { useAvatar } from '@/hooks/use-avatar'
import { useTranslation } from 'react-i18next'
import { changeLocale, normalizeLocale, type SupportedLocale } from '@/i18n'
import { useInterfaceLanguage } from '@/i18n/interface-language'
import { UserAvatar } from '@/components/UserAvatar'

interface AccountNavItem {
  to: string
  icon: LucideIcon
  label: string
  mobileOnly?: boolean
}

const THEME_OPTIONS: { value: ThemeMode; icon: LucideIcon; labelKey: 'light' | 'dark' | 'system' }[] = [
  { value: 'light', icon: Sun, labelKey: 'light' },
  { value: 'dark', icon: Moon, labelKey: 'dark' },
  { value: 'system', icon: Monitor, labelKey: 'system' },
]

const LANGUAGE_OPTIONS: { value: SupportedLocale; labelKey: 'simplifiedChinese' | 'english' }[] = [
  { value: 'zh-CN', labelKey: 'simplifiedChinese' },
  { value: 'en-US', labelKey: 'english' },
]

interface AccountMenuProps {
  navItems: AccountNavItem[]
  mode: ThemeMode
  onSetMode: (mode: ThemeMode) => void
  onOpenSelfCheck: () => void
}

const rowClass = 'flex min-h-8 w-full items-center gap-2.5 rounded-md px-2.5 py-1.5 text-left text-[12px] text-secondary-foreground hover:bg-accent/70 hover:text-foreground focus-visible:bg-accent/70 focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-ring'
const selectedClass = 'aria-pressed:bg-accent/60 aria-pressed:font-medium aria-pressed:text-foreground'
const iconClass = 'size-3.5 shrink-0'

export default function AccountMenu({ navItems, mode, onSetMode, onOpenSelfCheck }: AccountMenuProps) {
  const { t, i18n: i18nInstance } = useTranslation('settings')
  const currentLocale = normalizeLocale(i18nInstance.resolvedLanguage || i18nInstance.language)
  useInterfaceLanguage()
  const [open, setOpen] = useState(false)
  const { pathname } = useLocation()
  const avatar = useAvatar()

  useEffect(() => setOpen(false), [pathname])

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button type="button" className="app-nav-control size-10" title={t('account.menuTitle')} aria-label={t('account.menuTitle')}>
          <span className="size-7 overflow-hidden rounded-full bg-muted ring-1 ring-border">
            <UserAvatar src={avatar} alt="" />
          </span>
        </button>
      </PopoverTrigger>
      <PopoverContent
        aria-label={t('account.menuTitle')}
        align="end"
        sideOffset={10}
        collisionPadding={8}
        className="scrollbar max-h-[var(--radix-popover-content-available-height)] w-56 max-w-[calc(100vw-1rem)] overflow-y-auto overscroll-contain p-1.5 shadow-lg !animate-none"
      >
        {navItems.length > 0 && <div className="mb-1 border-b border-border pb-1">
          {navItems.map(({ to, icon: Icon, label, mobileOnly }) => (
            <NavLink
              key={to}
              to={to}
              onClick={() => setOpen(false)}
              className={`${rowClass} aria-[current=page]:bg-primary/10 aria-[current=page]:text-primary ${mobileOnly ? 'md:hidden' : ''}`}
            >
              <Icon aria-hidden="true" className={iconClass} />
              {label}
            </NavLink>
          ))}
        </div>}

        <div role="group" aria-label={t('account.themeTitle')} className="border-b border-border pb-1">
          <div aria-hidden="true" className="px-2.5 py-1 text-[11px] text-muted-foreground">{t('account.themeTitle')}</div>
          {THEME_OPTIONS.map(({ value, icon: Icon, labelKey }) => (
            <button key={value} type="button" aria-pressed={mode === value} onClick={() => onSetMode(value)} className={`${rowClass} ${selectedClass}`}>
              <Icon aria-hidden="true" className={iconClass} />
              {t(`account.theme.${labelKey}`)}
              {mode === value && <Check aria-hidden="true" className={`${iconClass} ml-auto text-primary`} />}
            </button>
          ))}
        </div>

        <div role="group" aria-label={t('language.title')} className="my-1 border-b border-border pb-1">
          <div aria-hidden="true" className="px-2.5 py-1 text-[11px] text-muted-foreground">{t('language.title')}</div>
          {LANGUAGE_OPTIONS.map(({ value, labelKey }) => (
            <button key={value} type="button" aria-pressed={currentLocale === value} onClick={() => void changeLocale(value)} className={`${rowClass} ${selectedClass}`}>
              <Languages aria-hidden="true" className={iconClass} />
              {t(`language.${labelKey}`)}
              {currentLocale === value && <Check aria-hidden="true" className={`${iconClass} ml-auto text-primary`} />}
            </button>
          ))}
        </div>

        <button type="button" onClick={() => { setOpen(false); onOpenSelfCheck() }} className={rowClass}>
          <Stethoscope aria-hidden="true" className={iconClass} />
          {t('account.selfCheck')}
        </button>
        {isAuthenticated() && (
          <button type="button" onClick={logout} className={`${rowClass} hover:bg-destructive/10 hover:text-destructive`}>
            <LogOut aria-hidden="true" className={iconClass} />
            {t('account.signOut')}
          </button>
        )}
      </PopoverContent>
    </Popover>
  )
}
