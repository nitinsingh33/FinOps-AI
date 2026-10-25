import { NavLink } from 'react-router-dom'
import {
  BarChart3, Upload, RefreshCw, AlertTriangle,
  LineChart, DollarSign, FileDown, Landmark, ShieldCheck
} from 'lucide-react'
import { useQuery } from '@tanstack/react-query'
import { fetchExceptions } from '../../api/client'

const navGroups = [
  {
    label: 'Workspace',
    items: [
      { to: '/dashboard', label: 'Dashboard', icon: BarChart3 },
      { to: '/analytics', label: 'Analytics', icon: LineChart },
      { to: '/pricing', label: 'Pricing & Savings', icon: DollarSign },
      { to: '/reports', label: 'Reports', icon: FileDown },
    ],
  },
  {
    label: 'Operations',
    items: [
      { to: '/reconciliation', label: 'Reconciliation', icon: RefreshCw },
      { to: '/exceptions', label: 'Exceptions', icon: AlertTriangle, badge: true },
      { to: '/vendor-compliance', label: 'Vendor Compliance', icon: ShieldCheck },
    ],
  },
  {
    label: 'Data Sources',
    items: [{ to: '/uploads', label: 'Data Uploads', icon: Upload }],
  },
]

export default function Sidebar() {
  const { data: excData } = useQuery({
    queryKey: ['exceptions-count'],
    queryFn: () => fetchExceptions({ review_status: 'open', page: 1, page_size: 1 }),
    refetchInterval: 60_000,
  })

  const openCount: number = excData?.total ?? 0

  return (
    <aside className="sidebar" aria-label="Application sidebar">
      <div className="sidebar-logo" aria-label="FinOps AI">
        <div className="logo-icon">
          <Landmark size={17} strokeWidth={1.8} aria-hidden="true" />
        </div>
        <span className="logo-name">FinOps AI</span>
      </div>

      <nav className="sidebar-nav" aria-label="Primary navigation">
        {navGroups.map(group => (
          <section className="nav-group" key={group.label} aria-labelledby={`nav-group-${group.label.toLowerCase().replaceAll(' ', '-')}`}>
            <h2 className="nav-section-label" id={`nav-group-${group.label.toLowerCase().replaceAll(' ', '-')}`}>{group.label}</h2>
            {group.items.map(({ to, label, icon: Icon, badge }) => (
              <NavLink
                key={to}
                to={to}
                end
                title={label}
                aria-label={label}
                className={({ isActive }) => `nav-item${isActive ? ' active' : ''}`}
              >
                <span className="nav-item-icon"><Icon size={17} strokeWidth={1.8} aria-hidden="true" /></span>
                <span className="nav-item-label">{label}</span>
                {badge && openCount > 0 && (
                  <span className="nav-badge" aria-label={`${openCount} open exceptions`}>
                    {openCount > 99 ? '99+' : openCount}
                  </span>
                )}
              </NavLink>
            ))}
          </section>
        ))}
      </nav>
    </aside>
  )
}
