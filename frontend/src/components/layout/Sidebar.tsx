import { NavLink } from 'react-router-dom'
import {
  BarChart3, Upload, RefreshCw, AlertTriangle,
  LineChart, DollarSign, FileDown, Activity,
  Zap
} from 'lucide-react'
import { useQuery } from '@tanstack/react-query'
import { fetchExceptions } from '../../api/client'

const navItems = [
  { to: '/dashboard', label: 'Dashboard', icon: BarChart3 },
  { to: '/uploads', label: 'Data Uploads', icon: Upload },
  { to: '/reconciliation', label: 'Reconciliation', icon: RefreshCw },
  { to: '/exceptions', label: 'Exceptions', icon: AlertTriangle, badge: true },
  { to: '/analytics', label: 'Analytics', icon: LineChart },
  { to: '/pricing', label: 'Pricing & Savings', icon: DollarSign },
  { to: '/reports', label: 'Reports', icon: FileDown },
]

export default function Sidebar() {
  const { data: excData } = useQuery({
    queryKey: ['exceptions-count'],
    queryFn: () => fetchExceptions({ review_status: 'open', page: 1, page_size: 1 }),
    refetchInterval: 60_000,
  })

  const openCount: number = excData?.total ?? 0

  return (
    <aside className="sidebar">
      <div className="sidebar-logo">
        <div className="logo-icon">
          <Zap size={18} color="white" />
        </div>
        <div className="logo-text">
          <span className="logo-name">FinOps AI</span>
          <span className="logo-tagline">Cost Intelligence</span>
        </div>
      </div>

      <nav className="sidebar-nav">
        <span className="nav-section-label">Main</span>
        {navItems.map(({ to, label, icon: Icon, badge }) => (
          <NavLink
            key={to}
            to={to}
            className={({ isActive }) => `nav-item${isActive ? ' active' : ''}`}
          >
            <span className="nav-item-icon">
              <Icon size={16} />
            </span>
            {label}
            {badge && openCount > 0 && (
              <span className="nav-badge">{openCount > 99 ? '99+' : openCount}</span>
            )}
          </NavLink>
        ))}
      </nav>

      <div className="sidebar-footer">
        <div className="sidebar-status">
          <span className="status-dot" />
          <span>API Connected</span>
        </div>
        <div style={{ marginTop: '6px', fontSize: '11px', color: 'var(--color-text-muted)' }}>
          v1.0.0 · FinOps AI
        </div>
      </div>
    </aside>
  )
}
