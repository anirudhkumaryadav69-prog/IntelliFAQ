import { useEffect, useState, useCallback } from 'react'
import { Search, PlusCircle } from 'lucide-react'
import {
  fetchUnansweredQuestions,
  updateUnansweredQuestion,
  fetchAdminCategories,
  createAdminFaq,
} from '../../services/adminApi'
import FAQEditor from './FAQEditor'

const STATUS_OPTIONS = ['', 'unreviewed', 'reviewed', 'resolved', 'dismissed']

function UnansweredQuestions() {
  const [items, setItems] = useState([])
  const [categories, setCategories] = useState([])
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState('')

  const [faqSourceItem, setFaqSourceItem] = useState(null)
  const [isSavingFaq, setIsSavingFaq] = useState(false)
  const [editorError, setEditorError] = useState('')

  const loadItems = useCallback(async (q = search, st = statusFilter) => {
    setIsLoading(true)
    setError('')
    const [res, catRes] = await Promise.all([
      fetchUnansweredQuestions(q, st),
      fetchAdminCategories(),
    ])
    setIsLoading(false)
    if (!res.ok) {
      setError(res.error || 'Failed to load unanswered questions.')
      return
    }
    setItems(res.data.items || [])
    if (catRes.ok) {
      setCategories(catRes.data.categories || [])
    }
  }, [search, statusFilter])

  useEffect(() => {
    let active = true
    Promise.all([fetchUnansweredQuestions('', ''), fetchAdminCategories()]).then(
      ([res, catRes]) => {
        if (!active) return
        setIsLoading(false)
        if (!res.ok) {
          setError(res.error || 'Failed to load unanswered questions.')
          return
        }
        setItems(res.data.items || [])
        if (catRes.ok) {
          setCategories(catRes.data.categories || [])
        }
      }
    )
    return () => {
      active = false
    }
  }, [])

  const handleStatusChange = async (item, newStatus) => {
    const res = await updateUnansweredQuestion(item.item_id, { status: newStatus })
    if (!res.ok) {
      setError(res.error || 'Failed to update status.')
      return
    }
    setItems((prev) =>
      prev.map((it) => (it.item_id === item.item_id ? res.data.item : it))
    )
  }

  const handleCreateFaqFromQuery = async (payload) => {
    if (!faqSourceItem) return
    setIsSavingFaq(true)
    setEditorError('')
    const res = await createAdminFaq(payload)
    setIsSavingFaq(false)
    if (!res.ok) {
      setEditorError(res.error || 'Failed to create FAQ.')
      return
    }
    await updateUnansweredQuestion(faqSourceItem.item_id, {
      status: 'resolved',
      review_notes: `Resolved via FAQ #${res.data.faq?.faq_id}`,
    })
    setFaqSourceItem(null)
    loadItems(search, statusFilter)
  }

  return (
    <div className="admin-page">
      <div className="admin-page-header">
        <div>
          <h1>Unanswered Student Questions</h1>
          <p>Review unresolved queries and optionally author verified FAQs from them.</p>
        </div>
      </div>

      <div className="admin-toolbar">
        <div className="admin-search-wrap">
          <Search size={15} className="admin-input-icon" />
          <input
            type="text"
            className="admin-input"
            value={search}
            onChange={(e) => {
              const val = e.target.value
              setSearch(val)
              loadItems(val, statusFilter)
            }}
            placeholder="Search student queries..."
          />
        </div>

        <select
          className="dialog-text-input admin-filter-select"
          value={statusFilter}
          onChange={(e) => {
            const val = e.target.value
            setStatusFilter(val)
            loadItems(search, val)
          }}
        >
          {STATUS_OPTIONS.map((opt) => (
            <option key={opt || 'all'} value={opt}>
              {opt ? opt.charAt(0).toUpperCase() + opt.slice(1) : 'All Statuses'}
            </option>
          ))}
        </select>
      </div>

      {error && <p className="dialog-error-text">{error}</p>}

      {isLoading ? (
        <div className="admin-panel-state">Loading unanswered questions...</div>
      ) : items.length === 0 ? (
        <div className="admin-panel-state">No unanswered questions match your filters.</div>
      ) : (
        <div className="admin-table-wrap">
          <table className="admin-table">
            <thead>
              <tr>
                <th>Query</th>
                <th>Match Type</th>
                <th>Count</th>
                <th>Status</th>
                <th>Last Seen</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr key={item.item_id}>
                  <td className="admin-table-question">{item.query_text}</td>
                  <td><span className="admin-cat-badge">{item.match_type}</span></td>
                  <td>{item.occurrence_count}</td>
                  <td>
                    <select
                      className="dialog-text-input admin-status-select"
                      value={item.status}
                      onChange={(e) => handleStatusChange(item, e.target.value)}
                    >
                      <option value="unreviewed">Unreviewed</option>
                      <option value="reviewed">Reviewed</option>
                      <option value="resolved">Resolved</option>
                      <option value="dismissed">Dismissed</option>
                    </select>
                  </td>
                  <td>{new Date(item.updated_at).toLocaleDateString()}</td>
                  <td>
                    <button
                      type="button"
                      className="dialog-btn-secondary admin-small-btn"
                      onClick={() => {
                        setEditorError('')
                        setFaqSourceItem(item)
                      }}
                    >
                      <PlusCircle size={14} />
                      <span>Create FAQ</span>
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {faqSourceItem && (
        <FAQEditor
          key={`from-unanswered-${faqSourceItem.item_id}`}
          mode="create"
          faq={null}
          initialQuestion={faqSourceItem.query_text}
          categories={categories}
          isSaving={isSavingFaq}
          errorMessage={editorError}
          onSave={handleCreateFaqFromQuery}
          onClose={() => setFaqSourceItem(null)}
        />
      )}
    </div>
  )
}

export default UnansweredQuestions
