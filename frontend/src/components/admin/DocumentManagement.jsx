import { useCallback, useEffect, useState } from 'react'
import { Upload, Search, Eye } from 'lucide-react'
import {
  fetchAdminDocuments,
  fetchDocumentAnalytics,
  uploadAdminDocument,
  fetchDocumentPreview,
  approveAdminDocument,
  rejectAdminDocument,
  archiveAdminDocument,
  reprocessAdminDocument,
  deleteAdminDocument,
} from '../../services/adminApi'
import DocumentUploadModal from './DocumentUploadModal'
import DocumentReviewModal from './DocumentReviewModal'

function DocumentManagement() {
  const [documents, setDocuments] = useState([])
  const [analytics, setAnalytics] = useState(null)
  const [search, setSearch] = useState('')
  const [docTypeFilter, setDocTypeFilter] = useState('')
  const [procFilter, setProcFilter] = useState('')
  const [approvalFilter, setApprovalFilter] = useState('')
  const [page, setPage] = useState(1)
  const [totalCount, setTotalCount] = useState(0)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState('')

  const [isUploadOpen, setIsUploadOpen] = useState(false)
  const [isUploading, setIsUploading] = useState(false)
  const [uploadError, setUploadError] = useState('')

  const [reviewData, setReviewData] = useState(null)
  const [isReviewBusy, setIsReviewBusy] = useState(false)
  const [reviewError, setReviewError] = useState('')
  const [deleteTarget, setDeleteTarget] = useState(null)

  const loadDocuments = useCallback(
    async (overrides = {}) => {
      setIsLoading(true)
      setError('')
      const filters = {
        q: overrides.q ?? search,
        doc_type: overrides.doc_type ?? docTypeFilter,
        processing_status: overrides.processing_status ?? procFilter,
        approval_status: overrides.approval_status ?? approvalFilter,
        page: overrides.page ?? page,
        per_page: 20,
      }
      const [docsRes, anaRes] = await Promise.all([
        fetchAdminDocuments(filters),
        fetchDocumentAnalytics(),
      ])
      setIsLoading(false)
      if (!docsRes.ok) {
        setError(docsRes.error || 'Failed to load documents.')
        return
      }
      setDocuments(docsRes.data.documents || [])
      setTotalCount(docsRes.data.total_count || 0)
      if (anaRes.ok) {
        setAnalytics(anaRes.data.analytics)
      }
    },
    [search, docTypeFilter, procFilter, approvalFilter, page]
  )

  useEffect(() => {
    let active = true
    Promise.all([
      fetchAdminDocuments({ page: 1, per_page: 20 }),
      fetchDocumentAnalytics(),
    ]).then(([docsRes, anaRes]) => {
      if (!active) return
      setIsLoading(false)
      if (!docsRes.ok) {
        setError(docsRes.error || 'Failed to load documents.')
        return
      }
      setDocuments(docsRes.data.documents || [])
      setTotalCount(docsRes.data.total_count || 0)
      if (anaRes.ok) {
        setAnalytics(anaRes.data.analytics)
      }
    })
    return () => {
      active = false
    }
  }, [])

  const handleUpload = async (formData) => {
    setIsUploading(true)
    setUploadError('')
    const res = await uploadAdminDocument(formData)
    setIsUploading(false)
    if (!res.ok) {
      setUploadError(res.error || 'Upload failed.')
      return
    }
    setIsUploadOpen(false)
    loadDocuments({ page: 1 })
  }

  const openReview = async (docId) => {
    setReviewError('')
    const res = await fetchDocumentPreview(docId)
    if (!res.ok) {
      setError(res.error || 'Failed to load document preview.')
      return
    }
    setReviewData(res.data)
  }

  const runAction = async (fn, docId) => {
    setIsReviewBusy(true)
    setReviewError('')
    const res = await fn(docId)
    setIsReviewBusy(false)
    if (!res.ok) {
      setReviewError(res.error || 'Operation failed.')
      return
    }
    await openReview(docId)
    loadDocuments()
  }

  const handleConfirmDelete = async () => {
    if (!deleteTarget) return
    setIsReviewBusy(true)
    const res = await deleteAdminDocument(deleteTarget.document_id)
    setIsReviewBusy(false)
    if (!res.ok) {
      setReviewError(res.error || 'Delete failed.')
      setDeleteTarget(null)
      return
    }
    setDeleteTarget(null)
    setReviewData(null)
    loadDocuments()
  }

  const docTypes = analytics?.document_types || [
    'University Prospectus',
    'Admission Guidelines',
    'Academic Regulations',
    'Examination Regulations',
    'Fee Structure',
    'Scholarship Guidelines',
    'Attendance Policy',
    'Hostel and Campus Guidelines',
    'Placement Guidelines',
    'Official Notices',
    'Other',
  ]

  return (
    <div className="admin-page">
      <div className="admin-page-header">
        <div>
          <h1>Document Knowledge Base</h1>
          <p>
            Upload, extract, review, and approve official university documents
            for grounded student retrieval.
          </p>
        </div>
        <button
          type="button"
          className="dialog-btn-primary admin-add-btn"
          onClick={() => {
            setUploadError('')
            setIsUploadOpen(true)
          }}
        >
          <Upload size={16} />
          <span>Upload Document</span>
        </button>
      </div>

      {analytics && (
        <div className="admin-stats-grid">
          <div className="admin-stat-card">
            <div>
              <span className="admin-stat-label">Total Documents</span>
              <strong className="admin-stat-value">{analytics.total_documents}</strong>
            </div>
          </div>
          <div className="admin-stat-card">
            <div>
              <span className="admin-stat-label">Approved &amp; Active</span>
              <strong className="admin-stat-value">{analytics.approved_documents}</strong>
            </div>
          </div>
          <div className="admin-stat-card">
            <div>
              <span className="admin-stat-label">Pending Review</span>
              <strong className="admin-stat-value">{analytics.pending_review}</strong>
            </div>
          </div>
          <div className="admin-stat-card">
            <div>
              <span className="admin-stat-label">Indexed Chunks</span>
              <strong className="admin-stat-value">{analytics.total_indexed_chunks}</strong>
            </div>
          </div>
        </div>
      )}

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
              setPage(1)
              loadDocuments({ q: val, page: 1 })
            }}
            placeholder="Search by title, department, or filename..."
          />
        </div>

        <select
          className="dialog-text-input admin-filter-select"
          value={docTypeFilter}
          onChange={(e) => {
            const val = e.target.value
            setDocTypeFilter(val)
            setPage(1)
            loadDocuments({ doc_type: val, page: 1 })
          }}
        >
          <option value="">All Types</option>
          {docTypes.map((t) => (
            <option key={t} value={t}>{t}</option>
          ))}
        </select>

        <select
          className="dialog-text-input admin-filter-select"
          value={procFilter}
          onChange={(e) => {
            const val = e.target.value
            setProcFilter(val)
            setPage(1)
            loadDocuments({ processing_status: val, page: 1 })
          }}
        >
          <option value="">All Processing</option>
          <option value="processed">Processed</option>
          <option value="OCR_REQUIRED">OCR Required</option>
          <option value="failed">Failed</option>
          <option value="archived">Archived</option>
        </select>

        <select
          className="dialog-text-input admin-filter-select"
          value={approvalFilter}
          onChange={(e) => {
            const val = e.target.value
            setApprovalFilter(val)
            setPage(1)
            loadDocuments({ approval_status: val, page: 1 })
          }}
        >
          <option value="">All Approvals</option>
          <option value="pending_review">Pending Review</option>
          <option value="approved">Approved</option>
          <option value="rejected">Rejected</option>
        </select>
      </div>

      {error && <p className="dialog-error-text">{error}</p>}

      {isLoading ? (
        <div className="admin-panel-state">Loading documents...</div>
      ) : documents.length === 0 ? (
        <div className="admin-panel-state">
          No official documents uploaded yet. Upload a PDF, DOCX, or TXT file to begin.
        </div>
      ) : (
        <div className="admin-table-wrap">
          <table className="admin-table">
            <thead>
              <tr>
                <th>Title</th>
                <th>Type</th>
                <th>Year</th>
                <th>Processing</th>
                <th>Approval</th>
                <th>Uploaded</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {documents.map((doc) => (
                <tr key={doc.document_id}>
                  <td className="admin-table-question">
                    <strong>{doc.title}</strong>
                    <div className="admin-muted">{doc.original_filename} • {doc.chunk_count} chunks</div>
                  </td>
                  <td><span className="admin-cat-badge">{doc.doc_type}</span></td>
                  <td>{doc.academic_year}</td>
                  <td><span className="admin-cat-badge">{doc.processing_status}</span></td>
                  <td><span className="admin-cat-badge">{doc.approval_status}</span></td>
                  <td>{new Date(doc.created_at).toLocaleDateString()}</td>
                  <td>
                    <button
                      type="button"
                      className="dialog-btn-secondary admin-small-btn"
                      onClick={() => openReview(doc.document_id)}
                    >
                      <Eye size={14} /> Review
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {totalCount > 20 && (
        <div className="modal-actions-row">
          <button
            type="button"
            className="dialog-btn-secondary"
            disabled={page <= 1}
            onClick={() => {
              const prev = page - 1
              setPage(prev)
              loadDocuments({ page: prev })
            }}
          >
            Previous
          </button>
          <span className="admin-muted">Page {page}</span>
          <button
            type="button"
            className="dialog-btn-secondary"
            disabled={page * 20 >= totalCount}
            onClick={() => {
              const next = page + 1
              setPage(next)
              loadDocuments({ page: next })
            }}
          >
            Next
          </button>
        </div>
      )}

      {isUploadOpen && (
        <DocumentUploadModal
          documentTypes={docTypes}
          isUploading={isUploading}
          errorMessage={uploadError}
          onUpload={handleUpload}
          onClose={() => setIsUploadOpen(false)}
        />
      )}

      {reviewData && (
        <DocumentReviewModal
          previewData={reviewData}
          isBusy={isReviewBusy}
          errorMessage={reviewError}
          onApprove={(id) => runAction(approveAdminDocument, id)}
          onReject={(id) => runAction((docId) => rejectAdminDocument(docId, ''), id)}
          onArchive={(id) => runAction(archiveAdminDocument, id)}
          onReprocess={(id) => runAction(reprocessAdminDocument, id)}
          onDelete={(doc) => setDeleteTarget(doc)}
          onClose={() => setReviewData(null)}
        />
      )}

      {deleteTarget && (
        <div className="modal-backdrop" role="dialog" aria-modal="true" onClick={() => setDeleteTarget(null)}>
          <div className="modal-card modal-card-compact" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h2>Delete Document #{deleteTarget.document_id}</h2>
            </div>
            <div className="modal-body">
              <p className="modal-lead">
                Permanently delete <strong>“{deleteTarget.title}”</strong> and all of its extracted chunks?
              </p>
              <div className="modal-actions-row">
                <button type="button" className="dialog-btn-secondary" onClick={() => setDeleteTarget(null)}>
                  Cancel
                </button>
                <button type="button" className="dialog-btn-danger" onClick={handleConfirmDelete} disabled={isReviewBusy}>
                  Delete Document
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default DocumentManagement
