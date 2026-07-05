// localStorage-backed citation tray shared by Library ("Add to report") and
// the Report Editor's citation picker. Items are plain objects:
// { post_id, zh_snippet, en_snippet, first_image_url } — deduped by post_id.

const KEY = 'redthread.citationTray'

export function readTray() {
  try {
    const raw = localStorage.getItem(KEY)
    const list = raw ? JSON.parse(raw) : []
    return Array.isArray(list) ? list : []
  } catch {
    // Corrupt or unavailable storage: start from an empty tray.
    return []
  }
}

function write(list) {
  try {
    localStorage.setItem(KEY, JSON.stringify(list))
  } catch {
    // Storage full/unavailable: the in-memory list still works for this page.
  }
  return list
}

// Returns { tray, added } — added=false when the post was already in the tray.
export function addToTray(item) {
  const tray = readTray()
  if (tray.some((it) => it.post_id === item.post_id)) return { tray, added: false }
  return { tray: write([...tray, item]), added: true }
}

export function removeFromTray(postId) {
  return write(readTray().filter((it) => it.post_id !== postId))
}

export function clearTray() {
  return write([])
}
