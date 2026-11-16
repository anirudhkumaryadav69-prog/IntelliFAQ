import { CheckCircle, XCircle, Archive, RefreshCw, Trash2, X } from 'lucide-react'

function DocumentReviewModal({
  previewData,
  isBusy,
  errorMessage,
  onApprove,
  onReject,
  onArchive,
  onReprocess,
  onDelete,
  onClose,
}) {
  if (!previewData?.document) return null
  const doc = previewData.document
  const chunks = previewData.chunks || []

  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" onClick={onClose}>
      <div className="modal-card admin-review-modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <div className="modal-title-group">
            <h2>Review Document #{doc.document_id}</h2>
          </div>
          <button type="button" className="modal-close-btn" onClick={onClose} aria-label="Close">
            <X size={18} />
          </button>
        </div>

        <div className="modal-body admin-editor-form">
          <div className="admin-preview-grid">
            <div>
              <span className="admin-stat-label">Title</span>
              <strong>{doc.title}</strong>
            </div>
            <div>
              <span className="admin-stat-label">Type &amp; Academic Year</span>
              <p>{doc.doc_type} • {doc.academic_year}</p>
            </div>
            <div>
              <span className="admin-stat-label">Processing Status</span>
              <p><span className="admin-cat-badge">{doc.processing_status}</span></p>
            </div>
            <div>
              <span className="admin-stat-label">Approval Status</span>
              <p><span className="admin-cat-badge">{doc.approval_status}</span></p>
            </div>
            <div>
              <span className="admin-stat-label">Pages / Chunks</span>
              <p>{doc.page_count != null ? `${doc.page_count} pages` : 'N/A'} • {doc.chunk_count} chunks</p>
            </div>
            <div>
              <span className="admin-stat-label">Uploaded By</span>
              <p>{doc.uploaded_by} ({new Date(doc.created_at).toLocaleDateString()})</p>
            </div>
            <div>
              <span className="admin-stat-label">Original Filename</span>
              <p>{doc.original_filename} (v{doc.version})</p>
            </div>
            <div>
              <span className="admin-stat-label">SHA-256 Fingerprint</span>
              <p><code className="admin-hash-code">{doc.sha256_hash}</code></p>
            </div>
          </div>

          {doc.error_message && (
            <div className="doc-warning-box" role="alert">
              <strong>Extraction Notice:</strong> {doc.error_message}
            </div>
          )}

          {doc.extracted_preview && (
            <div>
              <span className="admin-stat-label">Extracted Text Preview</span>
              <div className="admin-preview-answer-box admin-doc-preview-box">
                {doc.extracted_preview}
              </div>
            </div>
          )}

          {chunks.length > 0 && (
            <div>
              <span className="admin-stat-label">Extracted Chunks (showing {chunks.length})</span>
              <div className="admin-chunks-list">
                {chunks.slice(0, 6).map((ch) => (
                  <div key={ch.chunk_id} className="admin-chunk-item">
                    <small>
                      Chunk #{ch.chunk_index + 1}
                      {ch.page_number != null ? ` • Page ${ch.page_number}` : ''}
                      {ch.section_heading ? ` • ${ch.section_heading}` : ''}
                      {ch.paragraph_ref ? ` • ${ch.paragraph_ref}` : ''}
                    </small>
                    <p>{ch.chunk_text}</p>
                  </div>
                ))}
              </div>
            </div>
          )}

          {errorMessage && (
            <p className="dialog-error-text" role="alert">{errorMessage}</p>
          )}

          <div className="admin-review-actions">
            <button
              type="button"
              className="dialog-btn-primary admin-small-btn"
              disabled={isBusy || doc.processing_status !== 'processed' || doc.approval_status === 'approved'}
              onClick={() => onApprove(doc.document_id)}
            >
              <CheckCircle size={14} /> Approve
            </button>
            <button
              type="button"
              className="dialog-btn-secondary admin-small-btn"
              disabled={isBusy || doc.approval_status === 'rejected'}
              onClick={() => onReject(doc.document_id)}
            >
              <XCircle size={14} /> Reject
            </button>
            <button
              type="button"
              className="dialog-btn-secondary admin-small-btn"
              disabled={isBusy || doc.processing_status === 'archived'}
              onClick={() => onArchive(doc.document_id)}
            >
              <Archive size={14} /> Archive
            </button>
            <button
              type="button"
              className="dialog-btn-secondary admin-small-btn"
              disabled={isBusy}
              onClick={() => onReprocess(doc.document_id)}
            >
              <RefreshCw size={14} /> Reprocess
            </button>
            <button
              type="button"
              className="dialog-btn-danger admin-small-btn"
              disabled={isBusy}
              onClick={() => onDelete(doc)}
            >
              <Trash2 size={14} /> Delete
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

export default DocumentReviewModal
