import { useState } from 'react'
import { FlaskConical, Send } from 'lucide-react'
import { testChatbotPreview } from '../../services/adminApi'

function FAQPreview() {
  const [question, setQuestion] = useState('')
  const [isTesting, setIsTesting] = useState(false)
  const [preview, setPreview] = useState(null)
  const [error, setError] = useState('')

  const handleRunTest = async (e) => {
    e.preventDefault()
    if (!question.trim()) {
      setError('Please enter a test question.')
      return
    }
    setIsTesting(true)
    setError('')
    const res = await testChatbotPreview(question.trim())
    setIsTesting(false)
    if (!res.ok) {
      setError(res.error || 'Preview request failed.')
      return
    }
    setPreview(res.data.preview)
  }

  return (
    <div className="admin-page">
      <div className="admin-page-header">
        <div>
          <h1>FAQ Preview &amp; Chatbot Testing</h1>
          <p>
            Test queries against the live TF-IDF index without affecting student
            conversations or unanswered-question logs.
          </p>
        </div>
      </div>

      <form onSubmit={handleRunTest} className="admin-toolbar">
        <input
          type="text"
          className="dialog-text-input"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="Enter a test student question..."
          disabled={isTesting}
        />
        <button type="submit" className="dialog-btn-primary admin-add-btn" disabled={isTesting}>
          <Send size={15} />
          <span>{isTesting ? 'Testing...' : 'Test Query'}</span>
        </button>
      </form>

      {error && <p className="dialog-error-text">{error}</p>}

      {preview && (
        <div className="admin-card admin-preview-card">
          <div className="admin-preview-grid">
            <div>
              <span className="admin-stat-label">Original Question</span>
              <p>{preview.original_question}</p>
            </div>
            <div>
              <span className="admin-stat-label">Normalized Query</span>
              <p><code>{preview.normalized_query || '(empty after preprocessing)'}</code></p>
            </div>
            <div>
              <span className="admin-stat-label">Match Classification</span>
              <p><span className="admin-cat-badge">{preview.match_type}</span></p>
            </div>
            <div>
              <span className="admin-stat-label">TF-IDF Cosine Similarity (not a probability)</span>
              <p><strong>{Number(preview.similarity_score || 0).toFixed(2)}%</strong></p>
            </div>
            <div>
              <span className="admin-stat-label">Matched FAQ</span>
              <p>
                {preview.faq_id != null
                  ? `#${preview.faq_id} — ${preview.matched_question}`
                  : 'None'}
              </p>
            </div>
            <div>
              <span className="admin-stat-label">Matched Category</span>
              <p>{preview.category || 'None'}</p>
            </div>
          </div>

          <div className="admin-preview-answer">
            <span className="admin-stat-label">Returned Answer</span>
            <div className="admin-preview-answer-box">{preview.answer}</div>
          </div>

          {Array.isArray(preview.candidates) && preview.candidates.length > 0 && (
            <div className="admin-preview-candidates">
              <span className="admin-stat-label">Top Candidate FAQs (Cosine Similarity)</span>
              <ul className="admin-mini-list">
                {preview.candidates.map((c) => (
                  <li key={c.faq_id}>
                    <span className="admin-mini-id">#{c.faq_id}</span>
                    <div>
                      <p>{c.question}</p>
                      <small>{c.category} • Cosine similarity: {Number(c.similarity).toFixed(2)}%</small>
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}

      {!preview && !error && (
        <div className="admin-panel-state">
          <FlaskConical size={22} />
          <p>Run a test query to inspect TF-IDF normalization, candidates, and response output.</p>
        </div>
      )}
    </div>
  )
}

export default FAQPreview
