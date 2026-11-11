import {
  Activity,
  BellRing,
  Building2,
  CircleHelp,
  ClipboardList,
  BedDouble,
  Hospital,
  Inbox,
  Layers,
  LayoutDashboard,
  Lightbulb,
  Map as MapIcon,
  ScrollText,
  Settings,
  TrendingUp,
} from 'lucide-react'
import { canSeeAudit, canSeeOfficerViews, isHealthOfficer, isHospitalOperator } from '../../utils/constants'

export const NAV_ITEMS = [
  { to: '/', label: 'Dashboard', icon: LayoutDashboard, end: true },
  { to: '/hospitals', label: 'Hospitals', icon: Building2 },
  { to: '/federated', label: 'Federated Learning', icon: Activity },
  { to: '/models', label: 'Models', icon: Layers },
  { to: '/situation', label: 'Situation report', icon: ClipboardList },
  { to: '/surveillance', label: 'Disease Surveillance', icon: MapIcon },
  { to: '/alerts', label: 'Alerts', icon: BellRing },
  { to: '/forecasting', label: 'Forecasting', icon: TrendingUp },
  { to: '/explainability', label: 'Explainability', icon: Lightbulb },
  { to: '/audit', label: 'Audit Logs', icon: ScrollText },
  { to: '/how-it-works', label: 'How it works', icon: CircleHelp },
  { to: '/settings', label: 'Settings', icon: Settings },
]

const MY_HOSPITAL = { to: '/my-hospital', label: 'My hospital', icon: Hospital }
const PLANNING = { to: '/planning', label: 'Resource planning', icon: BedDouble }
/** Administrators: the public hospital registrations to review. The badge shows how many are pending. */
export const HOSPITAL_REQUESTS = { to: '/hospital-requests', label: 'Hospital requests', icon: Inbox, badge: 'pendingRegistrations' }

/** What a health officer may open (their jurisdiction only; see docs/permissions.md). */
const HEALTH_OFFICER_PAGES = ['/situation', '/surveillance', '/alerts', '/forecasting', '/how-it-works', '/settings']
const OFFICER_VIEWS = ['/situation', '/alerts']

/** The sidebar for this user. The server enforces the same rules; this only hides what it would refuse. */
export function navItemsFor(user) {
  if (isHealthOfficer(user)) {
    return NAV_ITEMS.filter((item) => HEALTH_OFFICER_PAGES.includes(item.to)).map((item) =>
      item.to === '/surveillance' ? { ...item, label: 'Jurisdiction map' } : item,
    )
  }
  const items = NAV_ITEMS.filter(
    (item) => (item.to !== '/audit' || canSeeAudit(user)) && (!OFFICER_VIEWS.includes(item.to) || canSeeOfficerViews(user)),
  )
  if (user?.role === 'hospital_manager') return [PLANNING, MY_HOSPITAL, ...items]
  if (user?.role === 'admin') return [...items.slice(0, -1), PLANNING, HOSPITAL_REQUESTS, items[items.length - 1]]
  if (isHospitalOperator(user)) return user?.self_registered ? [MY_HOSPITAL, PLANNING, ...items] : [MY_HOSPITAL, ...items]
  return items
}
