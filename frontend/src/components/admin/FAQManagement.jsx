import { useEffect, useState, useCallback } from 'react'
import { Plus, Search, Eye, Pencil, Trash2 } from 'lucide-react'
import {
  fetchAdminFaqs,
  fetchAdminFaqDetail,
  fetchAdminCategories,
  createAdminFaq,
  updateAdminFaq,
  deleteAdminFaq,
} from '../../services/adminApi'
import FAQEditor from './FAQEditor'

function FAQManagement() {
  const [faqs, setFaqs] = useState([])
  const [categories, setCategories] = useState([])
  const [search, setSearch] = useState('')
  const [categoryFilter, setCategoryFilter] = useState('')
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState('')

  const [editorState, setEditorState] = useState(null)
  const [isSaving, setIsSaving] = useState(false)
  const [editorError, setEditorError] = useState('')
  const [deleteTarget, setDeleteTarget] = useState(null)

  const loadData = useCallback(async (q = search, catId = categoryFilter) => {
    setIsLoading(true)
    setError('')
    const [faqRes, catRes] = await Promise.all([
      fetchAdminFaqs(q, catId),
      fetchAdminCategories(),
    ])
    setIsLoading(false)
    if (!faqRes.ok) {
      setError(faqRes.error || 'Failed to load FAQs.')
      return
    }
    setFaqs(faqRes.data.faqs || [])
    if (catRes.ok) {
      setCategories(catRes.data.categories || [])
    }
  }, [search, categoryFilter])

  useEffect(() => {
    let active = true
    Promise.all([fetchAdminFaqs('', ''), fetchAdminCategories()]).then(
      ([faqRes, catRes]) => {
        if (!active) return
        setIsLoading(false)
        if (!faqRes.ok) {
          setError(faqRes.error || 'Failed to load FAQs.')
          return
        }
        setFaqs(faqRes.data.faqs || [])
        if (catRes.ok) {
          setCategories(catRes.data.categories || [])
        }
      }
    )
    return () => {
      active = false
    }
  }, [])

  const openEditor = async (mode, faqSummary = null) => {
    setEditorError('')
    if (mode === 'create') {
      setEditorState({ mode: 'create', faq: null })
      return
    }
    const res = await fetchAdminFaqDetail(faqSummary.faq_id)
    if (!res.ok) {
      setError(res.error || 'Failed to load FAQ details.')
      return
    }
    setEditorState({ mode, faq: res.data.faq })
  }

  const handleSaveFaq = async (payload) => {
    setIsSaving(true)
    setEditorError('')
    const res =
      editorState.mode === 'create'
        ? await createAdminFaq(payload)
        : await updateAdminFaq(editorState.faq.faq_id, payload)
    setIsSaving(false)

    if (!res.ok) {
      setEditorError(res.error || 'Failed to save FAQ.')
      return
    }
    setEditorState(null)
    loadData(search, categoryFilter)
  }

  const handleConfirmDelete = async () => {
    if (!deleteTarget) return
    const res = await deleteAdminFaq(deleteTarget.faq_id)
    if (!res.ok) {
      setError(res.error || 'Failed to delete FAQ.')
      setDeleteTarget(null)
      return
    }
    setDeleteTarget(null)
    loadData(search, categoryFilter)
  }

  return (
    <div className="admin-page">
      <div className="admin-page-header">
        <div>
          <h1>FAQ Management</h1>
          <p>Create, edit, and organize canonical FAQs and alternative phrasings.</p>
        </div>
        <button
          type="button"
          className="dialog-btn-primary admin-add-btn"
          onClick={() => openEditor('create')}
        >
          <Plus size={16} />
          <span>Add FAQ</span>
        </button>
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
              loadData(val, categoryFilter)
            }}
            placeholder="Search questions, answers, or alternatives..."
          />
        </div>

        <select
          className="dialog-text-input admin-filter-select"
          value={categoryFilter}
          onChange={(e) => {
            const val = e.target.value
            setCategoryFilter(val)
            loadData(search, val)
          }}
        >
          <option value="">All Categories</option>
          {categories.map((c) => (
            <option key={c.category_id} value={c.category_id}>
              {c.name} ({c.faq_count})
            </option>
          ))}
        </select>
      </div>

      {error && <p className="dialog-error-text">{error}</p>}

      {isLoading ? (
        <div className="admin-panel-state">Loading FAQs...</div>
      ) : faqs.length === 0 ? (
        <div className="admin-panel-state">No FAQs match your filters.</div>
      ) : (
        <div className="admin-table-wrap">
          <table className="admin-table">
            <thead>
              <tr>
                <th>ID</th>
                <th>Question</th>
                <th>Category</th>
                <th>Alternatives</th>
                <th>Updated</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {faqs.map((faq) => (
                <tr key={faq.faq_id}>
                  <td>#{faq.faq_id}</td>
                  <td className="admin-table-question">{faq.question}</td>
                  <td><span className="admin-cat-badge">{faq.category}</span></td>
                  <td>{faq.alternative_count}</td>
                  <td>{new Date(faq.updated_at).toLocaleDateString()}</td>
                  <td>
                    <div className="admin-row-actions">
                      <button
                        type="button"
                        className="admin-icon-btn"
                        title="View FAQ"
                        onClick={() => openEditor('view', faq)}
                      >
                        <Eye size={15} />
                      </button>
                      <button
                        type="button"
                        className="admin-icon-btn"
                        title="Edit FAQ"
                        onClick={() => openEditor('edit', faq)}
                      >
                        <Pencil size={15} />
                      </button>
                      <button
                        type="button"
                        className="admin-icon-btn-danger"
                        title="Delete FAQ"
                        onClick={() => setDeleteTarget(faq)}
                      >
                        <Trash2 size={15} />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {editorState && (
        <FAQEditor
          key={`${editorState.mode}-${editorState.faq?.faq_id || 'new'}`}
          mode={editorState.mode}
          faq={editorState.faq}
          categories={categories}
          isSaving={isSaving}
          errorMessage={editorError}
          onSave={handleSaveFaq}
          onClose={() => setEditorState(null)}
        />
      )}

      {deleteTarget && (
        <div className="modal-backdrop" role="dialog" aria-modal="true" onClick={() => setDeleteTarget(null)}>
          <div className="modal-card modal-card-compact" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h2>Delete FAQ #{deleteTarget.faq_id}</h2>
            </div>
            <div className="modal-body">
              <p className="modal-lead">
                Delete <strong>“{deleteTarget.question}”</strong> and all of its alternative phrasings?
              </p>
              <div className="modal-actions-row">
                <button type="button" className="dialog-btn-secondary" onClick={() => setDeleteTarget(null)}>
                  Cancel
                </button>
                <button type="button" className="dialog-btn-danger" onClick={handleConfirmDelete}>
                  Delete FAQ
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default FAQManagement
