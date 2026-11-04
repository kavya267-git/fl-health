import {
  Activity,
  Building2,
  CircleHelp,
  Hospital,
  Layers,
  LayoutDashboard,
  Lightbulb,
  Map as MapIcon,
  ScrollText,
  Settings,
  TrendingUp,
} from 'lucide-react'
import { canSeeAudit, isHealthOfficer, isHospitalOperator } from '../../utils/constants'

export const NAV_ITEMS = [
  { to: '/', label: 'Dashboard', icon: LayoutDashboard, end: true },
  { to: '/hospitals', label: 'Hospitals', icon: Building2 },
  { to: '/federated', label: 'Federated Learning', icon: Activity },
  { to: '/models', label: 'Models', icon: Layers },
  { to: '/surveillance', label: 'Disease Surveillance', icon: MapIcon },
  { to: '/forecasting', label: 'Forecasting', icon: TrendingUp },
  { to: '/explainability', label: 'Explainability', icon: Lightbulb },
  { to: '/audit', label: 'Audit Logs', icon: ScrollText },
  { to: '/how-it-works', label: 'How it works', icon: CircleHelp },
  { to: '/settings', label: 'Settings', icon: Settings },
]

const MY_HOSPITAL = { to: '/my-hospital', label: 'My hospital', icon: Hospital }

/** What a health officer may open (their jurisdiction's surveillance and forecasts; see docs/permissions.md). */
const HEALTH_OFFICER_PAGES = ['/surveillance', '/forecasting', '/how-it-works', '/settings']

/** The sidebar for this user. The server enforces the same rules; this only hides what it would refuse. */
export function navItemsFor(user) {
  if (isHealthOfficer(user)) return NAV_ITEMS.filter((item) => HEALTH_OFFICER_PAGES.includes(item.to))
  const items = NAV_ITEMS.filter((item) => item.to !== '/audit' || canSeeAudit(user))
  return isHospitalOperator(user) ? [MY_HOSPITAL, ...items] : items
}
