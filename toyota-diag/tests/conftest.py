"""Make the in-repo `toyotadiag` package importable when pytest runs from the
car-logger repo root (toyota-diag is a subproject and is not pip-installed
there). Installing it with `pip install -e toyota-diag` also works."""

import sys
from pathlib import Path

_PROJECT_DIR = Path(__file__).resolve().parent.parent
if str(_PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(_PROJECT_DIR))
