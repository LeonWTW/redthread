import { useCallback, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../api.js'

// Library: semantic search over the corpus (COVERAGE loop — answer
// "what is XHS saying about X?" in 30 seconds, with evidence).
// Queries pass through as-is: English, Chinese, or mixed.

const SNIPPET_LEN = 200

// consumer_signal enum -> Chinese term (source Chinese always shown).
const SIGNAL_ZH = {
  bilei: '避雷',
  pingti: '平替',
  chengfen_dang: '成分党',
  zhongcao: '种草',
  qiuzhen: '求真',
}

function snippet(text) {
  if (!text) return ''
  return text.length > SNIPPET_LEN ? `${text.slice(0, SNIPPET_LEN)}…` : text
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

function AnnotationBadges({ annotation }) {
  if (!annotation) return null
  const badges = []
  if (annotation.category) badges.push(annotation.category)
  if (annotation.consumer_signal) {
    const zh = SIGNAL_ZH[annotation.consumer_signal]
    badges.push(zh ? `${zh} ${annotation.consumer_signal}` : annotation.consumer_signal)
  }
  if (annotation.recommended_action) badges.push(annotation.recommended_action)
  if (badges.length === 0) return null
  return (
    <div className="library-badges">
      {badges.map((label) => (
        <span key={label} className="badge badge-pending">
          {label}
        </span>
      ))}
    </div>
  )
}

function ResultCard({ result, onDelete, deleting, deleteError }) {
  const zh = snippet(result.corrected_text || result.full_ocr_text || result.caption_raw)
  const en = snippet(result.final_translation || result.machine_translation)
  return (
    <li className="library-card">
      {result.first_image_url ? (
        <img className="library-thumb" src={result.first_image_url} alt="" />
      ) : (
        <span className="library-thumb library-thumb-empty" />
      )}
      <div className="library-body">
        <div className="library-meta">
          <Link to={`/posts/${result.id}`}>View post</Link>
          <span className="cell-time">{formatCapturedAt(result.captured_at)}</span>
          {typeof result.score === 'number' && (
            <span className="library-score">score {result.score.toFixed(3)}</span>
          )}
        </div>
        {zh && <p className="library-snippet library-zh">{zh}</p>}
        {en && <p className="library-snippet">{en}</p>}
        {!zh && !en && <p className="hint">(no text)</p>}
        <AnnotationBadges annotation={result.annotation} />
        <div className="library-actions">
          {/* TODO(plan 001 M6): wire "Add to report" to the report builder. */}
          <button type="button" disabled title="Report builder arrives in the next milestone">
            Add to report
          </button>
          <button type="button" onClick={() => onDelete(result.id)} disabled={deleting}>
            {deleting ? 'Deleting…' : 'Delete'}
          </button>
        </div>
        {deleteError && <p className="error">{deleteError}</p>}
      </div>
    </li>
  )
}

export default function Library() {
  const navigate = useNavigate()
  const [query, setQuery] = useState('')
  const [results, setResults] = useState(null) // null = no search yet
  const [searching, setSearching] = useState(false)
  const [error, setError] = useState('')
  const [deletingId, setDeletingId] = useState(null)
  const [deleteErrors, setDeleteErrors] = useState({}) // post id -> message

  const handleError = useCallback(
    (err, apply) => {
      if (err.status === 401) {
        navigate('/login')
        return
      }
      apply(err.message)
    },
    [navigate],
  )

  async function search(e) {
    e.preventDefault()
    const q = query.trim()
    if (!q || searching) return
    setSearching(true)
    setError('')
    try {
      const data = await api(`/api/search?q=${encodeURIComponent(q)}`)
      setResults(data.results)
      setDeleteErrors({})
    } catch (err) {
      // 503 (provider not configured) and others render the server message plainly.
      handleError(err, setError)
    } finally {
      setSearching(false)
    }
  }

  async function deletePost(id) {
    if (!window.confirm('Delete this post? Images and annotation go with it.')) return
    setDeletingId(id)
    setDeleteErrors((prev) => ({ ...prev, [id]: '' }))
    try {
      await api(`/api/posts/${id}`, { method: 'DELETE' })
      setResults((prev) => prev.filter((r) => r.id !== id))
    } catch (err) {
      // 409 = post is cited in report(s); show the server's message on the card.
      handleError(err, (message) => setDeleteErrors((prev) => ({ ...prev, [id]: message })))
    } finally {
      setDeletingId(null)
    }
  }

  return (
    <main className="page">
      <h1>Library</h1>
      <form className="library-search" onSubmit={search}>
        <input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search the corpus…"
          aria-label="Search the corpus"
          autoFocus
        />
        <button type="submit" disabled={searching}>
          {searching ? 'Searching…' : 'Search'}
        </button>
      </form>
      {error && <p className="error">{error}</p>}
      {results === null && !error && (
        <p className="hint">Search the corpus in English, 中文, or mixed.</p>
      )}
      {results !== null && results.length === 0 && !error && <p className="hint">No matches.</p>}
      {results !== null && results.length > 0 && (
        <ul className="library-results">
          {results.map((result) => (
            <ResultCard
              key={result.id}
              result={result}
              onDelete={deletePost}
              deleting={deletingId === result.id}
              deleteError={deleteErrors[result.id]}
            />
          ))}
        </ul>
      )}
    </main>
  )
}
