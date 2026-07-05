# Verification 004 — M4 Triage Screen

Date: 2026-07-05 · Plan: docs/plans/001-mvp-plan.md §M4
Built via dynamic workflow wf_419defd1-e4b (annotation-api + triage-screen
parallel + fresh-context verifier). Verifier: 7/7 PASS.

## What was tested

1. **Full suite** — **125 passed** (111 + 14 new annotation tests: upsert
   create→update→explicit-null-clear with single-row assertion; every enum
   field rejects invalid values with 400 naming the field, nothing persisted;
   notes-only annotation; has_annotation filters + order asc/desc + invalid
   param 400; GET post carries annotation; 401/404 paths).
2. **Client build** — exit 0 (Docker build canonical; host-side npm quirk is a
   known npm optional-deps platform issue, not code).
3. **Live annotation flow** — token capture → PUT annotation → partial update
   retains other fields → filters reflect state → invalid enum 400 with exact
   message → cascade cleanup. All live via running api container.
4. **Triage screen code audit with line evidence** — locked hotkey map bound
   exactly (1-4 / Q-T / A-H / 7-9-0 / Z-X-C-V / Enter / Backspace); hotkeys
   disabled while typing (Escape returns to hotkey mode, visual indicator);
   Save & Next PATCHes only changed text fields then PUTs annotation;
   Backspace advances with zero writes; same-key toggle-off to null.
5. **Scope check** — client agent touched client/src only; server agent
   touched routes/posts.py + tests only; no new dependencies.

## Design notes

- Annotation enum validation lists come from the SQLAlchemy ENUM objects that
  mirror schema.sql — never hardcoded (single source of truth held).
- Triage queue: oldest-first un-annotated posts; per-post mm:ss timer surfaces
  the 30s counter-metric to the analyst continuously.
- The real 30s stopwatch walkthrough requires Leon + real captured posts
  (dogfood week, M8); the mechanical path is keyboard-complete per audit.

## What changed

routes/posts.py (annotation upsert endpoint, list filters, annotation in post
JSON); tests/test_annotations.py; client Triage.jsx + route + styles.
