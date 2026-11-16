import { useState } from 'react'
import { Pencil, X } from 'lucide-react'

const MAX_TITLE_LENGTH = 120

function RenameConversationDialog({
  conversation,
  isSaving,
  errorMessage,
  onSave,
  onCancel,
}) {
  const [titleInput, setTitleInput] = useState(conversation?.title || '')
  const [localError, setLocalError] = useState('')

  if (!conversation) return null

  const handleSubmit = (e) => {
    e.preventDefault()
    const trimmed = titleInput.trim()
    if (!trimmed) {
      setLocalError('Conversation title cannot be empty.')
      return
    }
    if (trimmed.length > MAX_TITLE_LENGTH) {
      setLocalError(`Title must be ${MAX_TITLE_LENGTH} characters or fewer.`)
      return
    }
    setLocalError('')
    onSave(conversation, trimmed)
  }

  const displayError = localError || errorMessage

  return (
    <div
      className="modal-backdrop"
      role="dialog"
      aria-modal="true"
      aria-labelledby="rename-dialog-title"
      onClick={onCancel}
    >
      <div
        className="modal-card modal-card-compact"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal-header">
          <div className="modal-title-group">
            <Pencil size={18} strokeWidth={2} />
            <h2 id="rename-dialog-title">Rename Conversation</h2>
          </div>
          <button
            type="button"
            className="modal-close-btn"
            onClick={onCancel}
            aria-label="Close rename dialog"
          >
            <X size={18} strokeWidth={2} />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="modal-body">
          <label htmlFor="rename-title-input" className="dialog-field-label">
            Conversation title
          </label>
          <input
            id="rename-title-input"
            type="text"
            className="dialog-text-input"
            value={titleInput}
            maxLength={MAX_TITLE_LENGTH}
            onChange={(e) => {
              setTitleInput(e.target.value)
              if (localError) setLocalError('')
            }}
            autoFocus
            disabled={isSaving}
          />
          <div className="dialog-meta-row">
            <span>
              {titleInput.trim().length} / {MAX_TITLE_LENGTH}
            </span>
          </div>
          {displayError && (
            <p className="dialog-error-text" role="alert">
              {displayError}
            </p>
          )}
          <div className="modal-actions-row">
            <button
              type="button"
              className="dialog-btn-secondary"
              onClick={onCancel}
              disabled={isSaving}
            >
              Cancel
            </button>
            <button
              type="submit"
              className="dialog-btn-primary"
              disabled={isSaving}
            >
              {isSaving ? 'Saving...' : 'Save Title'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

export default RenameConversationDialog
