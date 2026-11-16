import { useState } from 'react'
import { Upload, X } from 'lucide-react'

function DocumentUploadModal({ documentTypes, isUploading, errorMessage, onUpload, onClose }) {
  const [title, setTitle] = useState('')
  const [docType, setDocType] = useState(documentTypes[0] || 'University Prospectus')
  const [customType, setCustomType] = useState('')
  const [academicYear, setAcademicYear] = useState('2026-27')
  const [department, setDepartment] = useState('')
  const [description, setDescription] = useState('')
  const [effectiveDate, setEffectiveDate] = useState('')
  const [expiryDate, setExpiryDate] = useState('')
  const [selectedFile, setSelectedFile] = useState(null)
  const [localError, setLocalError] = useState('')

  const handleSubmit = (e) => {
    e.preventDefault()
    const resolvedType = docType === '__custom__' ? customType.trim() : docType
    if (!title.trim()) {
      setLocalError('Document title is required.')
      return
    }
    if (!resolvedType) {
      setLocalError('Document type is required.')
      return
    }
    if (!academicYear.trim()) {
      setLocalError('Academic year is required.')
      return
    }
    if (!selectedFile) {
      setLocalError('Please select a PDF, DOCX, or TXT file to upload.')
      return
    }
    setLocalError('')

    const formData = new FormData()
    formData.append('file', selectedFile)
    formData.append('title', title.trim())
    formData.append('doc_type', resolvedType)
    formData.append('academic_year', academicYear.trim())
    if (department.trim()) formData.append('department', department.trim())
    if (description.trim()) formData.append('description', description.trim())
    if (effectiveDate) formData.append('effective_date', effectiveDate)
    if (expiryDate) formData.append('expiry_date', expiryDate)

    onUpload(formData)
  }

  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" onClick={onClose}>
      <div className="modal-card admin-editor-modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <div className="modal-title-group">
            <Upload size={18} />
            <h2>Upload Official University Document</h2>
          </div>
          <button type="button" className="modal-close-btn" onClick={onClose} aria-label="Close">
            <X size={18} />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="modal-body admin-editor-form">
          <div className="admin-form-group">
            <label className="dialog-field-label" htmlFor="doc-title-input">Document Title *</label>
            <input
              id="doc-title-input"
              type="text"
              className="dialog-text-input"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="e.g., Academic Regulations 2026-27"
              disabled={isUploading}
            />
          </div>

          <div className="admin-two-col">
            <div className="admin-form-group">
              <label className="dialog-field-label" htmlFor="doc-type-select">Document Type *</label>
              <select
                id="doc-type-select"
                className="dialog-text-input"
                value={docType}
                onChange={(e) => setDocType(e.target.value)}
                disabled={isUploading}
              >
                {documentTypes.map((t) => (
                  <option key={t} value={t}>{t}</option>
                ))}
                <option value="__custom__">+ Custom Type...</option>
              </select>
            </div>

            <div className="admin-form-group">
              <label className="dialog-field-label" htmlFor="doc-year-input">Academic Year *</label>
              <input
                id="doc-year-input"
                type="text"
                className="dialog-text-input"
                value={academicYear}
                onChange={(e) => setAcademicYear(e.target.value)}
                placeholder="e.g., 2026-27"
                disabled={isUploading}
              />
            </div>
          </div>

          {docType === '__custom__' && (
            <div className="admin-form-group">
              <label className="dialog-field-label" htmlFor="doc-custom-type">Custom Document Type *</label>
              <input
                id="doc-custom-type"
                type="text"
                className="dialog-text-input"
                value={customType}
                onChange={(e) => setCustomType(e.target.value)}
                placeholder="Enter custom document type"
                disabled={isUploading}
              />
            </div>
          )}

          <div className="admin-form-group">
            <label className="dialog-field-label" htmlFor="doc-dept-input">Department / Programme (optional)</label>
            <input
              id="doc-dept-input"
              type="text"
              className="dialog-text-input"
              value={department}
              onChange={(e) => setDepartment(e.target.value)}
              placeholder="e.g., School of Engineering / All Programmes"
              disabled={isUploading}
            />
          </div>

          <div className="admin-two-col">
            <div className="admin-form-group">
              <label className="dialog-field-label" htmlFor="doc-eff-date">Effective Date (optional)</label>
              <input
                id="doc-eff-date"
                type="date"
                className="dialog-text-input"
                value={effectiveDate}
                onChange={(e) => setEffectiveDate(e.target.value)}
                disabled={isUploading}
              />
            </div>
            <div className="admin-form-group">
              <label className="dialog-field-label" htmlFor="doc-exp-date">Expiry / Review Date (optional)</label>
              <input
                id="doc-exp-date"
                type="date"
                className="dialog-text-input"
                value={expiryDate}
                onChange={(e) => setExpiryDate(e.target.value)}
                disabled={isUploading}
              />
            </div>
          </div>

          <div className="admin-form-group">
            <label className="dialog-field-label" htmlFor="doc-desc-input">Description (optional)</label>
            <textarea
              id="doc-desc-input"
              rows={2}
              className="dialog-text-input admin-textarea"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Brief summary of the document scope..."
              disabled={isUploading}
            />
          </div>

          <div className="admin-form-group">
            <label className="dialog-field-label" htmlFor="doc-file-input">
              Document File (.pdf, .docx, .txt) *
            </label>
            <input
              id="doc-file-input"
              type="file"
              accept=".pdf,.docx,.txt"
              onChange={(e) => setSelectedFile(e.target.files?.[0] || null)}
              disabled={isUploading}
            />
          </div>

          {(localError || errorMessage) && (
            <p className="dialog-error-text" role="alert">
              {localError || errorMessage}
            </p>
          )}

          <div className="modal-actions-row">
            <button type="button" className="dialog-btn-secondary" onClick={onClose} disabled={isUploading}>
              Cancel
            </button>
            <button type="submit" className="dialog-btn-primary" disabled={isUploading}>
              {isUploading ? 'Uploading & Extracting...' : 'Upload Document'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

export default DocumentUploadModal
