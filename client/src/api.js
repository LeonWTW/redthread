// Tiny fetch wrapper. Throws on !ok with the server's error message.
// Errors carry .status so callers can redirect to /login on 401.

export class ApiError extends Error {
  constructor(message, status) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

export async function api(path, options = {}) {
  const res = await fetch(path, { credentials: 'same-origin', ...options })
  if (!res.ok) {
    let message = `Request failed (${res.status})`
    try {
      const body = await res.json()
      if (body && (body.error || body.message)) message = body.error || body.message
    } catch {
      // Non-JSON error body; keep the generic message.
    }
    throw new ApiError(message, res.status)
  }
  if (res.status === 204) return null
  return res.json()
}

export function postJson(path, body) {
  return api(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
}

export function postForm(path, formData) {
  // No Content-Type header: the browser sets the multipart boundary.
  return api(path, { method: 'POST', body: formData })
}
