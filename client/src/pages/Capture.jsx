import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { postForm } from '../api.js'

export default function Capture() {
  const [files, setFiles] = useState([])
  const [caption, setCaption] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const navigate = useNavigate()

  async function onSubmit(e) {
    e.preventDefault()
    setError('')
    if (files.length === 0) {
      setError('Select at least one image.')
      return
    }
    setBusy(true)
    try {
      const form = new FormData()
      for (const file of files) form.append('images', file)
      if (caption.trim()) form.append('caption', caption)
      const data = await postForm('/api/capture', form)
      navigate(`/posts/${data.post_id || data.id}`)
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
    <main className="page page-narrow">
      <h1>RedThread — Capture</h1>
      <form onSubmit={onSubmit} className="stack">
        <label>
          Screenshots (PNG / JPEG / WebP)
          <input
            type="file"
            accept="image/png,image/jpeg,image/webp"
            multiple
            onChange={(e) => setFiles(Array.from(e.target.files || []))}
          />
        </label>
        {files.length > 0 && (
          <p className="hint">{files.length} file(s) selected: {files.map((f) => f.name).join(', ')}</p>
        )}
        <label>
          Caption (optional, paste the XHS caption)
          <textarea
            value={caption}
            onChange={(e) => setCaption(e.target.value)}
            rows={4}
          />
        </label>
        <button type="submit" disabled={busy}>{busy ? 'Uploading…' : 'Capture'}</button>
        {error && <p className="error">{error}</p>}
      </form>
    </main>
  )
}
