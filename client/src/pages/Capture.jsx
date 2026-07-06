import { useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api, postForm } from '../api.js'

const MAX_FILES = 20
const ACCEPT = 'image/png,image/jpeg,image/webp'

// Normalize near_duplicates from either response shape:
// capture: [{image_index, matches: [{post_id, image_id, distance}]}]
// images:  flat [{post_id, image_id, distance}] (or the nested shape).
function flattenMatches(nearDuplicates) {
  const matches = []
  for (const item of nearDuplicates || []) {
    if (Array.isArray(item.matches)) matches.push(...item.matches)
    else matches.push(item)
  }
  return matches
}

function DupNotices({ dups }) {
  if (dups.length === 0) return null
  return (
    <div className="notice-warn">
      <strong>Possible duplicates (soft warning — capture succeeded):</strong>
      <ul>
        {dups.map((d, i) => (
          <li key={i}>
            {d.label}: possible duplicate of post{' '}
            <Link to={`/posts/${d.match.post_id}`}>{d.match.post_id}</Link>
            {typeof d.match.distance === 'number' && <> (distance {d.match.distance})</>}
          </li>
        ))}
      </ul>
    </div>
  )
}

const STATUS_CLASS = {
  queued: 'step',
  uploading: 'step step-running',
  done: 'step step-success',
  failed: 'step step-failed',
}

function ScreenshotsSection() {
  const [files, setFiles] = useState([])
  const [statuses, setStatuses] = useState([])
  const [fileErrors, setFileErrors] = useState([])
  const [caption, setCaption] = useState('')
  const [url, setUrl] = useState('')
  const [postId, setPostId] = useState(null)
  const [dups, setDups] = useState([])
  const [alreadyCaptured, setAlreadyCaptured] = useState(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [processing, setProcessing] = useState(false)
  const [dragOver, setDragOver] = useState(false)
  const postIdRef = useRef(null)
  const navigate = useNavigate()

  const allDone = files.length > 0 && statuses.every((s) => s === 'done')
  const anyFailed = statuses.some((s) => s === 'failed')
  const started = statuses.some((s) => s !== 'queued')

  function handleFiles(fileList) {
    const picked = Array.from(fileList || [])
    setError('')
    if (picked.length > MAX_FILES) {
      setError(`Too many files: max ${MAX_FILES} images per capture.`)
      return
    }
    setFiles(picked)
    setStatuses(picked.map(() => 'queued'))
    setFileErrors(picked.map(() => ''))
    setDups([])
    setAlreadyCaptured(null)
    setPostId(null)
    postIdRef.current = null
  }

  function onSelect(e) {
    handleFiles(e.target.files)
  }

  function setStatusAt(index, value) {
    setStatuses((prev) => prev.map((s, i) => (i === index ? value : s)))
  }

  function setFileErrorAt(index, value) {
    setFileErrors((prev) => prev.map((s, i) => (i === index ? value : s)))
  }

  function collectDups(fileName, nearDuplicates) {
    const matches = flattenMatches(nearDuplicates)
    if (matches.length === 0) return
    setDups((prev) => [...prev, ...matches.map((match) => ({ label: fileName, match }))])
  }

  async function processAndGo(pid) {
    setProcessing(true)
    setError('')
    try {
      await api(`/api/posts/${pid}/process`, { method: 'POST' })
      navigate(`/posts/${pid}`)
    } catch (err) {
      if (err.status === 401) {
        navigate('/login')
        return
      }
      setError(`Failed to start processing: ${err.message}`)
      setProcessing(false)
    }
  }

  // Upload files sequentially, one request per file (iOS Safari kills long
  // requests). Stops at the first failure; Retry resumes from that file.
  async function uploadFrom(startIndex) {
    setBusy(true)
    setError('')
    let pid = postIdRef.current
    for (let i = startIndex; i < files.length; i++) {
      setStatusAt(i, 'uploading')
      setFileErrorAt(i, '')
      try {
        let data
        if (!pid) {
          const form = new FormData()
          form.append('images', files[i])
          form.append('defer_pipeline', '1')
          if (caption.trim()) form.append('caption', caption)
          if (url.trim()) form.append('url', url.trim())
          data = await postForm('/api/capture', form)
          if (data.already_captured) {
            // The URL matched an existing post; nothing was created.
            setAlreadyCaptured(data.post_id)
            setStatusAt(i, 'queued')
            setBusy(false)
            return
          }
          pid = data.post_id
          postIdRef.current = pid
          setPostId(pid)
        } else {
          const form = new FormData()
          form.append('image', files[i])
          data = await postForm(`/api/posts/${pid}/images`, form)
        }
        collectDups(files[i].name, data.near_duplicates)
        setStatusAt(i, 'done')
      } catch (err) {
        if (err.status === 401) {
          navigate('/login')
          return
        }
        setStatusAt(i, 'failed')
        setFileErrorAt(i, err.message)
        setBusy(false)
        return
      }
    }
    setBusy(false)
    await processAndGo(pid)
  }

  async function onSubmit(e) {
    e.preventDefault()
    if (files.length === 0) {
      setError('Select at least one image.')
      return
    }
    await uploadFrom(0)
  }

  return (
    <section className="section">
      <h2>Screenshots</h2>
      <form onSubmit={onSubmit} className="stack">
        <label
          className={dragOver ? 'drop-zone drag-over' : 'drop-zone'}
          onDragOver={(e) => {
            e.preventDefault()
            if (!busy && !processing) setDragOver(true)
          }}
          onDragLeave={() => setDragOver(false)}
          onDrop={(e) => {
            e.preventDefault()
            setDragOver(false)
            // Same guard as the picker input's disabled state: no new files
            // mid-upload, or the in-flight queue would be reset.
            if (busy || processing) return
            handleFiles(e.dataTransfer.files)
          }}
        >
          <input type="file" accept={ACCEPT} multiple onChange={onSelect} disabled={busy || processing} />
          <span>Tap to choose screenshots — or drop them here</span>
          <span className="drop-zone-hint">PNG · JPEG · WebP, up to {MAX_FILES} files</span>
        </label>
        <label>
          XHS URL (optional, for dedup)
          <input
            type="url"
            inputMode="url"
            placeholder="https://www.xiaohongshu.com/explore/..."
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            disabled={started}
          />
        </label>
        <label>
          Caption (optional, paste the XHS caption)
          <textarea value={caption} onChange={(e) => setCaption(e.target.value)} rows={3} disabled={started} />
        </label>
        {files.length > 0 && (
          <ul className="file-list">
            {files.map((f, i) => (
              <li key={i} className="file-row">
                <span className="file-name">{f.name}</span>
                <span className={STATUS_CLASS[statuses[i]]}>{statuses[i]}</span>
                {statuses[i] === 'failed' && (
                  <button type="button" onClick={() => uploadFrom(i)} disabled={busy || processing}>
                    Retry
                  </button>
                )}
                {fileErrors[i] && <span className="error file-error">{fileErrors[i]}</span>}
              </li>
            ))}
          </ul>
        )}
        {alreadyCaptured && (
          <p className="notice-warn">
            Already captured: this URL matches an existing post.{' '}
            <Link to={`/posts/${alreadyCaptured}`}>Open post</Link>. Nothing was uploaded.
          </p>
        )}
        <DupNotices dups={dups} />
        {!allDone && (
          <button type="submit" disabled={busy || processing || files.length === 0}>
            {busy ? 'Uploading…' : started ? 'Resume upload' : 'Upload screenshots'}
          </button>
        )}
        {anyFailed && postId && (
          <button type="button" onClick={() => processAndGo(postId)} disabled={busy || processing}>
            {processing ? 'Starting…' : 'Process anyway'}
          </button>
        )}
        {allDone && processing && <p className="hint">Starting pipeline…</p>}
        {error && <p className="error">{error}</p>}
      </form>
    </section>
  )
}

function UrlSection() {
  const [url, setUrl] = useState('')
  const [caption, setCaption] = useState('')
  const [alreadyCaptured, setAlreadyCaptured] = useState(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const navigate = useNavigate()

  async function onSubmit(e) {
    e.preventDefault()
    setError('')
    setAlreadyCaptured(null)
    if (!url.trim()) {
      setError('Paste an XHS URL.')
      return
    }
    setBusy(true)
    try {
      const form = new FormData()
      form.append('url', url.trim())
      if (caption.trim()) form.append('caption', caption)
      const data = await postForm('/api/capture', form)
      if (data.already_captured) {
        setAlreadyCaptured(data.post_id)
        setBusy(false)
        return
      }
      navigate(`/posts/${data.post_id}`)
    } catch (err) {
      if (err.status === 401) {
        navigate('/login')
        return
      }
      setError(err.message)
      setBusy(false)
    }
  }

  return (
    <section className="section">
      <h2>URL paste</h2>
      <form onSubmit={onSubmit} className="stack">
        <label>
          XHS URL
          <input
            type="url"
            inputMode="url"
            placeholder="https://www.xiaohongshu.com/explore/..."
            value={url}
            onChange={(e) => setUrl(e.target.value)}
          />
        </label>
        <label>
          Caption (optional)
          <textarea value={caption} onChange={(e) => setCaption(e.target.value)} rows={3} />
        </label>
        <button type="submit" disabled={busy}>{busy ? 'Capturing…' : 'Capture URL'}</button>
        {alreadyCaptured && (
          <p className="notice-warn">
            Already captured. <Link to={`/posts/${alreadyCaptured}`}>Open post</Link>.
          </p>
        )}
        {error && <p className="error">{error}</p>}
      </form>
    </section>
  )
}

function CsvSection() {
  const [file, setFile] = useState(null)
  const [result, setResult] = useState(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const navigate = useNavigate()

  async function onSubmit(e) {
    e.preventDefault()
    setError('')
    setResult(null)
    if (!file) {
      setError('Select a CSV file.')
      return
    }
    setBusy(true)
    try {
      const form = new FormData()
      form.append('file', file)
      const data = await postForm('/api/import/csv', form)
      setResult(data)
    } catch (err) {
      if (err.status === 401) {
        navigate('/login')
        return
      }
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="section">
      <h2>CSV import</h2>
      <p className="hint">Columns: url (required), caption, captured_at, notes. Header row required.</p>
      <form onSubmit={onSubmit} className="stack">
        <label>
          CSV file
          <input
            type="file"
            accept=".csv,text/csv"
            onChange={(e) => setFile((e.target.files || [])[0] || null)}
          />
        </label>
        <button type="submit" disabled={busy}>{busy ? 'Importing…' : 'Import CSV'}</button>
        {error && <p className="error">{error}</p>}
        {result && (
          <div className="csv-result">
            <p><strong>Created:</strong> {result.created}</p>
            {result.duplicates?.length > 0 && (
              <div>
                <strong>Duplicates (skipped):</strong>
                <ul>
                  {result.duplicates.map((d, i) => (
                    <li key={i}>
                      Row {d.row}: already captured — <Link to={`/posts/${d.post_id}`}>open post</Link>
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {result.errors?.length > 0 && (
              <div>
                <strong>Errors:</strong>
                <ul>
                  {result.errors.map((e2, i) => (
                    <li key={i} className="error">Row {e2.row}: {e2.error}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}
      </form>
    </section>
  )
}

export default function Capture() {
  return (
    <main className="page page-narrow">
      <h1>Capture</h1>
      <ScreenshotsSection />
      <UrlSection />
      <CsvSection />
    </main>
  )
}
