import { LogOut, Menu, X } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router-dom'
import { useAuth } from '../../context/AuthContext'
import { useSystem } from '../../context/SystemContext'
import { ROLE_LABELS } from '../../utils/constants'
import { classNames } from '../../utils/format'
import { SimulatedTag } from '../ui/Badge'
import { Logo } from './Logo'
import { api } from '../../services/endpoints'
import { navItemsFor } from './navigation'

/** Pending hospital registrations, for the administrator's nav badge. Refreshed every 30 s and after a review. */
function usePendingRegistrations(user) {
  const [count, setCount] = useState(0)
  const load = useCallback(() => {
    if (user?.role !== 'admin') return
    // A missing count must never break the page: the badge is a hint, the page itself has the list.
    Promise.resolve()
      .then(() => api.pendingRegistrations())
      .then((result) => setCount(Number(result?.pending) || 0))
      .catch(() => {})
  }, [user?.role])
  useEffect(() => {
    load()
    if (user?.role !== 'admin') return undefined
    const timer = setInterval(load, 30000)
    window.addEventListener('medifed:registrations-changed', load)
    return () => {
      clearInterval(timer)
      window.removeEventListener('medifed:registrations-changed', load)
    }
  }, [load, user?.role])
  return count
}

function Navigation({ onNavigate }) {
  const { user } = useAuth()
  const pending = usePendingRegistrations(user)
  return (
    <nav aria-label="Main" className="flex flex-col gap-0.5 px-3">
      {navItemsFor(user).map(({ to, label, icon: Icon, end, badge }) => (
        <NavLink
          key={to}
          to={to}
          end={end}
          onClick={onNavigate}
          className={({ isActive }) =>
            classNames(
              'flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors',
              isActive ? 'bg-brand-700 text-white' : 'text-brand-100 hover:bg-brand-800 hover:text-white',
            )
          }
        >
          <Icon className="h-4 w-4 shrink-0" aria-hidden="true" />
          {label}
          {badge === 'pendingRegistrations' && pending > 0 ? (
            <span
              className="ml-auto rounded-full bg-warn px-2 py-0.5 text-xs font-semibold text-white"
              aria-label={`${pending} pending`}
            >
              {pending}
            </span>
          ) : null}
        </NavLink>
      ))}
    </nav>
  )
}

function ModeNotice() {
  const { config } = useSystem()
  if (!config?.demo_mode) return null
  return (
    <div className="mx-3 rounded-md border border-brand-700 bg-brand-950/40 px-3 py-3">
      <p className="text-xs font-semibold text-white">Demo mode</p>
      <p className="mt-1 text-xs leading-relaxed text-brand-200">
        Hospitals and data are simulated. Training and metrics are computed for real on that data.
      </p>
    </div>
  )
}

export function AppShell() {
  const { user, signOut } = useAuth()
  const { config } = useSystem()
  const location = useLocation()
  const [menuOpen, setMenuOpen] = useState(false)

  useEffect(() => setMenuOpen(false), [location.pathname])

  return (
    <div className="min-h-screen lg:flex">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-3 focus:top-3 focus:z-50 focus:rounded focus:bg-surface focus:px-3 focus:py-2 focus:text-sm"
      >
        Skip to content
      </a>

      {/* Sidebar (desktop) */}
      <aside className="sticky top-0 hidden h-screen w-64 shrink-0 flex-col bg-brand-900 lg:flex">
        <div className="px-5 py-5">
          <Logo light />
        </div>
        <div className="flex-1 overflow-y-auto pb-4">
          <Navigation />
        </div>
        <div className="pb-4">
          <ModeNotice />
        </div>
      </aside>

      {/* Drawer (mobile) */}
      {menuOpen ? (
        <div className="fixed inset-0 z-[1200] lg:hidden">
          <button type="button" aria-label="Close menu" className="absolute inset-0 bg-brand-950/50" onClick={() => setMenuOpen(false)} />
          <div className="relative flex h-full w-72 max-w-[85%] flex-col bg-brand-900 pb-4">
            <div className="flex items-center justify-between px-5 py-5">
              <Logo light />
              <button type="button" aria-label="Close menu" onClick={() => setMenuOpen(false)} className="rounded p-1 text-brand-100">
                <X className="h-5 w-5" aria-hidden="true" />
              </button>
            </div>
            <div className="flex-1 overflow-y-auto">
              <Navigation onNavigate={() => setMenuOpen(false)} />
            </div>
            <ModeNotice />
          </div>
        </div>
      ) : null}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-[1000] flex h-14 items-center justify-between gap-3 border-b border-line bg-surface/95 px-4 backdrop-blur lg:px-8">
          <div className="flex min-w-0 items-center gap-3">
            <button
              type="button"
              aria-label="Open menu"
              onClick={() => setMenuOpen(true)}
              className="rounded p-1.5 text-muted hover:bg-canvas lg:hidden"
            >
              <Menu className="h-5 w-5" aria-hidden="true" />
            </button>
            {config?.demo_mode ? <SimulatedTag label={config.simulated_label} /> : null}
          </div>
          <div className="flex items-center gap-3">
            <div className="hidden text-right leading-tight sm:block">
              <p className="max-w-56 truncate text-sm font-medium text-ink">{user?.display_name || user?.email}</p>
              <p className="text-xs text-muted">{ROLE_LABELS[user?.role] || user?.role}</p>
            </div>
            <button
              type="button"
              onClick={signOut}
              className="inline-flex h-9 items-center gap-2 rounded-md border border-line-strong px-3 text-sm font-medium text-ink hover:bg-canvas"
            >
              <LogOut className="h-4 w-4" aria-hidden="true" />
              Sign out
            </button>
          </div>
        </header>
        <main id="main" className="mx-auto w-full max-w-[1320px] flex-1 px-4 py-7 lg:px-8">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
