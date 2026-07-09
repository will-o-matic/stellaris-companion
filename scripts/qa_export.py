#!/usr/bin/env python3
"""Full structured QA export + extraction-health audit for a Stellaris save.

Thin wrapper over ``stellaris_save_extractor.qa_export`` so it runs from a source
checkout without installing the package. See ``--help`` for options.

Examples:
    python scripts/qa_export.py -o export.json
    python scripts/qa_export.py path/to/save.sav --raw
    python scripts/qa_export.py --player-name "Great Coffee Nation" --no-audit
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from stellaris_save_extractor.qa_export import main

if __name__ == "__main__":
    raise SystemExit(main())
