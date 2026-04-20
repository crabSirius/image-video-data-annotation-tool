from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LABEL_STUDIO_TOOL_ROOT = PROJECT_ROOT / "tools" / "convert_dataset_format" / "label-studio"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(LABEL_STUDIO_TOOL_ROOT) not in sys.path:
    sys.path.insert(0, str(LABEL_STUDIO_TOOL_ROOT))
