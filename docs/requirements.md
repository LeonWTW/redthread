# Requirements

## Functional Requirements

Capture

- The system should let the analyst upload one or more screenshot images from a mobile browser (batch upload, drag-and-drop or photo picker).
- The system should let the analyst paste a Xiaohongshu post URL; when a note ID can be parsed from the URL, the system should detect and report duplicates instead of creating a second record.
- The system should support CSV import for batches of post URLs or metadata.
- The system should expose an authenticated capture API endpoint so trusted external clients can submit captures.
- The system should warn (but not block) when a newly uploaded image is visually near-identical to one already in the corpus.
- The system should treat a post as possibly having many images (Xiaohongshu posts are often multi-image carousels), including screenshots of the comment section marked as comment evidence.

Enrichment pipeline

- The system should run each captured post through a pipeline: OCR per image → translation → entity extraction → embedding.
- The system should record per-step pipeline status for every post and let the analyst retry any failed step individually.
- The system should make every pipeline step idempotent: re-running a step must not duplicate data or corrupt state.
- The system should store machine outputs and analyst corrections separately (raw OCR vs. corrected text; machine translation vs. final translation).
- The system should re-embed a post automatically when the analyst corrects its text or translation.
- The system should call all AI services (OCR, translation, extraction, embedding) through provider interfaces so a provider can be swapped by configuration without code changes.
- The system should inject a maintained Chinese–English glossary of community terms (e.g., 避雷, 平替, 成分党) into translation so domain slang is rendered consistently.

Triage and annotation

- The system should present a three-pane review screen: source image(s); OCR text, translation, and extracted entities (inline-editable; entities carry a model self-reported confidence heuristic — not a calibrated probability; OCR and translation do not display confidence); and an annotation panel.
- The system should support keyboard-first annotation with hotkeys for category, consumer signal, optional trend origin, save-and-next, and skip.
- The system should record annotations against a fixed taxonomy (values listed under Data Requirements).

Library and search

- The system should provide semantic search over the corpus that works for English queries, Chinese queries, and mixed queries.
- The system should display results as cards showing the bilingual content and annotations, with an action to add a post to a report.

Report building and export

- The system should let the analyst assemble a weekly report from an outline, where claims are attached to citation chips referencing captured posts.
- The system should make it structurally impossible to add a claim sentence to a report without at least one citation.
- The system should let the analyst open any citation's source post in a side panel for verification while editing.
- The system should render reports as styled HTML and export them to PDF, and support a public web variant of the same template.
- The system should render a consumer-language decoder section of the report from the glossary data.

## Data Requirements

- The system needs to store posts: unique ID, optional Xiaohongshu note ID (unique when present), capture timestamp (UTC), raw caption, aggregated OCR text and corrected text, machine translation and final translation, pipeline status, and embedding status.
- The system needs to store post images: ordering within the post, image type (note content / comments / other), the image file reference, per-image raw and corrected OCR, and a perceptual hash for duplicate warning.
- The system needs to store annotations against a fixed taxonomy:
  - category: skincare | makeup | haircare | wellness
  - trend_type: ingredient | routine | pain_point | product_format | creator_format | brand_move
  - consumer_signal: bilei (避雷) | pingti (平替) | chengfen_dang (成分党) | zhongcao (种草) | qiuzhen (求真)
  - recommended_action: monitor | test_content | seed_koc | avoid
  - origin (optional): china_native | west_to_china | pan_asian | unclear
  - free-text notes
- The system needs to store a glossary of community terms: Chinese term, English rendering, explanatory note, category.
- The system needs to store reports and their citation links to posts.
- The system needs to manage vector embeddings (one per post) in a vector database, kept consistent with the relational store when corrections occur.
- The system needs to manage uploaded media files privately: stored on the server and served only through authenticated application routes, never as public static files.
- The system needs to maintain a 20-post golden set with human-verified ground truth (correct OCR, translation, entities, annotations) used to evaluate AI providers on accuracy and cost.

## Non-Functional Requirements

- The system should be understandable and maintainable by a single developer: boring, well-known technology choices; providers behind interfaces; a single schema file as the source of truth.
- The system should start with one command via Docker Compose.
- The system should meet concrete workflow performance targets: capture-plus-annotate in ≤30 seconds per post; weekly report production in ≤1 hour; ≥90% of captures completing the pipeline without manual intervention; a relevant result in the top 5 for at least 4 of 5 representative search queries.
- The system should protect data appropriately: a single analyst account with session authentication on every route including media, a token-authenticated capture API, rate limiting on login, and secrets supplied only through environment variables (never committed).
- The system should protect the corpus against loss: automated nightly database and media backups to off-server storage, with a documented restore procedure exercised monthly.
- The system should operate within an explicit cost ceiling for AI services: at most $0.05 per post processed and $50 per month, with provider evaluation reporting cost alongside accuracy.
- The system should preserve source Chinese text alongside every translation throughout the interface and exports; bilingual transparency is a core quality of the product.
- The system should remain compliant with its collection posture: content is manually curated by the analyst for research and analysis purposes; the system does not perform automated bulk collection.

## Out of Scope for the First Version

- This version will not include a client-facing portal, client accounts, or any client-visible interface beyond exported documents.
- This version will not include a standalone chat or question-answering interface over the corpus.
- This version will not include a browser clipper extension.
- This version will not include multi-user support, roles, or permissions.
- This version will not include analytics dashboards, engagement charts, or computed trend scores.
- This version will not include settings pages, onboarding flows, notifications, dark mode, or an undo system.
- This version will not cover platforms other than Xiaohongshu or content categories other than beauty and wellness.
- This version will not perform any automated scraping, crawling, or bulk collection of platform content.
