import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../api.js'

const STEPS = ['ocr', 'translate', 'extract', 'embed']
const ACTIVE = ['pending', 'running']
const PAGE_SIZE = 50
const MAX_LIMIT = 200
const POLL_MS = 5000

function hasActiveStep(post) {
  return STEPS.some((step) => ACTIVE.includes(post[`${step}_status`]))
}

function formatCapturedAt(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function StatusCell({ post, step, onRetry }) {
  const status = post[`${step}_status`] || 'pending'
  if (status !== 'failed') {
    return (
      <td>
        <span className={`badge badge-${status}`}>{status}</span>
      </td>
    )
  }
  const errorType = post[`${step}_error_type`]
  const errorMessage = post[`${step}_error_message`]
  const tooltip = [errorType, errorMessage].filter(Boolean).join(': ') || 'failed'
  return (
    <td>
      <span className="badge badge-failed" title={tooltip}>
        failed
      </span>
      <button type="button" className="retry-btn" onClick={() => onRetry(post.id, step)}>
        Retry
      </button>
      <details className="err-line">
        <summary>{errorType || 'error'}</summary>
        <div>{errorMessage || '(no message)'}</div>
        {errorType === 'config_error' && (
          <div className="hint">configuration problem — fix .env and retry</div>
        )}
      </details>
    </td>
  )
}

export default function Inbox() {
  const navigate = useNavigate()
  const [posts, setPosts] = useState(null) // null = first load in flight
  const [total, setTotal] = useState(0)
  const [error, setError] = useState('')
  const [loadingMore, setLoadingMore] = useState(false)
  const countRef = useRef(0)

  useEffect(() => {
    countRef.current = posts ? posts.length : 0
  }, [posts])

  const handleError = useCallback(
    (err) => {
      if (err.status === 401) {
        navigate('/login')
        return
      }
      setError(err.message)
    },
    [navigate],
  )

  // Refetch the currently visible window (offset 0) so poll updates replace
  // rows in place. Capped at the server's max limit.
  const refresh = useCallback(async () => {
    const limit = Math.min(Math.max(countRef.current, PAGE_SIZE), MAX_LIMIT)
    try {
      const data = await api(`/api/posts?limit=${limit}&offset=0`)
      setPosts(data.posts)
      setTotal(data.total)
      setError('')
    } catch (err) {
      handleError(err)
    }
  }, [handleError])

  useEffect(() => {
    refresh()
  }, [refresh])

  // Poll every 5s while any visible post has a pending/running step.
  useEffect(() => {
    if (!posts || !posts.some(hasActiveStep)) return undefined
    const timer = setTimeout(refresh, POLL_MS)
    return () => clearTimeout(timer)
  }, [posts, refresh])

  async function loadMore() {
    setLoadingMore(true)
    try {
      const data = await api(`/api/posts?limit=${PAGE_SIZE}&offset=${posts.length}`)
      setPosts((prev) => {
        const seen = new Set(prev.map((p) => p.id))
        return [...prev, ...data.posts.filter((p) => !seen.has(p.id))]
      })
      setTotal(data.total)
      setError('')
    } catch (err) {
      handleError(err)
    } finally {
      setLoadingMore(false)
    }
  }

  async function retry(postId, step) {
    // Optimistic: retried step and everything downstream go back to pending;
    // the poll loop picks up real statuses from the server.
    const fromIndex = STEPS.indexOf(step)
    setPosts((prev) =>
      prev.map((p) => {
        if (p.id !== postId) return p
        const next = { ...p }
        for (const s of STEPS.slice(fromIndex)) {
          next[`${s}_status`] = 'pending'
          next[`${s}_error_type`] = null
          next[`${s}_error_message`] = null
        }
        return next
      }),
    )
    try {
      await api(`/api/posts/${postId}/retry/${step}`, { method: 'POST' })
    } catch (err) {
      handleError(err)
    }
  }

  if (error && !posts) {
    return (
      <main className="page">
        <h1>Inbox</h1>
        <p className="error">{error}</p>
      </main>
    )
  }
  if (!posts) {
    return (
      <main className="page">
        <h1>Inbox</h1>
        <p>Loading…</p>
      </main>
    )
  }

  return (
    <main className="page">
      <h1>Inbox</h1>
      {error && <p className="error">{error}</p>}
      {posts.length === 0 ? (
        <p className="hint">No posts captured yet.</p>
      ) : (
        <div className="table-wrap">
          <table className="inbox-table">
            <thead>
              <tr>
                <th></th>
                <th>Captured</th>
                <th>Post</th>
                <th>Imgs</th>
                <th>OCR</th>
                <th>Translate</th>
                <th>Extract</th>
                <th>Embed</th>
                <th>Annotated</th>
              </tr>
            </thead>
            <tbody>
              {posts.map((post) => (
                <tr key={post.id}>
                  <td>
                    {post.first_image_url ? (
                      <img className="inbox-thumb" src={post.first_image_url} alt="" />
                    ) : (
                      <span className="inbox-thumb-empty" />
                    )}
                  </td>
                  <td className="cell-time">{formatCapturedAt(post.captured_at)}</td>
                  <td className="cell-caption">
                    <Link to={`/posts/${post.id}`}>
                      {post.caption_raw || post.xhs_note_id || post.id.slice(0, 8)}
                    </Link>
                  </td>
                  <td>{post.image_count}</td>
                  {STEPS.map((step) => (
                    <StatusCell key={step} post={post} step={step} onRetry={retry} />
                  ))}
                  <td>{post.has_annotation ? 'yes' : ''}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="hint">
        Showing {posts.length} of {total}
      </p>
      {posts.length < total && (
        <button type="button" className="load-more" onClick={loadMore} disabled={loadingMore}>
          {loadingMore ? 'Loading…' : 'Load more'}
        </button>
      )}
    </main>
  )
}
