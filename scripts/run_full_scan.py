"""Resume the full metadata scan after temporary HTTP range failures."""

from __future__ import annotations

import time

from scan_home_metadata import main
from audit_phase3b import main as audit_main


if __name__ == "__main__":
    for attempt in range(100):
        try:
            main()
            audit_main()
            break
        except RuntimeError as exc:
            if not str(exc).startswith("Failed range ") or attempt == 99:
                raise
            delay = min(60, 10 + attempt * 5)
            print(f"Network range failed; checkpoint preserved. Retrying in {delay}s: {exc}", flush=True)
            time.sleep(delay)
