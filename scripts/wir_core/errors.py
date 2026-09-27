"""Error type carrying a machine-readable code, a hint and a process exit code."""
from __future__ import annotations

EXIT_OK = 0
EXIT_INPUT = 2
EXIT_USAGE = 3
EXIT_NETWORK = 4
EXIT_NODATA = 5
EXIT_NUMCHECK = 6


class WirError(Exception):
    def __init__(self, code: str, message: str, fix: str | None = None, exit_code: int = EXIT_USAGE):
        super().__init__(message)
        self.code = code
        self.message = message
        self.fix = fix
        self.exit_code = exit_code
