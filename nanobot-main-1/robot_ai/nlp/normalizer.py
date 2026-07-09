"""Chinese natural-language normalization for robot commands.

Reads ``~/.nanobot/robot_ai/nlp_standard_words.json`` with shape::

    {
      "version": "1.0",
      "words": [
        {
          "standard": "移动",
          "pinyin": "yidong",
          "category": "motion",
          "homophones": ["移洞", "挪到", "走到", ...],
          "sichuan_variants": ["挪一哈", ...],
          "func_id": 108
        },
        ...
      ]
    }

Each entry maps a canonical ``standard`` word to the spoken variations
(``homophones`` + ``sichuan_variants``) that should be replaced by it.
``normalize(text)`` applies those replacements plus a small set of explicit
multi-word ``compound aliases`` for common operator phrases whose correct
expansion can't be composed from single-word swaps (e.g. ``去A点`` →
``移动到位置A``, ``回原点`` → ``home``).

The migration helper copies the legacy file verbatim into the user config dir.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


# Explicit compound-phrase aliases. These are applied FIRST (before per-word
# substitution) because they span multiple tokens / require word reordering
# that a single-word swap can't express. Each value is the canonical spoken
# form. Keys are matched as substrings (case-insensitive). Longest keys first
# is enforced at build time so e.g. "回原点" wins over a hypothetical shorter
# overlapping key.
DEFAULT_COMPOUND_ALIASES: dict[str, str] = {
    # Motion-to-named-position phrasings. "去A点" / "到工位A" / "移动到A" all
    # mean "move to position A"; we canonicalize to the dashboard query_key
    # phrasing "移动到位置A" used in query_table.json.
    "去a点": "移动到位置A",
    "去b点": "移动到位置B",
    "去c点": "移动到位置C",
    "去a": "移动到位置A",
    "去b": "移动到位置B",
    "去c": "移动到位置C",
    "到工位a": "移动到位置A",
    "到工位b": "移动到位置B",
    "到工位c": "移动到位置C",
    "到a点": "移动到位置A",
    "到b点": "移动到位置B",
    "到c点": "移动到位置C",
    "移动到a": "移动到位置A",
    "移动到b": "移动到位置B",
    "移动到c": "移动到位置C",
    # "回原点" / "回零" — query_table.json uses the literal key "home" for
    # the home pose, so we canonicalize these phrases to that key.
    "回原点": "home",
    "回零位": "home",
    "回home": "home",
}

_DEFAULT_CONFIG_PATH = Path.home() / ".nanobot" / "robot_ai" / "nlp_standard_words.json"


class NlpNormalizer:
    """Substring-based Chinese NL normalizer backed by a JSON config file."""

    def __init__(
        self,
        path: str | Path | None = None,
        *,
        compound_aliases: dict[str, str] | None = None,
    ) -> None:
        self.path = Path(path) if path is not None else _DEFAULT_CONFIG_PATH
        self.compound_aliases = dict(compound_aliases or DEFAULT_COMPOUND_ALIASES)
        self._word_rules: list[tuple[str, str]] = []
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            self._word_rules = []
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            self._word_rules = []
            return
        words = payload.get("words", []) if isinstance(payload, dict) else []
        rules: list[tuple[str, str]] = []
        for w in words:
            if not isinstance(w, dict):
                continue
            standard = str(w.get("standard", "")).strip()
            if not standard:
                continue
            for key in ("homophones", "sichuan_variants"):
                for variant in w.get(key, []) or []:
                    if isinstance(variant, str) and variant:
                        rules.append((variant, standard))
        # Longest variation first so longer phrases win over their prefixes
        # (e.g. "向左走" before "向左"). Stable sort keeps insertion order for
        # ties, matching the legacy file's authoring order.
        rules.sort(key=lambda kv: len(kv[0]), reverse=True)
        self._word_rules = rules

    @property
    def word_rules(self) -> list[tuple[str, str]]:
        return list(self._word_rules)

    def normalize(self, text: str) -> str:
        """Return ``text`` with all known variations replaced by their canonical forms.

        Compound aliases are applied first, then per-word variation→standard
        swaps. Unknown text is returned unchanged.
        """
        result = str(text or "")
        if not result.strip():
            return result

        # 1) Compound aliases (specific multi-word phrases). Longest key first.
        for key in sorted(self.compound_aliases, key=len, reverse=True):
            canonical = self.compound_aliases[key]
            result = self._replace_ci(result, key, canonical)

        # 2) Per-word variation → standard. Already sorted longest-first.
        for variant, standard in self._word_rules:
            if variant == standard:
                continue
            result = self._replace_ci(result, variant, standard)

        return result

    @staticmethod
    def _replace_ci(haystack: str, needle: str, replacement: str) -> str:
        """Case-insensitive literal substring replace (no regex)."""
        if not needle:
            return haystack
        lowered = haystack.lower()
        idx = lowered.find(needle.lower())
        if idx < 0:
            return haystack
        # Replace ALL non-overlapping occurrences left-to-right.
        out: list[str] = []
        i = 0
        n = len(needle)
        while True:
            j = lowered.find(needle.lower(), i)
            if j < 0:
                out.append(haystack[i:])
                break
            out.append(haystack[i:j])
            out.append(replacement)
            i = j + n
        return "".join(out)


def normalize(text: str) -> str:
    """Module-level convenience wrapper around the default-config normalizer.

    Equivalent to ``NlpNormalizer().normalize(text)`` but cached so repeated
    calls don't re-read the JSON file.
    """
    global _DEFAULT_NORMALIZER
    if _DEFAULT_NORMALIZER is None or _DEFAULT_NORMALIZER[0] != _DEFAULT_CONFIG_PATH:
        _DEFAULT_NORMALIZER = (_DEFAULT_CONFIG_PATH, NlpNormalizer(_DEFAULT_CONFIG_PATH))
    return _DEFAULT_NORMALIZER[1].normalize(text)


_DEFAULT_NORMALIZER: tuple[Path, NlpNormalizer] | None = None


def migrate_nlp_words(src_dir: str | Path, out_path: str | Path) -> int:
    """Copy legacy ``nlp_standard_words.json`` into the user config dir.

    The legacy file is already in the runtime shape (``{version, words: [...]}``)
    so we copy it verbatim. Returns the number of word entries written, or 0
    if the legacy file is missing.
    """
    src = Path(src_dir) / "nlp_standard_words.json"
    if not src.exists():
        # Still (re)create an empty stub so downstream loaders don't crash.
        _write(out_path, {"version": "1.0", "words": []})
        return 0
    payload = json.loads(src.read_text(encoding="utf-8"))
    words = payload.get("words", []) if isinstance(payload, dict) else []
    _write(out_path, payload if isinstance(payload, dict) else {"version": "1.0", "words": []})
    return len(words) if isinstance(words, list) else 0


def _write(out_path: str | Path, payload: dict[str, Any]) -> None:
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
