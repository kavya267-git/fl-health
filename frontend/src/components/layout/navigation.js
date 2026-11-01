import { Activity, Building2, Layers, LayoutDashboard, Lightbulb, Map as MapIcon, ScrollText, Settings, TrendingUp } from 'lucide-react'

export const NAV_ITEMS = [
  { to: '/', label: 'Dashboard', icon: LayoutDashboard, end: true },
  { to: '/hospitals', label: 'Hospitals', icon: Building2 },
  { to: '/federated', label: 'Federated Learning', icon: Activity },
  { to: '/models', label: 'Models', icon: Layers },
  { to: '/surveillance', label: 'Disease Surveillance', icon: MapIcon },
  { to: '/forecasting', label: 'Forecasting', icon: TrendingUp },
  { to: '/explainability', label: 'Explainability', icon: Lightbulb },
  { to: '/audit', label: 'Audit Logs', icon: ScrollText },
  { to: '/settings', label: 'Settings', icon: Settings },
]
