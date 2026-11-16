import { useState } from 'react'
import { Shield, Lock, User, ArrowLeft, LogIn } from 'lucide-react'
import { adminLogin, fetchAdminMe } from '../../services/adminApi'

function AdminLogin({ onLoginSuccess, onExitAdmin }) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [errorMessage, setErrorMessage] = useState('')

  const handleSubmit = async (e) => {
    e.preventDefault()
    if (!username.trim() || !password) {
      setErrorMessage('Please enter both username and password.')
      return
    }
    setIsSubmitting(true)
    setErrorMessage('')
    const res = await adminLogin(username.trim(), password)

    if (!res.ok) {
      setIsSubmitting(false)
      setErrorMessage(res.error || 'Authentication failed.')
      return
    }

    // Confirm the backend recognizes the HttpOnly session cookie via /api/admin/me
    const meRes = await fetchAdminMe()
    setIsSubmitting(false)
    if (!meRes.ok || !meRes.data?.admin) {
      setErrorMessage(
        'Session cookie could not be verified by the backend. Please ensure cookies are enabled.'
      )
      return
    }

    setPassword('')
    onLoginSuccess(meRes.data.admin)
  }

  return (
    <div className="admin-login-page">
      <div className="admin-login-card">
        <div className="admin-login-header">
          <div className="admin-brand-badge">
            <Shield size={24} strokeWidth={2} />
          </div>
          <h1>IntelliFAQ Admin Portal</h1>
          <p>Sign in to manage the university FAQ knowledge base.</p>
        </div>

        <form onSubmit={handleSubmit} className="admin-login-form">
          <div className="admin-form-group">
            <label htmlFor="admin-username" className="dialog-field-label">
              Administrator Username
            </label>
            <div className="admin-input-wrap">
              <User size={16} className="admin-input-icon" />
              <input
                id="admin-username"
                type="text"
                className="admin-input"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                autoComplete="username"
                placeholder="Enter username"
                disabled={isSubmitting}
              />
            </div>
          </div>

          <div className="admin-form-group">
            <label htmlFor="admin-password" className="dialog-field-label">
              Password
            </label>
            <div className="admin-input-wrap">
              <Lock size={16} className="admin-input-icon" />
              <input
                id="admin-password"
                type="password"
                className="admin-input"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="current-password"
                placeholder="Enter password"
                disabled={isSubmitting}
              />
            </div>
          </div>

          {errorMessage && (
            <p className="dialog-error-text" role="alert">
              {errorMessage}
            </p>
          )}

          <button
            type="submit"
            className="admin-submit-btn"
            disabled={isSubmitting}
          >
            <LogIn size={16} />
            <span>{isSubmitting ? 'Signing in...' : 'Sign In'}</span>
          </button>
        </form>

        <div className="admin-login-footer">
          <button
            type="button"
            className="admin-back-link"
            onClick={onExitAdmin}
          >
            <ArrowLeft size={14} />
            <span>Return to Student Chatbot</span>
          </button>
        </div>
      </div>
    </div>
  )
}

export default AdminLogin
