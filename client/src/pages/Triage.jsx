import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../api.js'

// Triage: keyboard-first annotation. The 30s/post budget rules every choice
// here — one keystroke per taxonomy value, Enter saves, Backspace skips.
const GROUPS = [
  {
    field: 'category',
    label: 'Category',
    options: [
      { key: '1', value: 'skincare', label: 'skincare' },
      { key: '2', value: 'makeup', label: 'makeup' },
      { key: '3', value: 'haircare', label: 'haircare' },
      { key: '4', value: 'wellness', label: 'wellness' },
    ],
  },
  {
    field: 'consumer_signal',
    label: 'Consumer signal',
    options: [
      { key: 'q', value: 'bilei', label: '避雷 bilei' },
      { key: 'w', value: 'pingti', label: '平替 pingti' },
      { key: 'e', value: 'chengfen_dang', label: '成分党 chengfen_dang' },
      { key: 'r', value: 'zhongcao', label: '种草 zhongcao' },
      { key: 't', value: 'qiuzhen', label: '求真 qiuzhen' },
    ],
  },
  {
    field: 'trend_type',
    label: 'Trend type',
    options: [
      { key: 'a', value: 'ingredient', label: 'ingredient' },
      { key: 's', value: 'routine', label: 'routine' },
      { key: 'd', value: 'pain_point', label: 'pain_point' },
      { key: 'f', value: 'product_format', label: 'product_format' },
      { key: 'g', value: 'creator_format', label: 'creator_format' },
      { key: 'h', value: 'brand_move', label: 'brand_move' },
    ],
  },
  {
    field: 'recommended_action',
    label: 'Recommended action',
    options: [
      { key: '7', value: 'monitor', label: 'monitor' },
      { key: '8', value: 'test_content', label: 'test_content' },
      { key: '9', value: 'seed_koc', label: 'seed_koc' },
      { key: '0', value: 'avoid', label: 'avoid' },
    ],
  },
  {
    field: 'origin',
    label: 'Origin (optional; skip = NULL)',
    options: [
      { key: 'z', value: 'china_native', label: 'china_native' },
      { key: 'x', value: 'west_to_china', label: 'west_to_china' },
      { key: 'c', value: 'pan_asian', label: 'pan_asian' },
      { key: 'v', value: 'unclear', label: 'unclear' },
    ],
  },
]

const KEYMAP = {}
for (const group of GROUPS) {
  for (const option of group.options) {
    KEYMAP[option.key] = { field: group.field, value: option.value }
  }
}

function emptySelections() {
  return {
    category: null,
    trend_type: null,
    consumer_signal: null,
    recommended_action: null,
    origin: null,
  }
}

function formatElapsed(seconds) {
  const m = Math.floor(seconds / 60)
  const s = seconds % 60
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
}

function isEditable(el) {
  return !!el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA')
}

export default function Triage() {
  const navigate = useNavigate()
  const [queue, setQueue] = useState(null) // null = loading; array of post ids
  const [index, setIndex] = useState(0)
  const [post, setPost] = useState(null)
  const [selections, setSelections] = useState(emptySelections())
  const [notes, setNotes] = useState('')
  const [correctedText, setCorrectedText] = useState('')
  const [finalTranslation, setFinalTranslation] = useState('')
  const [editing, setEditing] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [elapsed, setElapsed] = useState(0)
  const seedRef = useRef({ corrected: '', translation: '' })
  const startRef = useRef(Date.now())

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

  // Queue: oldest-first unannotated posts, fetched once on mount.
  useEffect(() => {
    api('/api/posts?has_annotation=false&order=asc&limit=200')
      .then((data) => setQueue(data.posts.map((p) => p.id)))
      .catch(handleError)
  }, [handleError])

  // Load the current post's full record; reset all per-post state.
  useEffect(() => {
    if (!queue || index >= queue.length) return undefined
    let cancelled = false
    setPost(null)
    api(`/api/posts/${queue[index]}`)
      .then((data) => {
        if (cancelled) return
        const corrected = data.corrected_text || data.full_ocr_text || ''
        const translation = data.final_translation || data.machine_translation || ''
        seedRef.current = { corrected, translation }
        setCorrectedText(corrected)
        setFinalTranslation(translation)
        const anno = data.annotation
        setSelections({
          category: anno?.category ?? null,
          trend_type: anno?.trend_type ?? null,
          consumer_signal: anno?.consumer_signal ?? null,
          recommended_action: anno?.recommended_action ?? null,
          origin: anno?.origin ?? null,
        })
        setNotes(anno?.notes ?? '')
        setError('')
        startRef.current = Date.now()
        setElapsed(0)
        setPost(data)
      })
      .catch((err) => {
        if (!cancelled) handleError(err)
      })
    return () => {
      cancelled = true
    }
  }, [queue, index, handleError])

  // Per-post elapsed timer: the analyst self-checks the 30s budget.
  useEffect(() => {
    if (!post) return undefined
    const timer = setInterval(() => {
      setElapsed(Math.floor((Date.now() - startRef.current) / 1000))
    }, 1000)
    return () => clearInterval(timer)
  }, [post])

  // Hotkey-mode indicator: any focused input/textarea disables hotkeys.
  useEffect(() => {
    function onFocusIn(e) {
      setEditing(isEditable(e.target))
    }
    function onFocusOut() {
      setEditing(false)
    }
    document.addEventListener('focusin', onFocusIn)
    document.addEventListener('focusout', onFocusOut)
    return () => {
      document.removeEventListener('focusin', onFocusIn)
      document.removeEventListener('focusout', onFocusOut)
    }
  }, [])

  function toggle(field, value) {
    setSelections((prev) => ({ ...prev, [field]: prev[field] === value ? null : value }))
  }

  const skip = useCallback(() => {
    if (saving) return
    setIndex((i) => i + 1)
  }, [saving])

  const saveAndNext = useCallback(async () => {
    if (!post || saving) return
    setSaving(true)
    try {
      // Text corrections first: PATCH only changed fields (server re-embeds).
      const patch = {}
      if (correctedText !== seedRef.current.corrected) patch.corrected_text = correctedText
      if (finalTranslation !== seedRef.current.translation) {
        patch.final_translation = finalTranslation
      }
      if (Object.keys(patch).length > 0) {
        await api(`/api/posts/${post.id}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(patch),
        })
      }
      await api(`/api/posts/${post.id}/annotation`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...selections, notes: notes || null }),
      })
      setIndex((i) => i + 1)
    } catch (err) {
      handleError(err)
    } finally {
      setSaving(false)
    }
  }, [post, saving, correctedText, finalTranslation, selections, notes, handleError])

  // Global hotkeys. Disabled while focus is inside an input/textarea
  // (Escape blurs back to hotkey mode).
  useEffect(() => {
    function onKeyDown(e) {
      if (isEditable(e.target)) {
        if (e.key === 'Escape') e.target.blur()
        return
      }
      if (e.metaKey || e.ctrlKey || e.altKey) return
      if (e.key === 'Enter') {
        e.preventDefault()
        saveAndNext()
        return
      }
      if (e.key === 'Backspace') {
        e.preventDefault()
        skip()
        return
      }
      const hit = KEYMAP[e.key.toLowerCase()]
      if (hit) {
        e.preventDefault()
        toggle(hit.field, hit.value)
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [saveAndNext, skip])

  if (error && !post) {
    return (
      <main className="page">
        <h1>Triage</h1>
        <p className="error">{error}</p>
      </main>
    )
  }
  if (!queue) {
    return (
      <main className="page">
        <h1>Triage</h1>
        <p>Loading…</p>
      </main>
    )
  }
  if (index >= queue.length) {
    return (
      <main className="page">
        <h1>Triage</h1>
        <p>Triage queue clear.</p>
        <p>
          <Link to="/inbox">Back to Inbox</Link>
        </p>
      </main>
    )
  }
  if (!post) {
    return (
      <main className="page">
        <h1>Triage</h1>
        <p>
          Loading post {index + 1} of {queue.length}…
        </p>
      </main>
    )
  }

  const images = post.images || []
  const entities = Array.isArray(post.entities) ? post.entities : []

  return (
    <main className="page triage">
      <div
        className={editing ? 'hotkey-bar hotkey-off' : 'hotkey-bar hotkey-on'}
        title={editing ? 'Hotkeys off while editing — Esc to resume' : 'Hotkeys active'}
      >
        {editing ? 'Editing — Esc resumes hotkeys' : 'Hotkeys on'}
      </div>
      {error && <p className="error">{error}</p>}
      <div className="triage-grid">
        <section className="triage-images">
          <div className="queue-pos">
            <span className="queue-count">
              {index + 1} of {queue.length}
            </span>
            <span className="queue-timer">{formatElapsed(elapsed)}</span>
          </div>
          <div className="triage-image-scroll">
            {images.length === 0 && <p className="hint">No images.</p>}
            {images.map((img) => (
              <img
                key={img.id}
                src={img.url}
                alt={`${img.image_type || 'image'} ${img.sort_order ?? ''}`}
              />
            ))}
          </div>
        </section>

        <section className="triage-record">
          {post.caption_raw && (
            <div className="block">
              <h3>Caption (raw)</h3>
              <pre>{post.caption_raw}</pre>
            </div>
          )}
          <div className="block">
            <h3>Chinese text (corrected_text)</h3>
            <textarea
              className="triage-text"
              value={correctedText}
              onChange={(e) => setCorrectedText(e.target.value)}
              rows={8}
              aria-label="Corrected Chinese text"
            />
          </div>
          <div className="block">
            <h3>English translation (final_translation)</h3>
            <textarea
              className="triage-text"
              value={finalTranslation}
              onChange={(e) => setFinalTranslation(e.target.value)}
              rows={8}
              aria-label="Final English translation"
            />
          </div>
          {entities.length > 0 && (
            <div className="block">
              <h3>Entities (model self-reported confidence)</h3>
              <div className="chips">
                {entities.map((entity, i) => (
                  <span key={i} className="chip">
                    {entity.text_zh}
                    {entity.text_en ? ` (${entity.text_en})` : ''}{' '}
                    <span className="chip-type">[{entity.type}]</span>
                    {typeof entity.confidence === 'number'
                      ? ` ${entity.confidence.toFixed(2)}`
                      : ''}
                  </span>
                ))}
              </div>
            </div>
          )}
        </section>

        <section className="triage-anno">
          {GROUPS.map((group) => (
            <div key={group.field} className="anno-group">
              <h3>{group.label}</h3>
              <div className="anno-options">
                {group.options.map((option) => (
                  <button
                    key={option.key}
                    type="button"
                    className={
                      selections[group.field] === option.value
                        ? 'anno-btn anno-selected'
                        : 'anno-btn'
                    }
                    onClick={() => toggle(group.field, option.value)}
                  >
                    <span className="anno-key">{option.key.toUpperCase()}</span> {option.label}
                  </button>
                ))}
              </div>
            </div>
          ))}
          <div className="anno-group">
            <h3>Notes</h3>
            <textarea
              className="triage-text"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              rows={3}
              aria-label="Annotation notes"
            />
          </div>
          <div className="anno-actions">
            <button type="button" className="anno-save" onClick={saveAndNext} disabled={saving}>
              {saving ? 'Saving…' : 'Save & Next'} <span className="anno-key">↵</span>
            </button>
            <button type="button" className="anno-skip" onClick={skip} disabled={saving}>
              Skip <span className="anno-key">⌫</span>
            </button>
          </div>
        </section>
      </div>
    </main>
  )
}
