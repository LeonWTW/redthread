import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { api } from '../api.js'

const STEPS = ['ocr', 'translate', 'extract', 'embed']
const ACTIVE = ['pending', 'running']

function imageUrl(image) {
  if (image.url) return image.url
  return `/media/${image.file_path}`
}

function StepStatus({ post }) {
  return (
    <p className="status-line">
      {STEPS.map((step) => {
        const status = post[`${step}_status`] || 'unknown'
        const errorMessage = post[`${step}_error_message`]
        return (
          <span key={step} className={`step step-${status}`}>
            {step}: {status}
            {status === 'failed' && errorMessage ? ` — ${errorMessage}` : ''}
          </span>
        )
      })}
    </p>
  )
}

export default function PostView() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [post, setPost] = useState(null)
  const [error, setError] = useState('')
  const timerRef = useRef(null)

  const load = useCallback(async () => {
    try {
      const data = await api(`/api/posts/${id}`)
      setPost(data)
      setError('')
      const active = ACTIVE.includes(data.ocr_status) || ACTIVE.includes(data.translate_status)
      if (active) {
        timerRef.current = setTimeout(load, 2000)
      }
    } catch (err) {
      if (err.status === 401) {
        navigate('/login')
        return
      }
      setError(err.message)
    }
  }, [id, navigate])

  useEffect(() => {
    load()
    return () => clearTimeout(timerRef.current)
  }, [load])

  if (error) return <main className="page"><p className="error">{error}</p></main>
  if (!post) return <main className="page"><p>Loading…</p></main>

  const chinese = post.corrected_text || post.full_ocr_text || ''
  const english = post.final_translation || post.machine_translation || ''
  const images = post.images || []

  return (
    <main className="page">
      <h1>Post {post.id}</h1>
      <StepStatus post={post} />
      <div className="columns">
        <section className="col">
          <h2>Images</h2>
          {images.length === 0 && <p className="hint">No images.</p>}
          {images.map((img) => (
            <img key={img.id || img.file_path} src={imageUrl(img)} alt={`${img.image_type || 'image'} ${img.sort_order ?? ''}`} />
          ))}
        </section>
        <section className="col">
          <h2>Chinese</h2>
          {post.caption_raw && (
            <div className="block">
              <h3>Caption</h3>
              <pre>{post.caption_raw}</pre>
            </div>
          )}
          <div className="block">
            <h3>{post.corrected_text ? 'Corrected text' : 'OCR text'}</h3>
            <pre>{chinese || '(not yet available)'}</pre>
          </div>
        </section>
        <section className="col">
          <h2>English</h2>
          <div className="block">
            <h3>{post.final_translation ? 'Final translation' : 'Machine translation'}</h3>
            <pre>{english || '(not yet available)'}</pre>
          </div>
        </section>
      </div>
    </main>
  )
}
