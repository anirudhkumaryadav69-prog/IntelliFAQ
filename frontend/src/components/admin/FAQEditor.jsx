import { useState } from 'react'
import { Plus, Trash2, X } from 'lucide-react'

function FAQEditor({
  mode,
  faq,
  categories,
  initialQuestion = '',
  isSaving,
  errorMessage,
  onSave,
  onClose,
}) {
  const isViewOnly = mode === 'view'
  const [question, setQuestion] = useState(
    faq?.question || initialQuestion || ''
  )
  const [answer, setAnswer] = useState(faq?.answer || '')
  const [categoryId, setCategoryId] = useState(
    faq?.category_id ?? categories[0]?.category_id ?? ''
  )
  const [alternatives, setAlternatives] = useState(() => {
    if (Array.isArray(faq?.alternative_questions)) {
      return faq.alternative_questions.map((a) =>
        typeof a === 'string' ? a : a.question || ''
      )
    }
    return []
  })
  const [newAlt, setNewAlt] = useState('')
  const [localError, setLocalError] = useState('')

  const handleAddAlternative = () => {
    const trimmed = newAlt.trim()
    if (!trimmed) return
    if (
      alternatives.some((a) => a.toLowerCase() === trimmed.toLowerCase()) ||
      trimmed.toLowerCase() === question.trim().toLowerCase()
    ) {
      setLocalError('That phrasing is already listed.')
      return
    }
    setLocalError('')
    setAlternatives((prev) => [...prev, trimmed])
    setNewAlt('')
  }

  const handleUpdateAlternative = (idx, value) => {
    setAlternatives((prev) => prev.map((item, i) => (i === idx ? value : item)))
  }

  const handleRemoveAlternative = (idx) => {
    setAlternatives((prev) => prev.filter((_, i) => i !== idx))
  }

  const handleSubmit = (e) => {
    e.preventDefault()
    if (isViewOnly) {
      onClose()
      return
    }
    if (!question.trim()) {
      setLocalError('Canonical question is required.')
      return
    }
    if (!answer.trim()) {
      setLocalError('Answer is required.')
      return
    }
    if (!categoryId) {
      setLocalError('Please select a category.')
      return
    }
    setLocalError('')
    onSave({
      question: question.trim(),
      answer: answer.trim(),
      category_id: Number(categoryId),
      alternative_questions: alternatives
        .map((a) => a.trim())
        .filter(Boolean),
    })
  }

  const titleText =
    mode === 'create'
      ? 'Add New FAQ'
      : mode === 'edit'
      ? `Edit FAQ #${faq?.faq_id}`
      : `View FAQ #${faq?.faq_id}`

  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" onClick={onClose}>
      <div className="modal-card admin-editor-modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <div className="modal-title-group">
            <h2>{titleText}</h2>
          </div>
          <button type="button" className="modal-close-btn" onClick={onClose} aria-label="Close">
            <X size={18} />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="modal-body admin-editor-form">
          <div className="admin-form-group">
            <label className="dialog-field-label" htmlFor="faq-category-select">
              Category
            </label>
            <select
              id="faq-category-select"
              className="dialog-text-input"
              value={categoryId}
              onChange={(e) => setCategoryId(e.target.value)}
              disabled={isViewOnly || isSaving}
            >
              {categories.map((c) => (
                <option key={c.category_id} value={c.category_id}>
                  {c.name}
                </option>
              ))}
            </select>
          </div>

          <div className="admin-form-group">
            <label className="dialog-field-label" htmlFor="faq-question-input">
              Canonical Question
            </label>
            <input
              id="faq-question-input"
              type="text"
              className="dialog-text-input"
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              disabled={isViewOnly || isSaving}
              placeholder="Enter canonical FAQ question"
            />
          </div>

          <div className="admin-form-group">
            <label className="dialog-field-label" htmlFor="faq-answer-input">
              Answer
            </label>
            <textarea
              id="faq-answer-input"
              rows={4}
              className="dialog-text-input admin-textarea"
              value={answer}
              onChange={(e) => setAnswer(e.target.value)}
              disabled={isViewOnly || isSaving}
              placeholder="Enter verified FAQ answer"
            />
          </div>

          <div className="admin-form-group">
            <label className="dialog-field-label">
              Alternative Question Phrasings ({alternatives.length})
            </label>

            <div className="admin-alts-list">
              {alternatives.map((alt, idx) => (
                <div key={idx} className="admin-alt-row">
                  <input
                    type="text"
                    className="dialog-text-input"
                    value={alt}
                    onChange={(e) => handleUpdateAlternative(idx, e.target.value)}
                    disabled={isViewOnly || isSaving}
                  />
                  {!isViewOnly && (
                    <button
                      type="button"
                      className="admin-icon-btn-danger"
                      onClick={() => handleRemoveAlternative(idx)}
                      aria-label="Remove alternative phrasing"
                    >
                      <Trash2 size={14} />
                    </button>
                  )}
                </div>
              ))}
            </div>

            {!isViewOnly && (
              <div className="admin-alt-add-row">
                <input
                  type="text"
                  className="dialog-text-input"
                  value={newAlt}
                  onChange={(e) => setNewAlt(e.target.value)}
                  placeholder="Add an alternative phrasing..."
                  disabled={isSaving}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') {
                      e.preventDefault()
                      handleAddAlternative()
                    }
                  }}
                />
                <button
                  type="button"
                  className="dialog-btn-secondary"
                  onClick={handleAddAlternative}
                  disabled={isSaving}
                >
                  <Plus size={14} /> Add
                </button>
              </div>
            )}
          </div>

          {(localError || errorMessage) && (
            <p className="dialog-error-text" role="alert">
              {localError || errorMessage}
            </p>
          )}

          <div className="modal-actions-row">
            <button type="button" className="dialog-btn-secondary" onClick={onClose}>
              {isViewOnly ? 'Close' : 'Cancel'}
            </button>
            {!isViewOnly && (
              <button type="submit" className="dialog-btn-primary" disabled={isSaving}>
                {isSaving ? 'Saving...' : mode === 'create' ? 'Create FAQ' : 'Save Changes'}
              </button>
            )}
          </div>
        </form>
      </div>
    </div>
  )
}

export default FAQEditor
