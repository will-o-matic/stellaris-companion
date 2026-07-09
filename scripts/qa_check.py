#!/usr/bin/env python3
"""Interactive QA of a Stellaris save's extraction against the running game.

Thin wrapper over ``stellaris_save_extractor.qa_check`` so it runs from a source
checkout without installing. Runs the full export, auto-flags obvious breakage,
then walks you through comparing each value to the in-game panels and writes a
report + a paste-ready findings block. See ``--help``.

Examples:
    python scripts/qa_check.py                       # most recent save, pick areas
    python scripts/qa_check.py path/to/save.sav
    python scripts/qa_check.py --categories military,pops,colonies
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from stellaris_save_extractor.qa_check import main

if __name__ == "__main__":
    raise SystemExit(main())
