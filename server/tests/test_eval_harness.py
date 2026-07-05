"""Eval harness unit tests: scoring math, golden-set validation, no---live path.

NO live API calls anywhere in this file; the live path is stubbed out so a
regression that reaches providers fails loudly instead of spending money.
"""

import json

import pytest
from PIL import Image

from app.eval import harness
from app.eval.harness import (
    GoldenSetError,
    cost_usd,
    entity_prf,
    load_golden_set,
    main,
    score_ocr,
    token_f1,
)

VALID_GROUND_TRUTH = {
    "synthetic": True,
    "caption_raw": "这个防晒霜很好用",
    "ocr_text": "这个防晒霜很好用",
    "translation": "This sunscreen works really well.",
    "entities": [
        {"text_zh": "防晒霜", "text_en": "sunscreen", "type": "product"}
    ],
    "annotation": {
        "category": "skincare",
        "trend_type": "product_format",
        "consumer_signal": "zhongcao",
        "recommended_action": "monitor",
    },
}


def _write_entry(root, slug="valid-post", ground_truth=VALID_GROUND_TRUTH,
                 image_name="01.png"):
    entry = root / slug
    entry.mkdir(parents=True)
    if image_name is not None:
        (entry / "images").mkdir()
        Image.new("RGB", (8, 8), "white").save(
            entry / "images" / image_name, format="PNG"
        )
    if ground_truth is not None:
        (entry / "ground_truth.json").write_text(
            json.dumps(ground_truth, ensure_ascii=False), encoding="utf-8"
        )
    return entry


# --- Scoring: OCR character similarity -----------------------------------------


def test_score_ocr_ignores_whitespace_variance():
    assert score_ocr("这个 防晒霜\n很好用", "这个防晒霜很好用") == 1.0


def test_score_ocr_known_ratio():
    # normalized "abcd" vs "abce": 3 matching of 8 total -> 2*3/8 = 0.75
    assert score_ocr("abcd", "abce") == pytest.approx(0.75)


def test_score_ocr_empty_edges():
    assert score_ocr("", "") == 1.0
    assert score_ocr("", "防晒霜") == 0.0
    assert score_ocr("防晒霜", "") == 0.0


# --- Scoring: translation token F1 -----------------------------------------------


def test_token_f1_exact_match_case_insensitive():
    assert token_f1("The Fox Jumps", "the fox jumps") == 1.0


def test_token_f1_known_partial():
    # overlap 3; precision 3/3, recall 3/4 -> F1 = 6/7
    assert token_f1("the quick fox", "the quick brown fox") == pytest.approx(6 / 7)


def test_token_f1_disjoint_and_empty():
    assert token_f1("alpha beta", "gamma delta") == 0.0
    assert token_f1("", "") == 1.0
    assert token_f1("", "words here") == 0.0


# --- Scoring: extraction entity P/R/F1 -------------------------------------------


def test_entity_prf_known_values():
    truth = [("brand", "花西子"), ("ingredient", "烟酰胺")]
    predicted = [("brand", "花西子"), ("brand", "完美日记")]
    precision, recall, f1 = entity_prf(predicted, truth)
    assert (precision, recall, f1) == (0.5, 0.5, 0.5)


def test_entity_prf_type_must_match():
    # Same surface form but wrong type is NOT a match.
    precision, recall, f1 = entity_prf([("product", "花西子")], [("brand", "花西子")])
    assert (precision, recall, f1) == (0.0, 0.0, 0.0)


def test_entity_prf_empty_edges():
    assert entity_prf([], []) == (1.0, 1.0, 1.0)
    assert entity_prf([], [("brand", "花西子")]) == (0.0, 0.0, 0.0)


# --- Cost table --------------------------------------------------------------------


def test_cost_usd_prices_haiku_by_prefix():
    records = [
        {"model": "claude-haiku-4-5-20251001", "input_tokens": 1000, "output_tokens": 1000}
    ]
    price = harness.PRICE_USD_PER_MTOK["claude-haiku-4-5"]
    expected = 1000 / 1e6 * price["input"] + 1000 / 1e6 * price["output"]
    total, unpriced = cost_usd(records)
    assert total == pytest.approx(expected)
    assert unpriced == []


def test_cost_usd_flags_unknown_models():
    total, unpriced = cost_usd(
        [{"model": "mystery-model", "input_tokens": 10, "output_tokens": 10}]
    )
    assert total == 0.0
    assert unpriced == ["mystery-model"]


# --- Golden-set structure validation -----------------------------------------------


def test_valid_entry_loads(tmp_path):
    _write_entry(tmp_path)
    posts = load_golden_set(tmp_path)
    assert len(posts) == 1
    assert posts[0].slug == "valid-post"
    assert len(posts[0].image_paths) == 1
    assert posts[0].ground_truth["ocr_text"] == "这个防晒霜很好用"


def test_caption_only_entry_without_images_loads(tmp_path):
    _write_entry(tmp_path, image_name=None)
    posts = load_golden_set(tmp_path)
    assert posts[0].image_paths == ()


def _without(mapping, key):
    clone = json.loads(json.dumps(mapping))
    del clone[key]
    return clone


def _with(mapping, key, value):
    clone = json.loads(json.dumps(mapping))
    clone[key] = value
    return clone


BROKEN_CASES = [
    pytest.param(_without(VALID_GROUND_TRUTH, "ocr_text"), "ocr_text", id="missing-ocr_text"),
    pytest.param(_without(VALID_GROUND_TRUTH, "translation"), "translation", id="missing-translation"),
    pytest.param(_without(VALID_GROUND_TRUTH, "entities"), "entities", id="missing-entities"),
    pytest.param(_with(VALID_GROUND_TRUTH, "entities", "not-a-list"), "entities", id="entities-not-list"),
    pytest.param(
        _with(VALID_GROUND_TRUTH, "entities", [{"text_zh": "防晒霜", "type": "product"}]),
        "text_en", id="entity-missing-text_en",
    ),
    pytest.param(_without(VALID_GROUND_TRUTH, "annotation"), "annotation", id="missing-annotation"),
    pytest.param(
        _with(VALID_GROUND_TRUTH, "annotation", {"category": "skincare"}),
        "trend_type", id="annotation-missing-keys",
    ),
]


@pytest.mark.parametrize("ground_truth,named_reason", BROKEN_CASES)
def test_broken_entry_fails_with_named_reason(tmp_path, ground_truth, named_reason):
    _write_entry(tmp_path, slug="broken-post", ground_truth=ground_truth)
    with pytest.raises(GoldenSetError, match="broken-post") as excinfo:
        load_golden_set(tmp_path)
    assert named_reason in str(excinfo.value)


def test_missing_ground_truth_json_fails(tmp_path):
    _write_entry(tmp_path, slug="no-gt", ground_truth=None)
    with pytest.raises(GoldenSetError, match="no-gt.*ground_truth.json is missing"):
        load_golden_set(tmp_path)


def test_invalid_json_fails(tmp_path):
    entry = _write_entry(tmp_path, slug="bad-json", ground_truth=None)
    (entry / "ground_truth.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(GoldenSetError, match="bad-json.*not valid JSON"):
        load_golden_set(tmp_path)


def test_unsupported_image_extension_fails(tmp_path):
    entry = _write_entry(tmp_path, slug="bad-image")
    (entry / "images" / "clip.gif").write_bytes(b"GIF89a")
    with pytest.raises(GoldenSetError, match="bad-image.*clip.gif"):
        load_golden_set(tmp_path)


def test_empty_golden_dir_fails(tmp_path):
    with pytest.raises(GoldenSetError, match="no golden post"):
        load_golden_set(tmp_path)


def test_missing_golden_dir_fails(tmp_path):
    with pytest.raises(GoldenSetError, match="not found"):
        load_golden_set(tmp_path / "does-not-exist")


# --- CLI: no---live path never touches providers ------------------------------------


def test_no_live_validates_and_exits_zero(tmp_path, capsys, monkeypatch):
    _write_entry(tmp_path)
    monkeypatch.setattr(
        harness, "_run_live",
        lambda *a, **k: pytest.fail("live path invoked without --live"),
    )
    monkeypatch.setattr(
        harness, "_resolve_provider",
        lambda *a, **k: pytest.fail("provider resolved without --live"),
    )
    assert main(["--golden", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "Golden set OK: 1 post(s)" in out
    assert "Dry run (no --live)" in out


def test_no_live_broken_set_exits_nonzero_with_reason(tmp_path, capsys):
    _write_entry(tmp_path, slug="broken-post",
                 ground_truth=_without(VALID_GROUND_TRUTH, "ocr_text"))
    assert main(["--golden", str(tmp_path)]) == 2
    err = capsys.readouterr().err
    assert "broken-post" in err and "ocr_text" in err


def test_unknown_step_rejected(tmp_path, capsys):
    _write_entry(tmp_path)
    assert main(["--golden", str(tmp_path), "--steps", "embed"]) == 2
    assert "unknown step" in capsys.readouterr().err


def test_bad_providers_pair_rejected(tmp_path, capsys):
    _write_entry(tmp_path)
    assert main(["--golden", str(tmp_path), "--providers", "ocr"]) == 2
    assert "step=name" in capsys.readouterr().err
