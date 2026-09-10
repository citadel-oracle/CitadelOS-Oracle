import json
import os
from datetime import datetime, timezone
from pathlib import Path


class ForecastCache:
    SCHEMA_VERSION = 1

    def __init__(self, path):
        self.path = Path(path)

    def write(self, payload):
        document = {"schema_version": self.SCHEMA_VERSION, **payload}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps(document, sort_keys=True, separators=(",", ":")), encoding="utf-8")
        os.replace(temporary, self.path)
        return document

    def read(self):
        if not self.path.exists():
            return None
        try:
            document = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return None
        if not isinstance(document, dict) or document.get("schema_version") != self.SCHEMA_VERSION:
            return None
        return document

    @staticmethod
    def age_seconds(document, now=None):
        try:
            generated = datetime.fromisoformat(document["generated_at"].replace("Z", "+00:00"))
            reference = now or datetime.now(timezone.utc)
            return max(0.0, (reference - generated).total_seconds())
        except (KeyError, TypeError, ValueError):
            return None
