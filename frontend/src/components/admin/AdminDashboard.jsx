import { useEffect, useState } from 'react'
import {
  BookOpen,
  FolderTree,
  Layers,
  AlertCircle,
  Clock,
  RefreshCw,
  FileText,
} from 'lucide-react'
import {
  fetchAdminDashboard,
  fetchDocumentAnalytics,
} from '../../services/adminApi'

function formatShortDate(iso) {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return String(iso)
  return d.toLocaleString([], {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function AdminDashboard({ onNavigate }) {
  const [dashboard, setDashboard] = useState(null)
  const [docAnalytics, setDocAnalytics] = useState(null)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState('')

  const loadDashboard = async () => {
    setIsLoading(true)
    setError('')
    const [res, docRes] = await Promise.all([
      fetchAdminDashboard(),
      fetchDocumentAnalytics(),
    ])
    setIsLoading(false)
    if (!res.ok) {
      setError(res.error || 'Failed to load dashboard statistics.')
      return
    }
    setDashboard(res.data.dashboard)
    if (docRes.ok) {
      setDocAnalytics(docRes.data.analytics)
    }
  }

  useEffect(() => {
    let active = true
    Promise.all([fetchAdminDashboard(), fetchDocumentAnalytics()]).then(
      ([res, docRes]) => {
        if (!active) return
        setIsLoading(false)
        if (!res.ok) {
          setError(res.error || 'Failed to load dashboard statistics.')
          return
        }
        setDashboard(res.data.dashboard)
        if (docRes.ok) {
          setDocAnalytics(docRes.data.analytics)
        }
      }
    )
    return () => {
      active = false
    }
  }, [])

  if (isLoading) {
    return <div className="admin-panel-state">Loading dashboard statistics...</div>
  }

  if (error) {
    return (
      <div className="admin-panel-error">
        <p>{error}</p>
        <button type="button" className="dialog-btn-secondary" onClick={loadDashboard}>
          Retry
        </button>
      </div>
    )
  }

  const maxCatCount = Math.max(
    1,
    ...(dashboard?.category_distribution || []).map((c) => c.count || 0)
  )

  return (
    <div className="admin-page">
      <div className="admin-page-header">
        <div>
          <h1>Admin Dashboard</h1>
          <p>Live overview of IntelliFAQ knowledge base and unanswered queries.</p>
        </div>
        <button
          type="button"
          className="dialog-btn-secondary admin-refresh-btn"
          onClick={loadDashboard}
        >
          <RefreshCw size={15} />
          <span>Refresh</span>
        </button>
      </div>

      <div className="admin-stats-grid">
        <div className="admin-stat-card" onClick={() => onNavigate('/admin/faqs')}>
          <div className="admin-stat-icon"><BookOpen size={20} /></div>
          <div>
            <span className="admin-stat-label">Total FAQs</span>
            <strong className="admin-stat-value">{dashboard?.total_faqs ?? 0}</strong>
          </div>
        </div>
        <div className="admin-stat-card" onClick={() => onNavigate('/admin/categories')}>
          <div className="admin-stat-icon"><FolderTree size={20} /></div>
          <div>
            <span className="admin-stat-label">FAQ Categories</span>
            <strong className="admin-stat-value">{dashboard?.total_categories ?? 0}</strong>
          </div>
        </div>
        <div className="admin-stat-card" onClick={() => onNavigate('/admin/faqs')}>
          <div className="admin-stat-icon"><Layers size={20} /></div>
          <div>
            <span className="admin-stat-label">Alternative Phrasings</span>
            <strong className="admin-stat-value">{dashboard?.total_alternatives ?? 0}</strong>
          </div>
        </div>
        <div className="admin-stat-card" onClick={() => onNavigate('/admin/unanswered')}>
          <div className="admin-stat-icon admin-stat-icon-warn"><AlertCircle size={20} /></div>
          <div>
            <span className="admin-stat-label">Unreviewed Questions</span>
            <strong className="admin-stat-value">{dashboard?.total_unanswered ?? 0}</strong>
          </div>
        </div>
      </div>

      {docAnalytics && (
        <div className="admin-stats-grid">
          <div className="admin-stat-card" onClick={() => onNavigate('/admin/documents')}>
            <div className="admin-stat-icon"><FileText size={20} /></div>
            <div>
              <span className="admin-stat-label">Uploaded Documents</span>
              <strong className="admin-stat-value">{docAnalytics.total_documents}</strong>
            </div>
          </div>
          <div className="admin-stat-card" onClick={() => onNavigate('/admin/documents')}>
            <div>
              <span className="admin-stat-label">Approved Documents</span>
              <strong className="admin-stat-value">{docAnalytics.approved_documents}</strong>
            </div>
          </div>
          <div className="admin-stat-card" onClick={() => onNavigate('/admin/documents')}>
            <div>
              <span className="admin-stat-label">Pending Document Review</span>
              <strong className="admin-stat-value">{docAnalytics.pending_review}</strong>
            </div>
          </div>
          <div className="admin-stat-card" onClick={() => onNavigate('/admin/documents')}>
            <div>
              <span className="admin-stat-label">Failed / OCR Needed</span>
              <strong className="admin-stat-value">{docAnalytics.failed_processing}</strong>
            </div>
          </div>
          <div className="admin-stat-card" onClick={() => onNavigate('/admin/documents')}>
            <div>
              <span className="admin-stat-label">Indexed Doc Chunks</span>
              <strong className="admin-stat-value">{docAnalytics.total_indexed_chunks}</strong>
            </div>
          </div>
        </div>
      )}

      <div className="admin-two-col">
        <section className="admin-card">
          <h2>Category Distribution</h2>
          <div className="admin-dist-list">
            {(dashboard?.category_distribution || []).map((item) => {
              const pct = Math.round(((item.count || 0) / maxCatCount) * 100)
              return (
                <div key={item.category_id} className="admin-dist-row">
                  <div className="admin-dist-label">
                    <span>{item.category}</span>
                    <strong>{item.count}</strong>
                  </div>
                  <div className="admin-dist-bar-bg">
                    <div className="admin-dist-bar-fill" style={{ width: `${pct}%` }} />
                  </div>
                </div>
              )
            })}
          </div>
        </section>

        <section className="admin-card">
          <h2>Recent Activity</h2>
          {(dashboard?.recent_activity || []).length === 0 ? (
            <p className="admin-muted">No recent administrative changes recorded yet.</p>
          ) : (
            <ul className="admin-activity-list">
              {dashboard.recent_activity.map((act) => (
                <li key={act.activity_id} className="admin-activity-item">
                  <Clock size={14} className="admin-muted-icon" />
                  <div className="admin-activity-text">
                    <span>
                      <strong>{act.action}</strong> {act.entity_type}: {act.entity_label}
                    </span>
                    <small>{formatShortDate(act.created_at)}</small>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>

      <div className="admin-two-col">
        <section className="admin-card">
          <h2>Recently Added FAQs</h2>
          <ul className="admin-mini-list">
            {(dashboard?.recently_added_faqs || []).map((faq) => (
              <li key={faq.faq_id}>
                <span className="admin-mini-id">#{faq.faq_id}</span>
                <div>
                  <p>{faq.question}</p>
                  <small>{faq.category} • {formatShortDate(faq.created_at)}</small>
                </div>
              </li>
            ))}
          </ul>
        </section>

        <section className="admin-card">
          <h2>Recently Updated FAQs</h2>
          <ul className="admin-mini-list">
            {(dashboard?.recently_updated_faqs || []).map((faq) => (
              <li key={faq.faq_id}>
                <span className="admin-mini-id">#{faq.faq_id}</span>
                <div>
                  <p>{faq.question}</p>
                  <small>{faq.category} • {formatShortDate(faq.updated_at)}</small>
                </div>
              </li>
            ))}
          </ul>
        </section>
      </div>
    </div>
  )
}

export default AdminDashboard
