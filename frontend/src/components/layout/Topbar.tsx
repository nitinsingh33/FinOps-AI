import { useLocation } from 'react-router-dom'
import { Bell, HelpCircle } from 'lucide-react'

const PAGE_TITLES: Record<string, string> = {
  '/dashboard': 'Dashboard',
  '/uploads': 'Data Uploads',
  '/reconciliation': 'Reconciliation',
  '/exceptions': 'Exceptions',
  '/analytics': 'Analytics',
  '/pricing': 'Pricing & Savings',
  '/reports': 'Reports',
}

export default function Topbar() {
  const { pathname } = useLocation()
  const title = PAGE_TITLES[pathname] ?? 'FinOps AI'

  return (
    <header className="topbar">
      <div className="topbar-left">
        <span className="topbar-title">{title}</span>
      </div>
      <div className="topbar-right">
        <button className="btn btn-ghost btn-sm" title="Notifications">
          <Bell size={16} />
        </button>
        <button className="btn btn-ghost btn-sm" title="Help">
          <HelpCircle size={16} />
        </button>
        <div style={{
          width: 32, height: 32, borderRadius: '50%',
          background: 'linear-gradient(135deg, var(--color-accent), var(--color-accent-2))',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontSize: 13, fontWeight: 700, color: 'white', flexShrink: 0
        }}>
          F
        </div>
      </div>
    </header>
  )
}
