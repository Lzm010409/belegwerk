from __future__ import annotations

import os
import sys
from pathlib import Path

WURZEL = Path(__file__).resolve().parents[1]
os.environ.setdefault("DATEN_VERZEICHNIS", str(WURZEL / ".pytest-daten"))
os.environ.setdefault("SITZUNG_GEHEIMNIS", "test-geheimnis-nur-fuer-tests-0123456789")
os.environ.setdefault("UMGEBUNG", "test")

sys.path.insert(0, str(WURZEL / "src"))
