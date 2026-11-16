import {
  Shield,
  LayoutDashboard,
  BookOpen,
  FolderTree,
  FileText,
  HelpCircle,
  FlaskConical,
  LogOut,
  ArrowLeft,
} from 'lucide-react'

const ADMIN_NAV_ITEMS = [
  { path: '/admin', label: 'Dashboard', icon: LayoutDashboard },
  { path: '/admin/faqs', label: 'FAQ Management', icon: BookOpen },
  { path: '/admin/documents', label: 'Document Knowledge Base', icon: FileText },
  { path: '/admin/categories', label: 'Categories', icon: FolderTree },
  { path: '/admin/unanswered', label: 'Unanswered Queries', icon: HelpCircle },
  { path: '/admin/test-chatbot', label: 'Preview & Test', icon: FlaskConical },
]

function AdminSidebar({
  currentPath,
  adminUser,
  onNavigate,
  onLogout,
  onExitAdmin,
}) {
  return (
    <aside className="sidebar admin-sidebar" aria-label="Admin navigation">
      <div className="sidebar-header">
        <div className="brand-group">
          <div className="brand-logo" aria-hidden="true">
            <Shield size={20} strokeWidth={2.1} />
          </div>
          <div className="brand-text">
            <span className="brand-title">IntelliFAQ</span>
            <span className="brand-subtitle">Admin Console</span>
          </div>
        </div>
      </div>

      <nav className="sidebar-nav" aria-label="Admin sections">
        <div className="nav-section-label">Knowledge Base</div>
        {ADMIN_NAV_ITEMS.map((item) => {
          const Icon = item.icon
          const isActive =
            item.path === '/admin'
              ? currentPath === '/admin' || currentPath === '/admin/'
              : currentPath.startsWith(item.path)
          return (
            <button
              key={item.path}
              type="button"
              className={`nav-item ${isActive ? 'nav-item-active' : ''}`}
              onClick={() => onNavigate(item.path)}
            >
              <Icon size={17} strokeWidth={2} />
              <span>{item.label}</span>
            </button>
          )
        })}
      </nav>

      <div className="admin-sidebar-spacer" />

      <div className="sidebar-footer admin-sidebar-footer">
        <div className="admin-user-pill">
          <span>Signed in as</span>
          <strong>{adminUser?.username || 'admin'}</strong>
        </div>

        <button
          type="button"
          className="nav-item"
          onClick={onExitAdmin}
        >
          <ArrowLeft size={16} />
          <span>Student Chatbot</span>
        </button>

        <button
          type="button"
          className="nav-item admin-logout-btn"
          onClick={onLogout}
        >
          <LogOut size={16} />
          <span>Log Out</span>
        </button>
      </div>
    </aside>
  )
}

export default AdminSidebar
