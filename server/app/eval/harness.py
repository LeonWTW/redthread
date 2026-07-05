"""Golden-set provider eval harness (iron law #4).

A 20-post golden set with human ground truth drives provider eval; this
script reports accuracy AND per-post cost side by side. No provider debates
without eval numbers, and cost is a first-class metric, not a footnote.

Usage (inside the api container; see scripts/eval_providers.py for the
host-side wrapper):

    python -m app.eval.harness --golden /golden/golden/posts \
        --steps ocr,translation,extraction \
        --providers ocr=anthropic --providers translation=anthropic \
        --json /golden/eval-results.json --live

Without --live the harness only validates the golden-set structure and
prints the run plan, then exits 0 — safe for CI without API keys.

Scoring (coarse proxies by design — the analyst reads the table, the
metric only ranks providers):
- OCR: character-level similarity (difflib.SequenceMatcher ratio) on
  whitespace-normalized text.
- Translation: token-level F1 (lowercase, simple word split) vs the human
  ground-truth translation. This is a coarse proxy; it ranks, it does not
  grade absolute quality.
- Extraction: entity precision/recall/F1 matched on (type, text_zh) pairs.

Cost: anthropic SDK responses expose usage.input_tokens/output_tokens; the
harness instruments messages.create to capture them per post and prices
them with PRICE_USD_PER_MTOK. Each row carries a $0.05/post ceiling check
(the runtime budget is <= $0.05/post across ALL pipeline steps combined,
so the per-step check is necessary-not-sufficient; the summary line checks
the combined total).
"""

from __future__ import annotations

import argparse
import contextlib
import difflib
import json
import os
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from statistics import mean

# --- Pricing (USD per million tokens) ----------------------------------------
# UPDATE ME: verify against the provider price pages before trusting cost
# numbers in an eval conclusion. Keys are matched by model-id prefix.
PRICE_USD_PER_MTOK: dict[str, dict[str, float]] = {
    "claude-haiku-4-5": {"input": 1.00, "output": 5.00},  # UPDATE ME
    "text-embedding-3-small": {"input": 0.02, "output": 0.00},  # UPDATE ME
}

COST_CEILING_USD_PER_POST = 0.05

STEPS = ("ocr", "translation", "extraction")

_ENV_VAR_BY_STEP = {
    "ocr": "OCR_PROVIDER",
    "translation": "TRANSLATION_PROVIDER",
    "extraction": "EXTRACTION_PROVIDER",
}

_DEFAULT_PROVIDERS = {
    "ocr": "anthropic",
    "translation": "anthropic",
    "extraction": "anthropic",
}

_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg"}

_ANNOTATION_REQUIRED_KEYS = (
    "category",
    "trend_type",
    "consumer_signal",
    "recommended_action",
)


# --- Golden-set loading / validation ------------------------------------------


class GoldenSetError(Exception):
    """Structural problem in the golden set; message names the entry + reason."""


@dataclass(frozen=True)
class GoldenPost:
    slug: str
    ground_truth: dict
    image_paths: tuple[Path, ...] = field(default_factory=tuple)


def _fail(slug: str, reason: str) -> GoldenSetError:
    return GoldenSetError(f"golden post '{slug}': {reason}")


def _require_str(slug: str, obj: dict, key: str, where: str) -> None:
    value = obj.get(key)
    if not isinstance(value, str) or not value.strip():
        raise _fail(slug, f"{where} '{key}' must be a non-empty string")


def _load_entry(entry_dir: Path) -> GoldenPost:
    slug = entry_dir.name
    gt_path = entry_dir / "ground_truth.json"
    if not gt_path.is_file():
        raise _fail(slug, "ground_truth.json is missing")
    try:
        ground_truth = json.loads(gt_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise _fail(slug, f"ground_truth.json is not valid JSON: {exc}") from exc
    if not isinstance(ground_truth, dict):
        raise _fail(slug, "ground_truth.json top level must be an object")

    _require_str(slug, ground_truth, "ocr_text", "field")
    _require_str(slug, ground_truth, "translation", "field")
    if "caption_raw" in ground_truth and not isinstance(
        ground_truth["caption_raw"], str
    ):
        raise _fail(slug, "field 'caption_raw' must be a string when present")

    entities = ground_truth.get("entities")
    if not isinstance(entities, list):
        raise _fail(slug, "field 'entities' must be a list")
    for i, entity in enumerate(entities):
        if not isinstance(entity, dict):
            raise _fail(slug, f"entities[{i}] must be an object")
        for key in ("text_zh", "text_en", "type"):
            _require_str(slug, entity, key, f"entities[{i}]")

    annotation = ground_truth.get("annotation")
    if not isinstance(annotation, dict):
        raise _fail(slug, "field 'annotation' must be an object")
    for key in _ANNOTATION_REQUIRED_KEYS:
        _require_str(slug, annotation, key, "annotation")

    image_paths: list[Path] = []
    images_dir = entry_dir / "images"
    if images_dir.is_dir():
        for path in sorted(images_dir.iterdir()):
            if path.name.startswith("."):
                continue
            if path.suffix.lower() not in _IMAGE_EXTENSIONS:
                raise _fail(
                    slug,
                    f"unsupported image file '{path.name}' "
                    f"(allowed: {', '.join(sorted(_IMAGE_EXTENSIONS))})",
                )
            image_paths.append(path)

    return GoldenPost(
        slug=slug, ground_truth=ground_truth, image_paths=tuple(image_paths)
    )


def load_golden_set(golden_dir: str | Path) -> list[GoldenPost]:
    """Load + validate every entry; raises GoldenSetError with a named reason."""
    root = Path(golden_dir)
    if not root.is_dir():
        raise GoldenSetError(f"golden directory not found: {root}")
    entry_dirs = sorted(p for p in root.iterdir() if p.is_dir())
    if not entry_dirs:
        raise GoldenSetError(f"no golden post directories under {root}")
    return [_load_entry(entry_dir) for entry_dir in entry_dirs]


# --- Scoring -------------------------------------------------------------------


def normalize_ocr_text(text: str) -> str:
    """Strip all whitespace variance before character-level comparison."""
    return "".join(text.split())


def score_ocr(predicted: str, truth: str) -> float:
    """Character-level similarity ratio on whitespace-normalized text."""
    a, b = normalize_ocr_text(predicted), normalize_ocr_text(truth)
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def token_f1(predicted: str, truth: str) -> float:
    """Token-level F1 (lowercase, whitespace split). Coarse ranking proxy."""
    pred_tokens = Counter(predicted.lower().split())
    truth_tokens = Counter(truth.lower().split())
    if not pred_tokens and not truth_tokens:
        return 1.0
    if not pred_tokens or not truth_tokens:
        return 0.0
    overlap = sum((pred_tokens & truth_tokens).values())
    if overlap == 0:
        return 0.0
    precision = overlap / sum(pred_tokens.values())
    recall = overlap / sum(truth_tokens.values())
    return 2 * precision * recall / (precision + recall)


def entity_prf(
    predicted_pairs: list[tuple[str, str]], truth_pairs: list[tuple[str, str]]
) -> tuple[float, float, float]:
    """Precision/recall/F1 over (type, text_zh) pairs (multiset match)."""
    pred, truth = Counter(predicted_pairs), Counter(truth_pairs)
    if not pred and not truth:
        return 1.0, 1.0, 1.0
    tp = sum((pred & truth).values())
    precision = tp / sum(pred.values()) if pred else 0.0
    recall = tp / sum(truth.values()) if truth else 0.0
    f1 = 0.0 if precision + recall == 0 else 2 * precision * recall / (precision + recall)
    return precision, recall, f1


# --- Cost tracking ---------------------------------------------------------------


def _price_for_model(model: str) -> dict[str, float] | None:
    for prefix, price in PRICE_USD_PER_MTOK.items():
        if model.startswith(prefix):
            return price
    return None


def cost_usd(usage_records: list[dict]) -> tuple[float, list[str]]:
    """Total USD for captured usage records; returns (cost, unpriced models)."""
    total = 0.0
    unpriced: list[str] = []
    for record in usage_records:
        price = _price_for_model(record.get("model", ""))
        if price is None:
            unpriced.append(record.get("model", "?"))
            continue
        total += record.get("input_tokens", 0) / 1e6 * price["input"]
        total += record.get("output_tokens", 0) / 1e6 * price["output"]
    return total, unpriced


@contextlib.contextmanager
def _capture_anthropic_usage(records: list[dict]):
    """Instrument anthropic messages.create to record token usage per call.

    The provider classes return plain text and drop the SDK response, so the
    harness captures usage at the SDK boundary instead of changing provider
    interfaces for eval's sake.
    """
    import anthropic.resources.messages

    original = anthropic.resources.messages.Messages.create

    def wrapper(self, **kwargs):
        response = original(self, **kwargs)
        usage = getattr(response, "usage", None)
        if usage is not None:
            records.append(
                {
                    "model": kwargs.get("model", ""),
                    "input_tokens": getattr(usage, "input_tokens", 0),
                    "output_tokens": getattr(usage, "output_tokens", 0),
                }
            )
        return response

    anthropic.resources.messages.Messages.create = wrapper
    try:
        yield
    finally:
        anthropic.resources.messages.Messages.create = original


# --- Live run ---------------------------------------------------------------------


def _zh_source(ground_truth: dict) -> str:
    """Mirror pipeline _zh_source: caption + blank line + OCR aggregate."""
    caption = ground_truth.get("caption_raw") or ""
    ocr_text = ground_truth["ocr_text"]
    if caption:
        return caption + "\n\n" + ocr_text
    return ocr_text


def _mime_for(path: Path) -> str:
    return {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}[
        path.suffix.lower()
    ]


def _resolve_provider(step: str, name: str):
    """Select the provider via the registry env vars (lru_cache cleared)."""
    from app.providers import registry

    getter = {
        "ocr": registry.get_ocr_provider,
        "translation": registry.get_translation_provider,
        "extraction": registry.get_extraction_provider,
    }[step]
    os.environ[_ENV_VAR_BY_STEP[step]] = name
    getter.cache_clear()
    return getter()


def _run_post_step(step: str, provider, post: GoldenPost) -> dict:
    """Run one step for one golden post; returns a per-post result dict."""
    ground_truth = post.ground_truth
    if step == "ocr":
        if not post.image_paths:
            return {"slug": post.slug, "skipped": "no images (caption-only entry)"}
        texts = [
            provider.ocr_image(path.read_bytes(), _mime_for(path))
            for path in post.image_paths
        ]
        return {
            "slug": post.slug,
            "score": score_ocr("\n\n".join(texts), ground_truth["ocr_text"]),
        }
    if step == "translation":
        # Glossary intentionally empty: eval must be DB-independent and
        # deterministic. Glossary-aware quality is judged by the analyst.
        predicted = provider.translate(_zh_source(ground_truth), [])
        return {
            "slug": post.slug,
            "score": token_f1(predicted, ground_truth["translation"]),
        }
    if step == "extraction":
        entities = provider.extract(
            _zh_source(ground_truth), ground_truth["translation"]
        )
        predicted_pairs = [(e.type, e.text_zh) for e in entities]
        truth_pairs = [
            (e["type"], e["text_zh"]) for e in ground_truth["entities"]
        ]
        precision, recall, f1 = entity_prf(predicted_pairs, truth_pairs)
        return {
            "slug": post.slug,
            "score": f1,
            "precision": precision,
            "recall": recall,
        }
    raise ValueError(f"unknown step: {step}")


def _run_live(
    posts: list[GoldenPost], steps: list[str], providers: dict[str, str]
) -> dict:
    """Run every (step x provider) over the golden set; return the results doc."""
    from app.providers.base import ProviderError

    rows: list[dict] = []
    for step in steps:
        provider_name = providers[step]
        provider = _resolve_provider(step, provider_name)
        per_post: list[dict] = []
        for post in posts:
            usage_records: list[dict] = []
            try:
                with _capture_anthropic_usage(usage_records):
                    result = _run_post_step(step, provider, post)
            except ProviderError as exc:
                result = {
                    "slug": post.slug,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            post_cost, unpriced = cost_usd(usage_records)
            result["cost_usd"] = post_cost
            if unpriced:
                result["unpriced_models"] = sorted(set(unpriced))
            per_post.append(result)

        scored = [r["score"] for r in per_post if "score" in r]
        costs = [r["cost_usd"] for r in per_post if "skipped" not in r]
        mean_cost = mean(costs) if costs else 0.0
        row = {
            "step": step,
            "provider": provider_name,
            "posts": len(posts),
            "scored": len(scored),
            "errors": sum(1 for r in per_post if "error" in r),
            "skipped": sum(1 for r in per_post if "skipped" in r),
            "accuracy": mean(scored) if scored else None,
            "cost_per_post_usd": mean_cost,
            "ceiling_check": "PASS" if mean_cost <= COST_CEILING_USD_PER_POST else "OVER",
            "per_post": per_post,
        }
        if step == "extraction" and scored:
            row["precision"] = mean(r["precision"] for r in per_post if "score" in r)
            row["recall"] = mean(r["recall"] for r in per_post if "score" in r)
        rows.append(row)

    total_cost = sum(row["cost_per_post_usd"] for row in rows)
    return {
        "steps": steps,
        "providers": providers,
        "golden_posts": len(posts),
        "cost_ceiling_usd_per_post": COST_CEILING_USD_PER_POST,
        "results": rows,
        "total_cost_per_post_usd": total_cost,
        "total_ceiling_check": "PASS"
        if total_cost <= COST_CEILING_USD_PER_POST
        else "OVER",
    }


# --- Reporting -------------------------------------------------------------------

_ACCURACY_METRIC = {
    "ocr": "char-sim",
    "translation": "token-F1",
    "extraction": "entity-F1",
}


def _format_table(doc: dict) -> str:
    headers = (
        "STEP", "PROVIDER", "POSTS", "SCORED", "ERRORS",
        "ACCURACY", "COST/POST", "<=$0.05",
    )
    table_rows = []
    for row in doc["results"]:
        if row["accuracy"] is None:
            accuracy = "n/a"
        else:
            accuracy = f"{row['accuracy']:.3f} ({_ACCURACY_METRIC[row['step']]})"
            if "precision" in row:
                accuracy += f" P={row['precision']:.2f} R={row['recall']:.2f}"
        table_rows.append(
            (
                row["step"], row["provider"], str(row["posts"]),
                str(row["scored"]), str(row["errors"]), accuracy,
                f"${row['cost_per_post_usd']:.4f}", row["ceiling_check"],
            )
        )
    widths = [
        max(len(headers[i]), *(len(r[i]) for r in table_rows)) if table_rows else len(headers[i])
        for i in range(len(headers))
    ]
    lines = [
        "  ".join(h.ljust(widths[i]) for i, h in enumerate(headers)),
        "  ".join("-" * w for w in widths),
    ]
    lines += ["  ".join(c.ljust(widths[i]) for i, c in enumerate(r)) for r in table_rows]
    lines.append("")
    lines.append(
        f"TOTAL estimated cost/post across steps: "
        f"${doc['total_cost_per_post_usd']:.4f} -> {doc['total_ceiling_check']} "
        f"(ceiling ${COST_CEILING_USD_PER_POST:.2f}/post across the whole pipeline)"
    )
    lines.append(
        "NOTE: prices in PRICE_USD_PER_MTOK are marked UPDATE ME; "
        "verify before drawing cost conclusions."
    )
    return "\n".join(lines)


# --- CLI --------------------------------------------------------------------------


def _parse_providers(pairs: list[str]) -> dict[str, str]:
    providers = dict(_DEFAULT_PROVIDERS)
    for pair in pairs:
        if "=" not in pair:
            raise ValueError(f"--providers expects step=name, got: {pair!r}")
        step, _, name = pair.partition("=")
        if step not in STEPS:
            raise ValueError(
                f"unknown step in --providers: {step!r} (allowed: {', '.join(STEPS)})"
            )
        providers[step] = name
    return providers


def _parse_steps(raw: str) -> list[str]:
    steps = [s.strip() for s in raw.split(",") if s.strip()]
    for step in steps:
        if step not in STEPS:
            raise ValueError(f"unknown step: {step!r} (allowed: {', '.join(STEPS)})")
    if not steps:
        raise ValueError("--steps must name at least one step")
    return steps


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.eval.harness",
        description="Golden-set provider eval: accuracy x cost per provider.",
    )
    parser.add_argument(
        "--golden", required=True, help="directory containing golden post entries"
    )
    parser.add_argument(
        "--providers",
        action="append",
        default=[],
        metavar="STEP=NAME",
        help="provider per step, e.g. ocr=anthropic (repeatable)",
    )
    parser.add_argument(
        "--steps",
        default=",".join(STEPS),
        help=f"comma-separated steps to run (default: {','.join(STEPS)})",
    )
    parser.add_argument("--json", help="also write full results to this JSON file")
    parser.add_argument(
        "--live",
        action="store_true",
        help="actually call providers (costs money); without it, only validate",
    )
    args = parser.parse_args(argv)

    try:
        steps = _parse_steps(args.steps)
        providers = _parse_providers(args.providers)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    try:
        posts = load_golden_set(args.golden)
    except GoldenSetError as exc:
        print(f"golden-set validation FAILED: {exc}", file=sys.stderr)
        return 2

    print(f"Golden set OK: {len(posts)} post(s) under {args.golden}")
    print(f"Steps: {', '.join(steps)}")
    print("Providers: " + ", ".join(f"{s}={providers[s]}" for s in steps))

    if not args.live:
        print("Dry run (no --live): structure validated, no provider calls made.")
        return 0

    doc = _run_live(posts, steps, providers)
    print()
    print(_format_table(doc))
    if args.json:
        Path(args.json).write_text(
            json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"\nFull results written to {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
