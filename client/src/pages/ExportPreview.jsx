import { useEffect, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { api, apiText } from '../api.js'

// Export Preview: the fifth screen. Minimal chrome by design — its only job
// is to eyeball the rendered deliverable and grab the PDF / public HTML.

const VARIANTS = ['deliverable', 'public']

export default function ExportPreview() {
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const [reports, setReports] = useState(null)
  const [listError, setListError] = useState('')
  const [variant, setVariant] = useState('deliverable')
  const [html, setHtml] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const selectedId = searchParams.get('report') || ''

  // Load the report list; default the selection to the first report when the
  // URL does not already carry ?report= (ReportEditor links here with it).
  useEffect(() => {
    let alive = true
    api('/api/reports')
      .then((data) => {
        if (!alive) return
        setReports(data.reports)
      })
      .catch((err) => {
        if (err.status === 401) {
          navigate('/login')
          return
        }
        if (alive) setListError(err.message)
      })
    return () => {
      alive = false
    }
  }, [navigate])

  useEffect(() => {
    if (!reports || reports.length === 0) return
    const known = reports.some((r) => r.id === selectedId)
    if (!known) {
      setSearchParams({ report: reports[0].id }, { replace: true })
    }
  }, [reports, selectedId, setSearchParams])

  // Fetch the rendered HTML whenever report or variant changes.
  useEffect(() => {
    if (!selectedId) return
    let alive = true
    setLoading(true)
    setError('')
    apiText(`/api/reports/${selectedId}/export?variant=${variant}`)
      .then((text) => {
        if (alive) setHtml(text)
      })
      .catch((err) => {
        if (err.status === 401) {
          navigate('/login')
          return
        }
        if (alive) {
          setError(err.message)
          setHtml('')
        }
      })
      .finally(() => {
        if (alive) setLoading(false)
      })
    return () => {
      alive = false
    }
  }, [selectedId, variant, navigate])

  async function openPublicHtml() {
    if (!selectedId) return
    try {
      const text =
        variant === 'public' && html
          ? html
          : await apiText(`/api/reports/${selectedId}/export?variant=public`)
      const url = URL.createObjectURL(new Blob([text], { type: 'text/html' }))
      window.open(url, '_blank', 'noopener')
      // Give the new tab time to load before releasing the object URL.
      setTimeout(() => URL.revokeObjectURL(url), 60000)
    } catch (err) {
      if (err.status === 401) {
        navigate('/login')
        return
      }
      setError(err.message)
    }
  }

  return (
    <main className="page export-page">
      <h1>Export Preview</h1>
      {listError && <p className="error">{listError}</p>}
      {reports === null && !listError && <p>Loading…</p>}
      {reports !== null && reports.length === 0 && (
        <p className="hint">
          No reports yet — create one in <Link to="/reports">Reports</Link> first.
        </p>
      )}
      {reports !== null && reports.length > 0 && (
        <>
          <div className="export-toolbar">
            <select
              value={selectedId}
              onChange={(e) => setSearchParams({ report: e.target.value })}
              aria-label="Report"
            >
              {reports.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.title}
                  {r.week_of ? ` (week of ${r.week_of})` : ''}
                </option>
              ))}
            </select>
            <div className="variant-toggle" role="group" aria-label="Variant">
              {VARIANTS.map((v) => (
                <button
                  key={v}
                  type="button"
                  className={variant === v ? 'active' : ''}
                  aria-pressed={variant === v}
                  onClick={() => setVariant(v)}
                >
                  {v === 'deliverable' ? 'Deliverable' : 'Public'}
                </button>
              ))}
            </div>
            <span className="export-actions">
              <a href={`/api/reports/${selectedId}/export.pdf`} download>
                Download PDF
              </a>
              <button type="button" onClick={openPublicHtml}>
                Open public HTML in new tab
              </button>
            </span>
            {loading && <span className="hint">Rendering…</span>}
          </div>
          {error && <p className="error">{error}</p>}
          {!error && (
            <iframe
              className="export-frame"
              title="Report preview"
              srcDoc={html}
              sandbox=""
            />
          )}
        </>
      )}
    </main>
  )
}
