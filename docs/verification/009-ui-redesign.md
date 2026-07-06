# 009 — UI redesign: "Editorial Intelligence" + RedThread logo (plan 003)

Scope: visual layer only. Design tokens (`client/src/styles/tokens.css`),
full `client/src/app.css` rewrite, inline-SVG logo (`Logo.jsx` +
`public/favicon.svg`), Nav/Login rebuild, mechanical JSX class application on
the remaining pages. Server, export template, keyboard map, API contracts,
and dependencies untouched by design.

## What was tested / steps / expected / actual

### 1. Production build (canonical env = compose client container)

- Step: `docker compose exec client npm run build`
- Expected: exit 0, CSS within the 50 kB app budget.
- Actual: **exit 0** — `index-DBfg9GhP.css 26.84 kB (gzip 5.88 kB)`,
  JS 219.05 kB (gzip 68.44 kB, unchanged baseline). Zero webfonts added.

### 2. Server untouched

- Step: `git diff --name-only -- server/` → expected empty; ran
  `docker compose exec api pytest -q`.
- Actual: **0 server files changed; 183 passed in 3.17s.**
- `package.json` / `package-lock.json`: byte-identical (verified with raw
  `git diff --name-only`; an earlier rtk-compressed pipe suggested otherwise
  — false alarm).

### 3. Grep guards

- No `prefers-color-scheme` block anywhere in client (only the tokens.css
  comment stating the anti-requirement). Dark mode remains impossible.
- `@media (prefers-reduced-motion: reduce)` present (global animation kill +
  logo static fallback).
- No raw hex in `app.css` — all color goes through tokens; alpha via
  `color-mix`. Literal hex lives only in `tokens.css` and the standalone
  `favicon.svg`.

### 4. Visual QA (Playwright chromium inside the api container)

Method: headless chromium (already shipped in the api image for PDF export)
navigated to the vite dev server over the compose network; the analyst
credentials were read from the container environment (never typed through
any transcript). 12 screenshots across two rounds: login/capture at 1440 +
390, inbox/triage/library/reports/export/editor at 1440. Editor was captured
via a throwaway report created and deleted through the API (DELETE → 204).

Expected → actual:
- Logo mark reads as an "R" at nav size and favicon size — **yes**.
- Login: centered card, stroke-draw animation, serif wordmark — **yes**.
- Inbox: serif title + thread rule, card table, dot badges, failed rows
  carry the 2px thread left rail, mono timestamps — **yes**.
- Triage: HOTKEYS ON pill (green dot), serif queue count, mono timer, keycap
  hints on every option/action button — **yes**; grid + hotkey wiring
  untouched (JSX diff shows zero handler changes).
- Report editor: sticky head, serif title input, `01`-numbered sections in
  thread red, sunken composer, disabled Save claim until citations exist —
  **yes** (citation gate copy visible in the shot).
- Capture at 390: drop zone, ≥44px controls, truthful format hint — **yes**.

### 5. Issues found during QA and fixed

1. **Input specificity bug**: the global
   `input:not([type=checkbox]):not([type=radio])` base (specificity 0,2,1)
   silently beat component selectors like `.library-search input` (0,1,1) —
   search-icon padding and the report-title serif styling never applied.
   Fix: wrap the global base in `:where(...)` (specificity 0). Round-2
   screenshots confirm both now render.
2. **Drop-zone bypassed the disabled state**: the file input is disabled
   while `busy || processing`, but the new label-level `onDrop` was not —
   dropping files mid-upload would have reset the in-flight queue. Fix:
   same guard on the drop handler.
3. **Stale page copy**: Capture h1 read "RedThread — Capture"; redundant
   next to the nav wordmark → now "Capture".

### 6. Known non-issues (out of scope, pre-existing)

- Console shows React Router v7 future-flag warnings — pre-existing,
  unrelated to styling.
- Four thumbnail 404s on Inbox: media files for July-5 pipeline test posts
  no longer exist on the media volume (containers were force-recreated
  during the M8 password rotation). Data cleanup, not a UI defect — those
  junk posts can be deleted in Library.

## What changed

- New: `client/src/styles/tokens.css`, `client/src/components/Logo.jsx`,
  `client/public/favicon.svg`.
- Rewritten: `client/src/app.css` (357 → ~1050 lines, tokenized, one badge
  system, one button system, shared card/table/input treatments, motion with
  reduced-motion kill switch).
- Edited: `index.html` (favicon, theme-color), `App.jsx` (tokens import),
  `Nav.jsx` (brand lockup, underline active state), `Login.jsx` (card +
  draw-in logo), `Inbox.jsx` (skeleton, row-failed), `Triage.jsx` (hotkey
  pill label, keycap glyphs), `Capture.jsx` (drop zone + guard, h1),
  `Library.jsx` (search icon, tags→chips, danger delete),
  `ReportEditor.jsx` (danger classes).

## Leon's acceptance walkthrough (open items)

- Walk the five screens logged-in at desktop width; Capture from iPhone.
- Triage feel-check: hotkeys 1/Q/A/7/Enter, per-post rhythm unchanged
  (annotate-path transitions are capped at 120ms).
- Optional cleanup: delete the July-5 test posts with missing media.
