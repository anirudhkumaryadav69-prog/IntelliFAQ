import { Trash2, X } from 'lucide-react'

function DeleteConversationDialog({
  conversation,
  isDeleting,
  errorMessage,
  onConfirm,
  onCancel,
}) {
  if (!conversation) return null

  return (
    <div
      className="modal-backdrop"
      role="dialog"
      aria-modal="true"
      aria-labelledby="delete-dialog-title"
      onClick={onCancel}
    >
      <div
        className="modal-card modal-card-compact"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal-header">
          <div className="modal-title-group">
            <Trash2 size={18} strokeWidth={2} />
            <h2 id="delete-dialog-title">Delete Conversation</h2>
          </div>
          <button
            type="button"
            className="modal-close-btn"
            onClick={onCancel}
            aria-label="Close delete dialog"
          >
            <X size={18} strokeWidth={2} />
          </button>
        </div>

        <div className="modal-body">
          <p className="modal-lead">
            Are you sure you want to permanently delete{' '}
            <strong>“{conversation.title}”</strong>? This will remove all
            messages and saved context for this conversation.
          </p>

          {errorMessage && (
            <p className="dialog-error-text" role="alert">
              {errorMessage}
            </p>
          )}

          <div className="modal-actions-row">
            <button
              type="button"
              className="dialog-btn-secondary"
              onClick={onCancel}
              disabled={isDeleting}
            >
              Cancel
            </button>
            <button
              type="button"
              className="dialog-btn-danger"
              onClick={() => onConfirm(conversation)}
              disabled={isDeleting}
            >
              {isDeleting ? 'Deleting...' : 'Delete Conversation'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

export default DeleteConversationDialog
