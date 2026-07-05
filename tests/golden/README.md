# Golden set (provider eval ground truth)

Iron law #4: a 20-post golden set with human ground truth drives provider
eval; the eval script outputs accuracy x cost per provider. No provider
debates without eval numbers.

This directory holds that golden set. Target size: 20 real XHS posts with
analyst-verified ground truth. Until real posts are added, one synthetic
entry (`posts/example-synthetic/`) exists so the harness and its tests have
a known-good structure to validate against. Replace it with — or keep it
alongside — real entries; the harness treats every subdirectory of `posts/`
as one golden post.

## Directory structure

```
tests/golden/posts/<slug>/
  images/*.png|jpg|jpeg   # screenshot(s); optional for caption-only posts
  ground_truth.json       # human-verified ground truth (see below)
```

`ground_truth.json` schema:

```json
{
  "caption_raw": "optional Chinese caption pasted at capture time",
  "ocr_text": "required — the full correct transcription of images/ (Chinese stays Chinese)",
  "translation": "required — the correct English translation of the post text",
  "entities": [
    {"text_zh": "防晒霜", "text_en": "sunscreen", "type": "product", "confidence": 1.0}
  ],
  "annotation": {
    "category": "skincare",
    "trend_type": "product_format",
    "consumer_signal": "zhongcao",
    "recommended_action": "monitor",
    "origin": "china_native"
  }
}
```

Notes:
- `entities[].type`: brand | product | ingredient | other. `confidence` is
  optional in ground truth (it is a model self-report, not a human field).
- `annotation.origin` is optional (nullable in the schema).
- Chinese is DATA: never transliterate or strip it from ground truth.
- Multiple images are OCR-scored as one aggregate, joined in filename order,
  matching the pipeline's per-post aggregation.

## Running the eval

From the repo root (the harness runs inside the api container):

```bash
# Structure check only — no API calls, no keys needed, exits 0
python scripts/eval_providers.py

# Live eval (calls providers; costs money)
python scripts/eval_providers.py --live \
    --steps ocr,translation,extraction \
    --providers ocr=anthropic --providers translation=anthropic \
    --json /golden/eval-results.json   # lands at tests/eval-results.json
```

Output: an aligned table with accuracy AND per-post cost side by side, plus
a $0.05/post ceiling check per row and for the combined total. Update the
`PRICE_USD_PER_MTOK` table in `server/app/eval/harness.py` (entries are
marked UPDATE ME) before trusting cost numbers.

Scoring metrics (coarse ranking proxies — the analyst reads the table, the
metric only ranks providers):
- OCR: character-level similarity (SequenceMatcher ratio, whitespace-normalized).
- Translation: token-level F1 (lowercase, simple word split).
- Extraction: precision/recall/F1 on (type, text_zh) entity pairs.

## The synthetic example

`posts/example-synthetic/` is marked `"synthetic": true` in its
ground_truth.json. Its PNG was rendered with PIL: the api container image
ships no fonts at all, so a CJK-capable font (Hiragino Sans GB) was mounted
from the macOS host at generation time to render the Chinese sentence
这个防晒霜很好用. It exercises the full entry structure; it is not evidence
of real-world OCR quality — that is what the 20 real posts are for.
