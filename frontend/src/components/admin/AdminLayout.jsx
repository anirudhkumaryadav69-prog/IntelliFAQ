import { useEffect, useState } from 'react'
import {
  fetchAdminMe,
  adminLogout,
  onAdminAuthExpired,
} from '../../services/adminApi'
import AdminLogin from './AdminLogin'
import AdminSidebar from './AdminSidebar'
import AdminDashboard from './AdminDashboard'
import FAQManagement from './FAQManagement'
import CategoryManagement from './CategoryManagement'
import FAQPreview from './FAQPreview'
import UnansweredQuestions from './UnansweredQuestions'
import DocumentManagement from './DocumentManagement'

function AdminLayout({ currentPath, onNavigate, onExitAdmin }) {
  const [adminUser, setAdminUser] = useState(null)
  const [isCheckingAuth, setIsCheckingAuth] = useState(true)

  useEffect(() => {
    let active = true
    const unsubscribe = onAdminAuthExpired(() => {
      if (active) {
        setAdminUser(null)
      }
    })
    fetchAdminMe().then((res) => {
      if (!active) return
      setIsCheckingAuth(false)
      if (res.ok && res.data.admin) {
        setAdminUser(res.data.admin)
      } else {
        setAdminUser(null)
      }
    })
    return () => {
      active = false
      unsubscribe()
    }
  }, [])

  const handleLogout = async () => {
    await adminLogout()
    setAdminUser(null)
    onNavigate('/admin')
  }

  if (isCheckingAuth) {
    return (
      <div className="admin-login-page">
        <div className="admin-panel-state">Verifying administrator session...</div>
      </div>
    )
  }

  if (!adminUser) {
    return (
      <AdminLogin
        onLoginSuccess={(user) => setAdminUser(user)}
        onExitAdmin={onExitAdmin}
      />
    )
  }

  const renderSection = () => {
    if (currentPath.startsWith('/admin/faqs')) {
      return <FAQManagement />
    }
    if (currentPath.startsWith('/admin/documents')) {
      return <DocumentManagement />
    }
    if (currentPath.startsWith('/admin/categories')) {
      return <CategoryManagement />
    }
    if (currentPath.startsWith('/admin/unanswered')) {
      return <UnansweredQuestions />
    }
    if (currentPath.startsWith('/admin/test-chatbot')) {
      return <FAQPreview />
    }
    return <AdminDashboard onNavigate={onNavigate} />
  }

  return (
    <div className="app-layout admin-layout">
      <AdminSidebar
        currentPath={currentPath}
        adminUser={adminUser}
        onNavigate={onNavigate}
        onLogout={handleLogout}
        onExitAdmin={onExitAdmin}
      />
      <main className="admin-main">{renderSection()}</main>
    </div>
  )
}

export default AdminLayout
