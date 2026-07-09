"""Migrate legacy ``nlp_standard_words.json`` into the user config dir.

Usage::

    .venv-robot-desktop/Scripts/python.exe tools/migrate_nlp_words.py

Reads ``<ROBOT_LEGACY_DATA_DIR>/nlp_standard_words.json`` and writes a verbatim
copy to ``~/.nanobot/robot_ai/nlp_standard_words.json``. Re-running is safe —
it overwrites the destination. Prints the count of word entries migrated.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from robot_ai.nlp.normalizer import migrate_nlp_words

LEGACY = Path(
    os.environ.get(
        "ROBOT_LEGACY_DATA_DIR",
        r"data/legacy",
    )
)
OUT = Path(os.path.expanduser("~")) / ".nanobot" / "robot_ai" / "nlp_standard_words.json"

if __name__ == "__main__":
    count = migrate_nlp_words(LEGACY, OUT)
    print(f"Migrated {count} NLP word entries -> {OUT}")
