#!/usr/bin/env python3
"""Entry point of the wiki-interest-research CLI. Normally started through scripts/wir."""
import json
import sys

try:
    from wir_core.cli import main
except ImportError as exc:  # dependencies missing: python was started without uv
    print(json.dumps({"ok": False, "state": "failed", "error": {
        "code": "DEPS_MISSING", "message": str(exc),
        "fix": "Run the tool through scripts/wir (it uses uv to install dependencies)."}}))
    sys.exit(3)

if __name__ == "__main__":
    # The envelope is UTF-8 JSON whatever the locale says (uk strings, em dashes).
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(errors="backslashreplace")
    sys.exit(main())
