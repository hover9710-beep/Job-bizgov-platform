# -*- coding: utf-8 -*-
"""프로젝트 루트 호환: pipeline.validate_counts 로 위임."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from pipeline.validate_counts import main

if __name__ == "__main__":
    sys.exit(main())
