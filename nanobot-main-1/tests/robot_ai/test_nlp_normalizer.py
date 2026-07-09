from __future__ import annotations

import json

from robot_ai.nlp.normalizer import (
    DEFAULT_COMPOUND_ALIASES,
    NlpNormalizer,
    migrate_nlp_words,
    normalize,
)


def _write_config(path, words) -> None:
    path.write_text(
        json.dumps({"version": "1.0", "words": words}, ensure_ascii=False),
        encoding="utf-8",
    )


# --- Spec'd test cases ---------------------------------------------------


def test_normalize_qu_a_dian_to_move_to_position_a(tmp_path) -> None:
    p = tmp_path / "nlp_standard_words.json"
    _write_config(p, [])
    n = NlpNormalizer(p)
    assert n.normalize("去A点") == "移动到位置A"


def test_normalize_hui_yuan_dian_to_home(tmp_path) -> None:
    p = tmp_path / "nlp_standard_words.json"
    _write_config(p, [])
    n = NlpNormalizer(p)
    assert n.normalize("回原点") == "home"


def test_normalize_unknown_unchanged(tmp_path) -> None:
    p = tmp_path / "nlp_standard_words.json"
    _write_config(p, [])
    n = NlpNormalizer(p)
    assert n.normalize("totally-unknown-phrase") == "totally-unknown-phrase"
    # Empty / whitespace passthrough
    assert n.normalize("") == ""
    assert n.normalize("   ") == "   "


# --- Variation → standard substitution -----------------------------------


def test_variation_replaced_by_standard(tmp_path) -> None:
    p = tmp_path / "nlp_standard_words.json"
    _write_config(
        p,
        [
            {
                "standard": "移动",
                "homophones": ["移洞", "挪到"],
                "sichuan_variants": ["挪一哈"],
            },
            {
                "standard": "保存",
                "homophones": ["宝存"],
                "sichuan_variants": [],
            },
        ],
    )
    n = NlpNormalizer(p)
    assert n.normalize("请移洞过去") == "请移动过去"
    assert n.normalize("帮我宝存一下") == "帮我保存一下"
    # Sichuan variant
    assert n.normalize("挪一哈") == "移动"


def test_longest_variation_wins(tmp_path) -> None:
    """Longer variations must be matched before their shorter prefixes."""
    p = tmp_path / "nlp_standard_words.json"
    _write_config(
        p,
        [
            {"standard": "左移", "homophones": ["向左"], "sichuan_variants": []},
            {"standard": "前进", "homophones": ["向左走"], "sichuan_variants": []},
        ],
    )
    n = NlpNormalizer(p)
    # "向左走" should match as a whole (longest first), not be split into
    # "向左" + leftover "走".
    assert n.normalize("请向左走") == "请前进"


def test_module_level_normalize_uses_default_config(tmp_path, monkeypatch) -> None:
    p = tmp_path / "nlp_standard_words.json"
    _write_config(
        p,
        [{"standard": "保存", "homophones": ["宝存"], "sichuan_variants": []}],
    )
    # Point the module-level default path at our temp file and reset cache.
    import robot_ai.nlp.normalizer as mod

    monkeypatch.setattr(mod, "_DEFAULT_CONFIG_PATH", p)
    monkeypatch.setattr(mod, "_DEFAULT_NORMALIZER", None)
    assert normalize("宝存") == "保存"


def test_missing_config_file_returns_input_unchanged(tmp_path) -> None:
    n = NlpNormalizer(tmp_path / "does-not-exist.json")
    # Compound aliases still apply (they're defaults), but no word rules.
    assert n.normalize("回原点") == "home"
    assert n.normalize("随便说点什么") == "随便说点什么"


def test_compound_aliases_overridable(tmp_path) -> None:
    p = tmp_path / "nlp_standard_words.json"
    _write_config(p, [])
    n = NlpNormalizer(p, compound_aliases={"回原点": "回零"})
    assert n.normalize("回原点") == "回零"
    # Default compound alias for "去A点" is gone now
    assert n.normalize("去A点") == "去A点"


# --- Migration -----------------------------------------------------------


def test_migrate_copies_legacy_file(tmp_path) -> None:
    src = tmp_path / "old"
    src.mkdir()
    legacy_payload = {
        "version": "1.0",
        "words": [
            {"standard": "移动", "homophones": ["移洞"], "sichuan_variants": []},
            {"standard": "保存", "homophones": ["宝存"], "sichuan_variants": []},
        ],
    }
    (src / "nlp_standard_words.json").write_text(
        json.dumps(legacy_payload), encoding="utf-8"
    )
    out = tmp_path / "nlp_standard_words.json"
    count = migrate_nlp_words(src, out)
    assert count == 2
    written = json.loads(out.read_text(encoding="utf-8"))
    assert written["version"] == "1.0"
    assert [w["standard"] for w in written["words"]] == ["移动", "保存"]


def test_migrate_handles_missing_legacy(tmp_path) -> None:
    out = tmp_path / "nlp_standard_words.json"
    count = migrate_nlp_words(tmp_path / "no-such-dir", out)
    assert count == 0
    written = json.loads(out.read_text(encoding="utf-8"))
    assert written == {"version": "1.0", "words": []}


def test_default_compound_aliases_complete() -> None:
    # Guard against accidental shrinkage of the spec'd phrases.
    assert DEFAULT_COMPOUND_ALIASES["去a点"] == "移动到位置A"
    assert DEFAULT_COMPOUND_ALIASES["回原点"] == "home"
