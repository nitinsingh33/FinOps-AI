import { Routes, Route, Navigate } from 'react-router-dom'
import Layout from './components/layout/Layout'
import DashboardPage from './pages/DashboardPage'
import UploadsPage from './pages/UploadsPage'
import ReconciliationPage from './pages/ReconciliationPage'
import ExceptionsPage from './pages/ExceptionsPage'
import AnalyticsPage from './pages/AnalyticsPage'
import PricingPage from './pages/PricingPage'
import ReportsPage from './pages/ReportsPage'
import VendorCompliancePage from './pages/VendorCompliancePage'

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Layout />}>
        <Route index element={<Navigate to="/dashboard" replace />} />
        <Route path="dashboard" element={<DashboardPage />} />
        <Route path="uploads" element={<UploadsPage />} />
        <Route path="reconciliation" element={<ReconciliationPage />} />
        <Route path="exceptions" element={<ExceptionsPage />} />
        <Route path="analytics" element={<AnalyticsPage />} />
        <Route path="pricing" element={<PricingPage />} />
        <Route path="reports" element={<ReportsPage />} />
        <Route path="vendor-compliance" element={<VendorCompliancePage />} />
      </Route>
    </Routes>
  )
}
