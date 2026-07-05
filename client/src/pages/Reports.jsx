import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api, postJson } from '../api.js'

// Reports list: entry point of the weekly report loop (Loop 2, ~1h budget).
// Create a report, land straight in the editor.

function formatDate(iso) {
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

export default function Reports() {
  const navigate = useNavigate()
  const [reports, setReports] = useState(null)
  const [error, setError] = useState('')
  const [title, setTitle] = useState('')
  const [weekOf, setWeekOf] = useState('')
  const [creating, setCreating] = useState(false)
  const [createError, setCreateError] = useState('')

  useEffect(() => {
    let alive = true
    api('/api/reports')
      .then((data) => {
        if (alive) setReports(data.reports)
      })
      .catch((err) => {
        if (err.status === 401) {
          navigate('/login')
          return
        }
        if (alive) setError(err.message)
      })
    return () => {
      alive = false
    }
  }, [navigate])

  async function create(e) {
    e.preventDefault()
    const t = title.trim()
    if (!t || creating) return
    setCreating(true)
    setCreateError('')
    try {
      const body = { title: t }
      if (weekOf) body.week_of = weekOf
      const report = await postJson('/api/reports', body)
      navigate(`/reports/${report.id}`)
    } catch (err) {
      if (err.status === 401) {
        navigate('/login')
        return
      }
      setCreateError(err.message)
    } finally {
      setCreating(false)
    }
  }

  return (
    <main className="page">
      <h1>Reports</h1>
      <form className="report-new" onSubmit={create}>
        <input
          type="text"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="Report title"
          aria-label="Report title"
        />
        <input
          type="date"
          value={weekOf}
          onChange={(e) => setWeekOf(e.target.value)}
          aria-label="Week of (optional)"
        />
        <button type="submit" disabled={creating || !title.trim()}>
          {creating ? 'Creating…' : 'New report'}
        </button>
      </form>
      {createError && <p className="error">{createError}</p>}
      {error && <p className="error">{error}</p>}
      {reports === null && !error && <p>Loading…</p>}
      {reports !== null && reports.length === 0 && (
        <p className="hint">No reports yet — create the first weekly report above.</p>
      )}
      {reports !== null && reports.length > 0 && (
        <div className="table-wrap">
          <table className="report-table">
            <thead>
              <tr>
                <th>Title</th>
                <th>Week of</th>
                <th>Status</th>
                <th>Blocks</th>
                <th>Updated</th>
              </tr>
            </thead>
            <tbody>
              {reports.map((report) => (
                <tr key={report.id}>
                  <td>
                    <Link to={`/reports/${report.id}`}>{report.title}</Link>
                  </td>
                  <td className="cell-time">{report.week_of || '—'}</td>
                  <td>
                    <span className={`badge status-${report.status}`}>{report.status}</span>
                  </td>
                  <td>{report.block_count}</td>
                  <td className="cell-time">{formatDate(report.updated_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </main>
  )
}
