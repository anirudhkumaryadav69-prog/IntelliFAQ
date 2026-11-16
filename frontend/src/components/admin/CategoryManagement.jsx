import { useEffect, useState } from 'react'
import { Plus, Pencil, Trash2, Check, X } from 'lucide-react'
import {
  fetchAdminCategories,
  createAdminCategory,
  renameAdminCategory,
  deleteAdminCategory,
} from '../../services/adminApi'

function CategoryManagement() {
  const [categories, setCategories] = useState([])
  const [newName, setNewName] = useState('')
  const [editingId, setEditingId] = useState(null)
  const [editingName, setEditingName] = useState('')
  const [deleteTarget, setDeleteTarget] = useState(null)
  const [reassignId, setReassignId] = useState('')
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState('')

  const reload = async () => {
    setIsLoading(true)
    const res = await fetchAdminCategories()
    setIsLoading(false)
    if (!res.ok) {
      setError(res.error || 'Failed to load categories.')
      return
    }
    setCategories(res.data.categories || [])
  }

  useEffect(() => {
    let active = true
    fetchAdminCategories().then((res) => {
      if (!active) return
      setIsLoading(false)
      if (!res.ok) {
        setError(res.error || 'Failed to load categories.')
        return
      }
      setCategories(res.data.categories || [])
    })
    return () => {
      active = false
    }
  }, [])

  const handleAdd = async (e) => {
    e.preventDefault()
    setError('')
    if (!newName.trim()) {
      setError('Category name cannot be empty.')
      return
    }
    const res = await createAdminCategory(newName.trim())
    if (!res.ok) {
      setError(res.error || 'Failed to create category.')
      return
    }
    setNewName('')
    reload()
  }

  const handleRename = async (categoryId) => {
    setError('')
    if (!editingName.trim()) {
      setError('Category name cannot be empty.')
      return
    }
    const res = await renameAdminCategory(categoryId, editingName.trim())
    if (!res.ok) {
      setError(res.error || 'Failed to rename category.')
      return
    }
    setEditingId(null)
    reload()
  }

  const openDeleteDialog = (cat) => {
    setError('')
    setDeleteTarget(cat)
    const fallbackTarget = categories.find((c) => c.category_id !== cat.category_id)
    setReassignId(fallbackTarget ? String(fallbackTarget.category_id) : '')
  }

  const handleConfirmDelete = async () => {
    if (!deleteTarget) return
    setError('')
    const needsReassign = (deleteTarget.faq_count || 0) > 0
    if (needsReassign && !reassignId) {
      setError('Please select a target category to reassign existing FAQs.')
      return
    }
    const res = await deleteAdminCategory(
      deleteTarget.category_id,
      needsReassign ? Number(reassignId) : null
    )
    if (!res.ok) {
      setError(res.error || 'Failed to delete category.')
      return
    }
    setDeleteTarget(null)
    reload()
  }

  return (
    <div className="admin-page">
      <div className="admin-page-header">
        <div>
          <h1>Category Management</h1>
          <p>Manage institutional FAQ categories safely without orphaning FAQs.</p>
        </div>
      </div>

      <form onSubmit={handleAdd} className="admin-toolbar">
        <input
          type="text"
          className="dialog-text-input"
          value={newName}
          onChange={(e) => setNewName(e.target.value)}
          placeholder="New category name..."
          maxLength={80}
        />
        <button type="submit" className="dialog-btn-primary admin-add-btn">
          <Plus size={16} />
          <span>Add Category</span>
        </button>
      </form>

      {error && <p className="dialog-error-text" role="alert">{error}</p>}

      {isLoading ? (
        <div className="admin-panel-state">Loading categories...</div>
      ) : (
        <div className="admin-table-wrap">
          <table className="admin-table">
            <thead>
              <tr>
                <th>ID</th>
                <th>Category Name</th>
                <th>FAQs</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {categories.map((cat) => (
                <tr key={cat.category_id}>
                  <td>#{cat.category_id}</td>
                  <td>
                    {editingId === cat.category_id ? (
                      <input
                        type="text"
                        className="dialog-text-input"
                        value={editingName}
                        onChange={(e) => setEditingName(e.target.value)}
                        autoFocus
                      />
                    ) : (
                      <strong>{cat.name}</strong>
                    )}
                  </td>
                  <td>{cat.faq_count}</td>
                  <td>
                    <div className="admin-row-actions">
                      {editingId === cat.category_id ? (
                        <>
                          <button
                            type="button"
                            className="admin-icon-btn"
                            title="Save"
                            onClick={() => handleRename(cat.category_id)}
                          >
                            <Check size={15} />
                          </button>
                          <button
                            type="button"
                            className="admin-icon-btn"
                            title="Cancel"
                            onClick={() => setEditingId(null)}
                          >
                            <X size={15} />
                          </button>
                        </>
                      ) : (
                        <>
                          <button
                            type="button"
                            className="admin-icon-btn"
                            title="Rename category"
                            onClick={() => {
                              setEditingId(cat.category_id)
                              setEditingName(cat.name)
                            }}
                          >
                            <Pencil size={15} />
                          </button>
                          <button
                            type="button"
                            className="admin-icon-btn-danger"
                            title="Delete category"
                            onClick={() => openDeleteDialog(cat)}
                          >
                            <Trash2 size={15} />
                          </button>
                        </>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {deleteTarget && (
        <div className="modal-backdrop" role="dialog" aria-modal="true" onClick={() => setDeleteTarget(null)}>
          <div className="modal-card modal-card-compact" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h2>Delete Category “{deleteTarget.name}”</h2>
            </div>
            <div className="modal-body">
              {deleteTarget.faq_count > 0 ? (
                <>
                  <p className="modal-lead">
                    This category contains <strong>{deleteTarget.faq_count}</strong> FAQ(s).
                    Select another category to reassign them before deleting:
                  </p>
                  <select
                    className="dialog-text-input"
                    value={reassignId}
                    onChange={(e) => setReassignId(e.target.value)}
                  >
                    {categories
                      .filter((c) => c.category_id !== deleteTarget.category_id)
                      .map((c) => (
                        <option key={c.category_id} value={c.category_id}>
                          {c.name} ({c.faq_count} FAQs)
                        </option>
                      ))}
                  </select>
                </>
              ) : (
                <p className="modal-lead">
                  This category has no FAQs and can be safely deleted.
                </p>
              )}

              <div className="modal-actions-row">
                <button type="button" className="dialog-btn-secondary" onClick={() => setDeleteTarget(null)}>
                  Cancel
                </button>
                <button
                  type="button"
                  className="dialog-btn-danger"
                  onClick={handleConfirmDelete}
                  disabled={deleteTarget.faq_count > 0 && !reassignId}
                >
                  {deleteTarget.faq_count > 0 ? 'Reassign & Delete' : 'Delete Category'}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default CategoryManagement
