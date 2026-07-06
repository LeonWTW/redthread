# Plan 003 — UI Redesign: "Editorial Intelligence" + RedThread Logo

**Status: APPROVED.** Leon approved this plan in-session on 2026-07-06 (plan-mode
acceptance), after locking three design decisions via structured questions:
art direction = Editorial Intelligence, logo = Thread-stitch R, export
deliverable = untouched.

## Context

Leon is dissatisfied with the current UI. The client was deliberately built
"fast, not pretty" (`app.css:1`); it has no brand identity, no logo, one
animation, and raw hex values throughout. Leon explicitly requested a full UI
redesign in a modern, premium-minimal direction, with tasteful animation, plus
a RedThread logo on the web app.

Constitution note (questioned once, per CLAUDE.md §1): CLAUDE.md positions
analyst screens as "fast-not-pretty". Leon — the only user — explicitly
requested this upgrade. Resolution: **visual layer only**. Nothing may slow the
two loops: keyboard map, API calls, polling, routes, and workflow logic are
untouched; the 30s/post triage metric remains the counter-metric every choice
is checked against.

Decisions locked by Leon (2026-07-06):

1. **Art direction: Editorial Intelligence** — paper + ink + one thread-red
   accent; serif display (New York) / SF Pro UI / SF Mono data.
2. **Logo: Thread-stitch R** — one continuous red thread stroke forming an R;
   stitch-dot start, tail extends into an underline; wordmark beside it; same
   mark as favicon.
3. **Export deliverable untouched** — the PDF/public-HTML template is not
   modified by one byte. Report branding = future separate plan.

## Current state (verified by inventory)

- One stylesheet: `client/src/app.css` (357 lines), imported once at
  `App.jsx:12`. Zero inline styles, no CSS modules/Tailwind/webfonts. JSX
  already uses stable semantic class names.
- Inconsistencies to collapse: two parallel status-pill systems (`.step-*` vs
  `.badge-*`), black-primary button rules written 5×, 5 ad-hoc text grays + 5
  border grays, radius values 2/3/4/12px mixed, `font: inherit` repeated ~30×,
  disabled pattern repeated ~9×, one stray blue active state in ExportPreview.
- Mobile constraints that must survive: ≥44px tap targets on Capture/Login
  (iPhone flow), breakpoint collapses at 800/900px.

## Non-goals (hard)

- NO dark mode (anti-requirement; no `prefers-color-scheme` blocks). NO sixth
  screen, settings, dashboards, onboarding, notifications.
- NO new npm dependencies — hand-rolled CSS + inline SVG only. `package.json`
  byte-identical.
- NO changes to: server code, export template (`server/app/export/`), Triage
  keyboard handling/hotkey map, API contracts, routes, polling logic.
- English UI copy; source Chinese preserved everywhere.

## Design system spec

### Tokens — new file `client/src/styles/tokens.css`

```
Surfaces   --paper #FAF9F6 (page) · --paper-raised #FFFFFF (cards) · --paper-sunken #F3F1EC (wells)
Ink        --ink #16130F · --ink-2 #57534B (secondary) · --ink-3 #8A857B (meta)
Lines      --line #E7E3DB (hairline) · --line-strong #D6D1C6 (inputs/hover)
Brand      --thread #C41E2A · --thread-deep #9E1622 (hover/danger) · --thread-tint #F9ECEB (wash)
Status     ok #2E7D32/#EAF4EC/#B7D8BC · run #1E5FA8/#E9F1FA/#B4CDE8 · fail #B3261E/#FBEDEB/#EFC2BD · warn #9A6B00/#FBF3DC/#E8D49A
Fonts      display: ui-serif "New York" · ui: SF Pro system stack · mono: SF Mono stack
Radius     --r-ctl 6px · --r-card 10px · --r-pill 999px
Shadows    --shadow-1 (cards) · --shadow-2 (hover lift) · --shadow-panel (side panel)
Motion     --dur-fast 120ms · --dur 180ms · --dur-slow 260ms · --ease cubic-bezier(0.16,1,0.3,1)
Focus      thread-tinted ring, :focus-visible everywhere
```

Brand red vs error red: status badges always carry a tinted background + the
status word; brand red appears only as bare accents (logo, active-nav
underline, title hairline, links, danger buttons) — form factor disambiguates.

### `client/src/app.css` rewritten as the component + screen layer

- **Buttons**: one global `button` base (font, radius, border, hover, focus,
  press, disabled) + variants (primary ink fill on form CTAs / `.anno-save` /
  `.composer-save`; `.btn-danger` for deletes; quiet default).
- **Badges**: one unified status-pill system (mono uppercase 11px, tinted bg,
  status dot via `::before`); `.step-*` aliased to the same triplets so
  Capture/PostView need zero JSX churn; running keeps the pulse (dot only).
  Annotation *tags* move from `.badge` to `.chip` (tags ≠ statuses).
- **Cards**: shared surface treatment on `.library-card`, `.report-block`,
  `.table-wrap`, `.cite-picker`, capture `.section`, PostView `.col`.
- **Tables**: shared treatment (overline uppercase thead, hairline rows,
  row-hover wash) for inbox/report/glossary/crossover.
- **Inputs**: shared styling with thread focus ring; existing `.anno-key`
  spans rendered as mono mini-keycaps.
- Messages (`.error`, `.hint`, `.notice-warn`), merged chip family, skeleton
  shimmer rows, subtle custom scrollbar.

### Motion (CSS-only, compositor-friendly: transform/opacity)

Page enter fade-rise 260ms; card hover lift; nav/tab active underline scaleX;
citation-chip pop-in; source panel slide-in; running-dot pulse; skeleton
shimmer; Library staggered entry (capped); Login logo stroke-draw (~900ms,
once). Global `@media (prefers-reduced-motion: reduce)` kill switch. Triage
rule: nothing on the annotate path animates longer than 120ms; selection
feedback is background-color only.

### Logo — `client/src/components/Logo.jsx` + `client/public/favicon.svg`

Inline SVG, 32×32 viewBox: one continuous thread-red path drawing an R
(stitch-dot start, round caps), tail exiting as an underline ending in a dot.
Recognizable at 16px. `<Logo size withWordmark />`; wordmark "RedThread" in
display serif, ink (the mark carries the red). Placements: Nav brand, Login
hero (draw-in animation), favicon + `theme-color` in `index.html`.

### Per-screen treatments

| Screen | Treatment (visual only) |
|---|---|
| Nav | Sticky, paper blur, hairline bottom; logo left; active link = ink text + thread underline; logout quiet |
| Login | Centered card, logo draw-in, serif heading, refined form, error shake |
| Capture | Three method cards with overline labels; styled drop zone; unified badges; ≥44px targets kept |
| Inbox | Serif title + thread rule; table in card shell; dot-badges; failed rows get a thread left rail; skeleton first load |
| Triage | Grid/keys untouched; hotkey pill status bar; serif queue count; mono timer; keycap hints; selected = ink fill |
| Library | Larger search bar w/ magnifier icon; hover-lift cards, mono score, staggered entry; annotation tags as chips |
| Reports | Create-form card + shared table |
| Report Editor | Sticky head (≥900px); sections numbered editorially (mono "01" in thread red + serif h2) — five locked sections, order unchanged; blocks as cards; sunken composer; sliding source panel |
| Export Preview | Refined toolbar; segmented toggle active = ink; iframe framed. Iframe CONTENT untouched |
| PostView | Unified badges; three labeled column cards |

## Implementation steps & routing

0. `[fable]` Pre-flight (`git status` clean ✓); this plan file; ai-log append.
1. `[fable]` Design core: `styles/tokens.css`, `app.css` rewrite, `Logo.jsx`,
   `favicon.svg`, `index.html`, `App.jsx` import, `Nav.jsx`, `Login.jsx`.
2. `[sonnet]` Two parallel implementer dispatches, mechanical JSX only:
   - A: `Inbox.jsx` (skeleton, failed-row class), `Triage.jsx` (hotkey strip
     label, keycap glyphs), `PostView.jsx` (labels)
   - B: `Capture.jsx` (drop zone), `Library.jsx` (icon, tags→chips, skeleton),
     `Reports.jsx`, `ReportEditor.jsx` (danger classes), `ExportPreview.jsx`
3. `[fable]` Review diffs; restart client; fix round (escalate on one failure).
4. `[fable]` Verification + docs + commits.

## Verification

- `docker compose exec client npm run build` green (container = canonical env).
- `git diff --stat`: only `client/` + docs touched; `package.json` and
  `server/` untouched.
- Grep guards: no `prefers-color-scheme`; `prefers-reduced-motion` present; no
  hardcoded hex in `app.css` (tokens only; alphas via `color-mix`).
- `docker compose exec api pytest -q` still 183 passed (server untouched).
- Visual: screenshot Login at 1440/768/390; Leon walks the five screens
  logged-in + Capture at iPhone width; Triage hotkeys 1/Q/A/7/Enter unchanged.
- Note: `docs/verification/009-ui-redesign.md`.

## Commits (on `main`, then fast-forward `sprint-2-prototype`)

1. `feat: design tokens, base design system, and RedThread logo`
2. `feat: restyle all screens to editorial intelligence direction`
3. `docs: plan 003, verification 009, ai-log`

Each with `AI-Assisted: yes (scope: per approved plan docs/plans/003)`.
