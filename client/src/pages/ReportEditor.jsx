import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api, patchJson, postJson } from '../api.js'
import { clearTray, readTray, removeFromTray } from '../citationTray.js'

// Report Editor: THE core screen of the weekly report loop (<=1h budget).
// Five sections in the locked template order; every claim carries >=1
// citation — the Save button mirrors the server rule (and the deferred DB
// trigger backstops both). Citation chips open the source post in a side
// panel so evidence is verifiable without leaving the editor.

const SECTIONS = [
  { key: 'brand_watch', label: 'C-beauty Brand Watch' },
  { key: 'trend_radar', label: 'Trend Radar' },
  { key: 'not_crossing', label: 'Not Crossing' },
  { key: 'decoder', label: 'Consumer Language Decoder' },
  { key: 'seen_in_china', label: 'Seen in China (optional)' },
]

const BLOCK_SECTIONS = ['brand_watch', 'trend_radar', 'not_crossing', 'seen_in_china']

const CROSSOVER_FACTORS = [
  { key: 'visual_legibility', label: 'Visual legibility' },
  { key: 'price_shipability', label: 'Price & shipability' },
  { key: 'creator_translatability', label: 'Creator translatability' },
  { key: 'institutional_carrier', label: 'Institutional carrier' },
]

const VERDICTS = ['will_cross', 'wont_cross', 'watch']

const SNIPPET_LEN = 80

function snippet(text) {
  if (!text) return ''
  return text.length > SNIPPET_LEN ? `${text.slice(0, SNIPPET_LEN)}…` : text
}

// Library/search card -> citation object shaped like the server's block
// citation JSON (the server recomputes authoritative snippets on save).
function cardToCitation(card) {
  return {
    post_id: card.id,
    zh_snippet: snippet(card.corrected_text || card.full_ocr_text || card.caption_raw),
    en_snippet: snippet(card.final_translation || card.machine_translation),
    first_image_url: card.first_image_url || null,
  }
}

function nextSort(blocks) {
  return blocks.reduce((max, b) => Math.max(max, b.sort_order ?? 0), 0) + 1
}

function CitationChip({ citation, onOpen, onRemove }) {
  return (
    <span className="cite-chip" title={citation.en_snippet || ''}>
      <button
        type="button"
        className="cite-chip-open"
        onClick={() => onOpen(citation.post_id)}
        aria-label="Open source post"
      >
        {citation.first_image_url && <img src={citation.first_image_url} alt="" />}
        <span className="cite-chip-zh">
          {citation.zh_snippet || citation.en_snippet || citation.post_id.slice(0, 8)}
        </span>
      </button>
      {onRemove && (
        <button
          type="button"
          className="cite-chip-remove"
          onClick={() => onRemove(citation.post_id)}
          aria-label="Remove citation"
        >
          ×
        </button>
      )}
    </span>
  )
}

function CiteRow({ citation, attached, onAttach, onRemove }) {
  return (
    <li className="cite-row">
      {citation.first_image_url ? (
        <img src={citation.first_image_url} alt="" />
      ) : (
        <span className="cite-row-thumb-empty" />
      )}
      <span className="cite-row-text">
        <span className="cite-row-zh">{citation.zh_snippet || '(no text)'}</span>
        {citation.en_snippet && <span className="cite-row-en">{citation.en_snippet}</span>}
      </span>
      <button type="button" disabled={attached} onClick={() => onAttach(citation)}>
        {attached ? 'Attached' : 'Attach'}
      </button>
      {onRemove && (
        <button type="button" onClick={() => onRemove(citation.post_id)}>
          Remove
        </button>
      )}
    </li>
  )
}

// Two citation sources, both first-class: the localStorage tray (filled from
// Library) and an inline mini-search against /api/search.
function CitationPicker({ attachedIds, onAttach, tray, onTrayRemove, onTrayClear, onUnauthorized }) {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState(null)
  const [searching, setSearching] = useState(false)
  const [error, setError] = useState('')

  async function runSearch() {
    const q = query.trim()
    if (!q || searching) return
    setSearching(true)
    setError('')
    try {
      const data = await api(`/api/search?q=${encodeURIComponent(q)}`)
      setResults(data.results)
    } catch (err) {
      if (err.status === 401) {
        onUnauthorized()
        return
      }
      setError(err.message)
    } finally {
      setSearching(false)
    }
  }

  return (
    <div className="cite-picker">
      <div>
        <div className="cite-picker-head">
          <h4>Citation tray</h4>
          {tray.length > 0 && (
            <button type="button" onClick={onTrayClear}>
              Clear tray
            </button>
          )}
        </div>
        {tray.length === 0 && (
          <p className="hint">Empty — use “Add to report” on Library cards.</p>
        )}
        {tray.length > 0 && (
          <ul>
            {tray.map((item) => (
              <CiteRow
                key={item.post_id}
                citation={item}
                attached={attachedIds.includes(item.post_id)}
                onAttach={onAttach}
                onRemove={onTrayRemove}
              />
            ))}
          </ul>
        )}
      </div>
      <div>
        <h4>Search the corpus</h4>
        <div className="cite-search-bar">
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault()
                runSearch()
              }
            }}
            placeholder="Find a source post…"
            aria-label="Search for a source post"
          />
          <button type="button" onClick={runSearch} disabled={searching}>
            {searching ? 'Searching…' : 'Search'}
          </button>
        </div>
        {error && <p className="error">{error}</p>}
        {results !== null && results.length === 0 && <p className="hint">No matches.</p>}
        {results !== null && results.length > 0 && (
          <ul>
            {results.map((card) => {
              const cite = cardToCitation(card)
              return (
                <CiteRow
                  key={card.id}
                  citation={cite}
                  attached={attachedIds.includes(card.id)}
                  onAttach={onAttach}
                />
              )
            })}
          </ul>
        )}
      </div>
    </div>
  )
}

// Claim composer: textarea + citation chips + picker. Save stays disabled
// until text is non-empty AND >=1 citation is attached (server rule mirror).
function ClaimComposer({
  reportId,
  section,
  parentBlockId = null,
  block = null,
  nextSortOrder,
  tray,
  onTrayRemove,
  onTrayClear,
  onOpenPost,
  onSaved,
  onCancel,
  onUnauthorized,
}) {
  const [text, setText] = useState(block?.text_content || '')
  const [citations, setCitations] = useState(block?.citations || [])
  const [pickerOpen, setPickerOpen] = useState(false)
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)

  const canSave = text.trim().length > 0 && citations.length >= 1 && !saving
  const attachedIds = citations.map((c) => c.post_id)

  function attach(citation) {
    setCitations((prev) =>
      prev.some((c) => c.post_id === citation.post_id) ? prev : [...prev, citation],
    )
  }

  function detach(postId) {
    setCitations((prev) => prev.filter((c) => c.post_id !== postId))
  }

  async function save() {
    if (!canSave) return
    setSaving(true)
    setError('')
    try {
      const citationIds = citations.map((c) => c.post_id)
      let saved
      if (block) {
        saved = await patchJson(`/api/blocks/${block.id}`, {
          text_content: text,
          citations: citationIds,
        })
      } else {
        const payload = {
          section,
          block_type: 'claim',
          text_content: text,
          citations: citationIds,
          sort_order: nextSortOrder,
        }
        if (parentBlockId) payload.parent_block_id = parentBlockId
        saved = await postJson(`/api/reports/${reportId}/blocks`, payload)
      }
      onSaved(saved)
      if (!block) {
        setText('')
        setCitations([])
        setPickerOpen(false)
      }
    } catch (err) {
      if (err.status === 401) {
        onUnauthorized()
        return
      }
      // Server 400s name exactly what's wrong; render them verbatim.
      setError(err.message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="composer">
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder="Claim — every sentence here ships to the client, and needs evidence."
        aria-label="Claim text"
      />
      {citations.length > 0 && (
        <div className="chips-row">
          {citations.map((c) => (
            <CitationChip key={c.post_id} citation={c} onOpen={onOpenPost} onRemove={detach} />
          ))}
        </div>
      )}
      {citations.length === 0 && <p className="hint">No citations yet — a claim needs at least one.</p>}
      <div className="composer-row">
        <button type="button" onClick={() => setPickerOpen((open) => !open)}>
          {pickerOpen ? 'Hide citation picker' : 'Add citation'}
        </button>
        <button type="button" className="composer-save" onClick={save} disabled={!canSave}>
          {saving ? 'Saving…' : block ? 'Save changes' : 'Save claim'}
        </button>
        {onCancel && (
          <button type="button" onClick={onCancel}>
            Cancel
          </button>
        )}
      </div>
      {error && <p className="error">{error}</p>}
      {pickerOpen && (
        <CitationPicker
          attachedIds={attachedIds}
          onAttach={attach}
          tray={tray}
          onTrayRemove={onTrayRemove}
          onTrayClear={onTrayClear}
          onUnauthorized={onUnauthorized}
        />
      )}
    </div>
  )
}

// Trend composer (trend_radar only): title + summary + Crossover Screen
// (four factors + verdict) + optional citations.
function TrendComposer({
  reportId,
  block = null,
  nextSortOrder,
  tray,
  onTrayRemove,
  onTrayClear,
  onOpenPost,
  onSaved,
  onCancel,
  onUnauthorized,
}) {
  const [trendTitle, setTrendTitle] = useState(block?.trend_title || '')
  const [text, setText] = useState(block?.text_content || '')
  const [factors, setFactors] = useState(() => {
    const initial = {}
    for (const f of CROSSOVER_FACTORS) initial[f.key] = block?.crossover?.[f.key] || ''
    return initial
  })
  const [verdict, setVerdict] = useState(block?.crossover_verdict || '')
  const [citations, setCitations] = useState(block?.citations || [])
  const [pickerOpen, setPickerOpen] = useState(false)
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)

  const canSave = trendTitle.trim().length > 0 && !saving
  const attachedIds = citations.map((c) => c.post_id)

  function attach(citation) {
    setCitations((prev) =>
      prev.some((c) => c.post_id === citation.post_id) ? prev : [...prev, citation],
    )
  }

  function detach(postId) {
    setCitations((prev) => prev.filter((c) => c.post_id !== postId))
  }

  async function save() {
    if (!canSave) return
    setSaving(true)
    setError('')
    try {
      const payload = {
        trend_title: trendTitle,
        text_content: text || null,
        citations: citations.map((c) => c.post_id),
      }
      // crossover, when sent, must carry exactly the four factor keys.
      if (CROSSOVER_FACTORS.some((f) => factors[f.key].trim())) {
        const crossover = {}
        for (const f of CROSSOVER_FACTORS) crossover[f.key] = factors[f.key]
        payload.crossover = crossover
      }
      if (verdict) payload.crossover_verdict = verdict
      let saved
      if (block) {
        saved = await patchJson(`/api/blocks/${block.id}`, payload)
      } else {
        saved = await postJson(`/api/reports/${reportId}/blocks`, {
          ...payload,
          section: 'trend_radar',
          block_type: 'trend',
          sort_order: nextSortOrder,
        })
      }
      onSaved(saved)
      if (!block) {
        setTrendTitle('')
        setText('')
        setFactors(() => {
          const cleared = {}
          for (const f of CROSSOVER_FACTORS) cleared[f.key] = ''
          return cleared
        })
        setVerdict('')
        setCitations([])
        setPickerOpen(false)
      }
    } catch (err) {
      if (err.status === 401) {
        onUnauthorized()
        return
      }
      setError(err.message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="composer">
      <label>
        Trend title
        <input
          type="text"
          value={trendTitle}
          onChange={(e) => setTrendTitle(e.target.value)}
          placeholder="Featured trend"
        />
      </label>
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder="Trend summary (optional)"
        aria-label="Trend summary"
      />
      <fieldset className="crossover-fields">
        <legend>Crossover Screen</legend>
        {CROSSOVER_FACTORS.map((f) => (
          <label key={f.key}>
            {f.label}
            <input
              type="text"
              value={factors[f.key]}
              onChange={(e) => setFactors((prev) => ({ ...prev, [f.key]: e.target.value }))}
            />
          </label>
        ))}
        <label>
          Verdict
          <select value={verdict} onChange={(e) => setVerdict(e.target.value)}>
            <option value="">(none)</option>
            {VERDICTS.map((v) => (
              <option key={v} value={v}>
                {v}
              </option>
            ))}
          </select>
        </label>
      </fieldset>
      {citations.length > 0 && (
        <div className="chips-row">
          {citations.map((c) => (
            <CitationChip key={c.post_id} citation={c} onOpen={onOpenPost} onRemove={detach} />
          ))}
        </div>
      )}
      <div className="composer-row">
        <button type="button" onClick={() => setPickerOpen((open) => !open)}>
          {pickerOpen ? 'Hide citation picker' : 'Add citation (optional)'}
        </button>
        <button type="button" className="composer-save" onClick={save} disabled={!canSave}>
          {saving ? 'Saving…' : block ? 'Save changes' : 'Save trend'}
        </button>
        {onCancel && (
          <button type="button" onClick={onCancel}>
            Cancel
          </button>
        )}
      </div>
      {error && <p className="error">{error}</p>}
      {pickerOpen && (
        <CitationPicker
          attachedIds={attachedIds}
          onAttach={attach}
          tray={tray}
          onTrayRemove={onTrayRemove}
          onTrayClear={onTrayClear}
          onUnauthorized={onUnauthorized}
        />
      )}
    </div>
  )
}

function CrossoverTable({ crossover }) {
  return (
    <table className="crossover-table">
      <tbody>
        {CROSSOVER_FACTORS.map((f) => (
          <tr key={f.key}>
            <th>{f.label}</th>
            <td>{crossover[f.key]}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

// A saved block: claim text or trend (title + crossover + nested claims),
// with citation chips, edit-in-place and delete.
function BlockView({
  block,
  reportId,
  sectionKey,
  tray,
  onTrayRemove,
  onTrayClear,
  onOpenPost,
  onBlockAdded,
  onBlockUpdated,
  onBlockDeleted,
  onUnauthorized,
}) {
  const [editing, setEditing] = useState(false)
  const [addingChild, setAddingChild] = useState(false)
  const [error, setError] = useState('')
  const [deleting, setDeleting] = useState(false)

  const isTrend = block.block_type === 'trend'
  const children = [...(block.children || [])].sort(
    (a, b) => (a.sort_order ?? 0) - (b.sort_order ?? 0),
  )

  async function remove() {
    const message = isTrend
      ? 'Delete this trend? Claims nested under it go with it.'
      : 'Delete this claim?'
    if (!window.confirm(message)) return
    setDeleting(true)
    setError('')
    try {
      await api(`/api/blocks/${block.id}`, { method: 'DELETE' })
      onBlockDeleted(sectionKey, block.id)
    } catch (err) {
      if (err.status === 401) {
        onUnauthorized()
        return
      }
      setError(err.message)
    } finally {
      setDeleting(false)
    }
  }

  const shared = {
    reportId,
    tray,
    onTrayRemove,
    onTrayClear,
    onOpenPost,
    onUnauthorized,
  }

  if (editing) {
    const Composer = isTrend ? TrendComposer : ClaimComposer
    return (
      <Composer
        {...shared}
        section={sectionKey}
        block={block}
        onSaved={(saved) => {
          onBlockUpdated(sectionKey, saved)
          setEditing(false)
        }}
        onCancel={() => setEditing(false)}
      />
    )
  }

  return (
    <div className={`report-block block-${block.block_type}`}>
      {isTrend && <h3 className="trend-title">{block.trend_title}</h3>}
      {block.text_content && <p className="block-text">{block.text_content}</p>}
      {isTrend && block.crossover && <CrossoverTable crossover={block.crossover} />}
      {isTrend && block.crossover_verdict && (
        <span className={`badge verdict-${block.crossover_verdict}`}>
          {block.crossover_verdict}
        </span>
      )}
      {block.citations?.length > 0 && (
        <div className="chips-row">
          {block.citations.map((c) => (
            <CitationChip key={c.post_id} citation={c} onOpen={onOpenPost} />
          ))}
        </div>
      )}
      <div className="block-actions">
        <button type="button" onClick={() => setEditing(true)}>
          Edit
        </button>
        <button type="button" onClick={remove} disabled={deleting}>
          {deleting ? 'Deleting…' : 'Delete'}
        </button>
        {isTrend && !addingChild && (
          <button type="button" onClick={() => setAddingChild(true)}>
            Add claim under this trend
          </button>
        )}
      </div>
      {error && <p className="error">{error}</p>}
      {(children.length > 0 || addingChild) && (
        <div className="trend-children">
          {children.map((child) => (
            <BlockView
              key={child.id}
              block={child}
              reportId={reportId}
              sectionKey={sectionKey}
              tray={tray}
              onTrayRemove={onTrayRemove}
              onTrayClear={onTrayClear}
              onOpenPost={onOpenPost}
              onBlockAdded={onBlockAdded}
              onBlockUpdated={onBlockUpdated}
              onBlockDeleted={onBlockDeleted}
              onUnauthorized={onUnauthorized}
            />
          ))}
          {addingChild && (
            <ClaimComposer
              {...shared}
              section={sectionKey}
              parentBlockId={block.id}
              nextSortOrder={nextSort(children)}
              onSaved={(saved) => {
                onBlockAdded(sectionKey, saved)
                setAddingChild(false)
              }}
              onCancel={() => setAddingChild(false)}
            />
          )}
        </div>
      )}
    </div>
  )
}

// Decoder has no blocks by design: it renders from the glossary table at
// export time; here we show a read-only preview.
function DecoderSection({ terms, error }) {
  return (
    <section className="report-section">
      <h2>Consumer Language Decoder</h2>
      <p className="hint">Rendered from the glossary at export time.</p>
      {error && <p className="error">{error}</p>}
      {terms === null && !error && <p className="hint">Loading glossary…</p>}
      {terms !== null && terms.length === 0 && <p className="hint">Glossary is empty.</p>}
      {terms !== null && terms.length > 0 && (
        <div className="table-wrap">
          <table className="glossary-table">
            <thead>
              <tr>
                <th>Term</th>
                <th>English</th>
                <th>Note</th>
                <th>Category</th>
              </tr>
            </thead>
            <tbody>
              {terms.map((t) => (
                <tr key={t.term_zh}>
                  <td>{t.term_zh}</td>
                  <td>{t.term_en}</td>
                  <td>{t.note}</td>
                  <td>{t.category}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}

function Section({
  sectionKey,
  label,
  blocks,
  reportId,
  tray,
  onTrayRemove,
  onTrayClear,
  onOpenPost,
  onBlockAdded,
  onBlockUpdated,
  onBlockDeleted,
  onUnauthorized,
}) {
  const isTrendRadar = sectionKey === 'trend_radar'
  const [mode, setMode] = useState(isTrendRadar ? 'trend' : 'claim')
  const sorted = [...blocks].sort((a, b) => (a.sort_order ?? 0) - (b.sort_order ?? 0))

  const shared = {
    reportId,
    tray,
    onTrayRemove,
    onTrayClear,
    onOpenPost,
    onUnauthorized,
  }

  return (
    <section className="report-section">
      <h2>{label}</h2>
      {sorted.length === 0 && <p className="hint">No blocks yet.</p>}
      {sorted.map((block) => (
        <BlockView
          key={block.id}
          block={block}
          reportId={reportId}
          sectionKey={sectionKey}
          tray={tray}
          onTrayRemove={onTrayRemove}
          onTrayClear={onTrayClear}
          onOpenPost={onOpenPost}
          onBlockAdded={onBlockAdded}
          onBlockUpdated={onBlockUpdated}
          onBlockDeleted={onBlockDeleted}
          onUnauthorized={onUnauthorized}
        />
      ))}
      {isTrendRadar && (
        <div className="composer-tabs">
          <button
            type="button"
            className={mode === 'trend' ? 'tab-active' : ''}
            onClick={() => setMode('trend')}
          >
            New trend
          </button>
          <button
            type="button"
            className={mode === 'claim' ? 'tab-active' : ''}
            onClick={() => setMode('claim')}
          >
            New claim
          </button>
        </div>
      )}
      {isTrendRadar && mode === 'trend' ? (
        <TrendComposer
          {...shared}
          nextSortOrder={nextSort(sorted)}
          onSaved={(saved) => onBlockAdded(sectionKey, saved)}
        />
      ) : (
        <ClaimComposer
          {...shared}
          section={sectionKey}
          nextSortOrder={nextSort(sorted)}
          onSaved={(saved) => onBlockAdded(sectionKey, saved)}
        />
      )}
    </section>
  )
}

// The trust loop: clicking a citation chip opens the source post — images,
// Chinese, English, annotation — without leaving the editor. Esc or X closes.
function SourcePanel({ postId, onClose, onUnauthorized }) {
  const [post, setPost] = useState(null)
  const [error, setError] = useState('')

  useEffect(() => {
    let alive = true
    setPost(null)
    setError('')
    api(`/api/posts/${postId}`)
      .then((data) => {
        if (alive) setPost(data)
      })
      .catch((err) => {
        if (err.status === 401) {
          onUnauthorized()
          return
        }
        if (alive) setError(err.message)
      })
    return () => {
      alive = false
    }
  }, [postId, onUnauthorized])

  useEffect(() => {
    function onKey(e) {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const chinese = post ? post.corrected_text || post.full_ocr_text || '' : ''
  const english = post ? post.final_translation || post.machine_translation || '' : ''
  const annotation = post?.annotation

  return (
    <aside className="source-panel" aria-label="Source post">
      <div className="source-panel-head">
        <h2>Source post</h2>
        <button type="button" className="source-panel-close" onClick={onClose} aria-label="Close">
          ×
        </button>
      </div>
      {error && <p className="error">{error}</p>}
      {!post && !error && <p>Loading…</p>}
      {post && (
        <>
          <p>
            <Link to={`/posts/${post.id}`}>Open full post view</Link>
          </p>
          {annotation && (
            <div className="chips-row">
              {[
                annotation.category,
                annotation.consumer_signal,
                annotation.recommended_action,
                annotation.origin,
              ]
                .filter(Boolean)
                .map((value) => (
                  <span key={value} className="badge badge-pending">
                    {value}
                  </span>
                ))}
            </div>
          )}
          {annotation?.notes && <p className="hint">{annotation.notes}</p>}
          <h3>Chinese</h3>
          {post.caption_raw && <pre>{post.caption_raw}</pre>}
          <pre>{chinese || '(not yet available)'}</pre>
          <h3>English</h3>
          <pre>{english || '(not yet available)'}</pre>
          <h3>Images</h3>
          {(post.images || []).length === 0 && <p className="hint">No images.</p>}
          {(post.images || []).map((img) => (
            <img key={img.id} src={img.url} alt={img.image_type || 'image'} />
          ))}
        </>
      )}
    </aside>
  )
}

export default function ReportEditor() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [meta, setMeta] = useState(null) // {id, title, week_of, status}
  const [sections, setSections] = useState(null) // key -> top-level blocks
  const [loadError, setLoadError] = useState('')
  const [glossary, setGlossary] = useState(null)
  const [glossaryError, setGlossaryError] = useState('')
  const [panelPostId, setPanelPostId] = useState(null)
  const [tray, setTray] = useState(readTray)
  const [title, setTitle] = useState('')
  const [weekOf, setWeekOf] = useState('')
  const [headerError, setHeaderError] = useState('')
  const [savingHeader, setSavingHeader] = useState(false)

  const onUnauthorized = useCallback(() => navigate('/login'), [navigate])

  useEffect(() => {
    let alive = true
    api(`/api/reports/${id}`)
      .then((data) => {
        if (!alive) return
        setMeta({ id: data.id, title: data.title, week_of: data.week_of, status: data.status })
        setTitle(data.title || '')
        setWeekOf(data.week_of || '')
        const loaded = {}
        for (const key of BLOCK_SECTIONS) loaded[key] = data.sections?.[key] || []
        setSections(loaded)
      })
      .catch((err) => {
        if (err.status === 401) {
          onUnauthorized()
          return
        }
        if (alive) setLoadError(err.message)
      })
    api('/api/glossary')
      .then((data) => {
        if (alive) setGlossary(data.terms)
      })
      .catch((err) => {
        if (err.status === 401) {
          onUnauthorized()
          return
        }
        if (alive) setGlossaryError(err.message)
      })
    return () => {
      alive = false
    }
  }, [id, onUnauthorized])

  // --- local block-state updates (no full-page reloads on save) ---

  const onBlockAdded = useCallback((sectionKey, block) => {
    setSections((prev) => {
      const list = prev[sectionKey] || []
      if (block.parent_block_id) {
        return {
          ...prev,
          [sectionKey]: list.map((b) =>
            b.id === block.parent_block_id
              ? { ...b, children: [...(b.children || []), block] }
              : b,
          ),
        }
      }
      return { ...prev, [sectionKey]: [...list, { ...block, children: block.children || [] }] }
    })
  }, [])

  const onBlockUpdated = useCallback((sectionKey, block) => {
    setSections((prev) => ({
      ...prev,
      [sectionKey]: (prev[sectionKey] || []).map((b) => {
        // Preserve children if the PATCH response omits them.
        if (b.id === block.id) return { ...block, children: block.children ?? b.children ?? [] }
        if (b.children?.some((c) => c.id === block.id)) {
          return { ...b, children: b.children.map((c) => (c.id === block.id ? block : c)) }
        }
        return b
      }),
    }))
  }, [])

  const onBlockDeleted = useCallback((sectionKey, blockId) => {
    setSections((prev) => ({
      ...prev,
      [sectionKey]: (prev[sectionKey] || [])
        .filter((b) => b.id !== blockId)
        .map((b) =>
          b.children?.length
            ? { ...b, children: b.children.filter((c) => c.id !== blockId) }
            : b,
        ),
    }))
  }, [])

  // --- tray (shared across all composers on the page) ---

  const onTrayRemove = useCallback((postId) => setTray(removeFromTray(postId)), [])
  const onTrayClear = useCallback(() => setTray(clearTray()), [])
  const onOpenPost = useCallback((postId) => setPanelPostId(postId), [])

  // --- report header ---

  const headerDirty =
    meta !== null && (title !== (meta.title || '') || (weekOf || '') !== (meta.week_of || ''))

  async function saveHeader() {
    if (!title.trim() || savingHeader) return
    setSavingHeader(true)
    setHeaderError('')
    try {
      const updated = await patchJson(`/api/reports/${id}`, {
        title,
        week_of: weekOf || null,
      })
      setMeta((m) => ({ ...m, title: updated.title ?? title, week_of: updated.week_of ?? null }))
    } catch (err) {
      if (err.status === 401) {
        onUnauthorized()
        return
      }
      setHeaderError(err.message)
    } finally {
      setSavingHeader(false)
    }
  }

  async function toggleStatus() {
    const next = meta.status === 'final' ? 'draft' : 'final'
    setHeaderError('')
    try {
      const updated = await patchJson(`/api/reports/${id}`, { status: next })
      setMeta((m) => ({ ...m, status: updated.status ?? next }))
    } catch (err) {
      if (err.status === 401) {
        onUnauthorized()
        return
      }
      setHeaderError(err.message)
    }
  }

  if (loadError) {
    return (
      <main className="page">
        <p className="error">{loadError}</p>
      </main>
    )
  }
  if (!meta || !sections) {
    return (
      <main className="page">
        <p>Loading…</p>
      </main>
    )
  }

  return (
    <main className="page report-editor">
      <header className="report-head">
        <input
          type="text"
          className="report-title-input"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          aria-label="Report title"
        />
        <input
          type="date"
          value={weekOf || ''}
          onChange={(e) => setWeekOf(e.target.value)}
          aria-label="Week of"
        />
        {headerDirty && (
          <button type="button" onClick={saveHeader} disabled={savingHeader || !title.trim()}>
            {savingHeader ? 'Saving…' : 'Save'}
          </button>
        )}
        <span className={`badge status-${meta.status}`}>{meta.status}</span>
        <button type="button" onClick={toggleStatus}>
          {meta.status === 'final' ? 'Back to draft' : 'Mark final'}
        </button>
        <Link to={`/export?report=${meta.id}`}>Open export preview</Link>
      </header>
      {headerError && <p className="error">{headerError}</p>}
      {SECTIONS.map(({ key, label }) =>
        key === 'decoder' ? (
          <DecoderSection key={key} terms={glossary} error={glossaryError} />
        ) : (
          <Section
            key={key}
            sectionKey={key}
            label={label}
            blocks={sections[key] || []}
            reportId={meta.id}
            tray={tray}
            onTrayRemove={onTrayRemove}
            onTrayClear={onTrayClear}
            onOpenPost={onOpenPost}
            onBlockAdded={onBlockAdded}
            onBlockUpdated={onBlockUpdated}
            onBlockDeleted={onBlockDeleted}
            onUnauthorized={onUnauthorized}
          />
        ),
      )}
      {panelPostId && (
        <SourcePanel
          postId={panelPostId}
          onClose={() => setPanelPostId(null)}
          onUnauthorized={onUnauthorized}
        />
      )}
    </main>
  )
}
