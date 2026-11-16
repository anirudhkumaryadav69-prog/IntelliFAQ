/**
 * IntelliFAQ 2.0 Admin REST API Client
 *
 * Uses HttpOnly cookie sessions (`credentials: 'include'`) and attaches the
 * session's `X-CSRF-Token` header on all state-changing requests.
 */

import { API_BASE_URL } from './api'

let currentCsrfToken = null
const authExpiredListeners = new Set()

export function setAdminCsrfToken(token) {
  currentCsrfToken = typeof token === 'string' && token ? token : null
}

export function onAdminAuthExpired(listener) {
  authExpiredListeners.add(listener)
  return () => authExpiredListeners.delete(listener)
}

function notifyAuthExpired() {
  setAdminCsrfToken(null)
  for (const listener of authExpiredListeners) {
    listener()
  }
}

async function parseJson(response) {
  const text = await response.text()
  if (!text || !text.trim()) return null
  try {
    return JSON.parse(text)
  } catch {
    return null
  }
}

async function adminRequest(path, options = {}) {
  const method = (options.method || 'GET').toUpperCase()
  const isFormData =
    typeof FormData !== 'undefined' && options.body instanceof FormData
  const headers = {
    Accept: 'application/json',
    ...(!isFormData && options.body ? { 'Content-Type': 'application/json' } : {}),
    ...(options.headers || {}),
  }

  if (['POST', 'PATCH', 'DELETE', 'PUT'].includes(method) && currentCsrfToken) {
    headers['X-CSRF-Token'] = currentCsrfToken
  }

  try {
    const response = await fetch(`${API_BASE_URL}${path}`, {
      method,
      credentials: 'include',
      headers,
      body: options.body
        ? isFormData
          ? options.body
          : JSON.stringify(options.body)
        : undefined,
    })
    const data = await parseJson(response)
    if (data && typeof data.csrf_token === 'string') {
      setAdminCsrfToken(data.csrf_token)
    }
    if (
      response.status === 401 &&
      path !== '/api/admin/login' &&
      path !== '/api/admin/me'
    ) {
      notifyAuthExpired()
    }
    return {
      ok: response.ok && Boolean(data?.success),
      status: response.status,
      data: data || {},
      error: data?.error || (!response.ok ? `Request failed (${response.status})` : null),
    }
  } catch {
    return {
      ok: false,
      status: 0,
      data: {},
      connectionError: true,
      error: 'Unable to connect to the IntelliFAQ backend server.',
    }
  }
}

export async function adminLogin(username, password) {
  const res = await adminRequest('/api/admin/login', {
    method: 'POST',
    body: { username, password },
  })
  if (res.ok && res.data.csrf_token) {
    setAdminCsrfToken(res.data.csrf_token)
  }
  return res
}

export async function adminLogout() {
  const res = await adminRequest('/api/admin/logout', { method: 'POST' })
  setAdminCsrfToken(null)
  return res
}

export async function fetchAdminMe() {
  const res = await adminRequest('/api/admin/me')
  if (!res.ok) {
    setAdminCsrfToken(null)
  }
  return res
}

export function fetchAdminDashboard() {
  return adminRequest('/api/admin/dashboard')
}

export function fetchAdminFaqs(search = '', categoryId = '') {
  const params = new URLSearchParams()
  if (search.trim()) params.set('q', search.trim())
  if (categoryId !== '' && categoryId != null) params.set('category_id', String(categoryId))
  const qs = params.toString()
  return adminRequest(`/api/admin/faqs${qs ? `?${qs}` : ''}`)
}

export function fetchAdminFaqDetail(faqId) {
  return adminRequest(`/api/admin/faqs/${faqId}`)
}

export function createAdminFaq(payload) {
  return adminRequest('/api/admin/faqs', { method: 'POST', body: payload })
}

export function updateAdminFaq(faqId, payload) {
  return adminRequest(`/api/admin/faqs/${faqId}`, { method: 'PATCH', body: payload })
}

export function deleteAdminFaq(faqId) {
  return adminRequest(`/api/admin/faqs/${faqId}`, { method: 'DELETE' })
}

export function fetchAdminCategories() {
  return adminRequest('/api/admin/categories')
}

export function createAdminCategory(name) {
  return adminRequest('/api/admin/categories', { method: 'POST', body: { name } })
}

export function renameAdminCategory(categoryId, name) {
  return adminRequest(`/api/admin/categories/${categoryId}`, {
    method: 'PATCH',
    body: { name },
  })
}

export function deleteAdminCategory(categoryId, reassignToCategoryId = null) {
  const body =
    reassignToCategoryId != null
      ? { reassign_to_category_id: Number(reassignToCategoryId) }
      : {}
  return adminRequest(`/api/admin/categories/${categoryId}`, {
    method: 'DELETE',
    body,
  })
}

export function testChatbotPreview(question) {
  return adminRequest('/api/admin/test-chatbot', {
    method: 'POST',
    body: { question },
  })
}

export function fetchUnansweredQuestions(search = '', status = '') {
  const params = new URLSearchParams()
  if (search.trim()) params.set('q', search.trim())
  if (status.trim()) params.set('status', status.trim())
  const qs = params.toString()
  return adminRequest(`/api/admin/unanswered${qs ? `?${qs}` : ''}`)
}

export function updateUnansweredQuestion(itemId, payload) {
  return adminRequest(`/api/admin/unanswered/${itemId}`, {
    method: 'PATCH',
    body: payload,
  })
}

export function fetchDocumentAnalytics() {
  return adminRequest('/api/admin/documents/analytics')
}

export function fetchAdminDocuments(filters = {}) {
  const params = new URLSearchParams()
  for (const [k, v] of Object.entries(filters)) {
    if (v !== '' && v != null) params.set(k, String(v))
  }
  const qs = params.toString()
  return adminRequest(`/api/admin/documents${qs ? `?${qs}` : ''}`)
}

export function uploadAdminDocument(formData) {
  return adminRequest('/api/admin/documents', {
    method: 'POST',
    body: formData,
  })
}

export function fetchDocumentPreview(documentId) {
  return adminRequest(`/api/admin/documents/${documentId}/preview`)
}

export function approveAdminDocument(documentId) {
  return adminRequest(`/api/admin/documents/${documentId}/approve`, {
    method: 'POST',
  })
}

export function rejectAdminDocument(documentId, reason = '') {
  return adminRequest(`/api/admin/documents/${documentId}/reject`, {
    method: 'POST',
    body: { reason },
  })
}

export function archiveAdminDocument(documentId) {
  return adminRequest(`/api/admin/documents/${documentId}/archive`, {
    method: 'POST',
  })
}

export function reprocessAdminDocument(documentId) {
  return adminRequest(`/api/admin/documents/${documentId}/reprocess`, {
    method: 'POST',
  })
}

export function deleteAdminDocument(documentId) {
  return adminRequest(`/api/admin/documents/${documentId}`, {
    method: 'DELETE',
  })
}
