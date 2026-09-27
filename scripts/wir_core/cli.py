"""Argument parsing and command dispatch. Every path ends in exactly one JSON line on stdout."""
from __future__ import annotations

import argparse
import importlib
import importlib.util
import sys
import traceback

from .config import VERSION
from .envelope import emit, from_error
from .errors import EXIT_USAGE, WirError

COMMANDS: dict[str, tuple[str, str]] = {
    "scope": ("wir_core.scope", "run_scope"),
    "analyze": ("wir_core.pipeline", "run_analyze"),
    "verify": ("wir_core.pipeline", "run_verify"),
    "publish": ("wir_core.publish", "run_publish"),
    "status": ("wir_core.project", "run_status"),
}


class _Parser(argparse.ArgumentParser):
    def error(self, message: str):  # argparse would print usage text and exit(2)
        raise WirError("BAD_ARGS", message, fix=f"{self.prog} --help", exit_code=EXIT_USAGE)


def build_parser() -> argparse.ArgumentParser:
    p = _Parser(prog="wir", description=(
        "Research public interest in a topic across Wikipedia language editions. "
        "Every command prints one JSON object: read 'say', 'caveats', 'ask', 'next', 'error.fix'."))
    p.add_argument("--version", action="version", version=f"wir {VERSION}")
    sub = p.add_subparsers(dest="command", required=True, parser_class=_Parser)

    s = sub.add_parser("scope", help="create or edit a project: topic -> articles per language")
    s.add_argument("topic", nargs="?", help='topic text or Wikidata QID, e.g. "intermittent fasting" or Q1666254')
    s.add_argument("--langs", help="comma-separated wiki language codes, e.g. pl,cs")
    s.add_argument("--source", choices=["wikipedia", "wiktionary", "wikivoyage"], help="default: wikipedia")
    s.add_argument("--period", help="window length, e.g. 24m or 2y (default 24m)")
    s.add_argument("--from", dest="date_from", metavar="YYYY-MM", help="window start month")
    s.add_argument("--to", dest="date_to", metavar="YYYY-MM", help="window end month")
    s.add_argument("--ui", help="language the user writes in, e.g. uk or en (default en)")
    s.add_argument("--project", help="project directory or id (default: latest)")
    s.add_argument("--add-lang", action="append", default=[], metavar="CODE")
    s.add_argument("--drop-lang", action="append", default=[], metavar="CODE")
    s.add_argument("--set", dest="set_title", action="append", default=[], metavar='LANG="Title"',
                   help="use this article for LANG (checked by code)")
    s.add_argument("--add-article", action="append", default=[], metavar='LANG="Title"',
                   help="add a related article to the topic basket for LANG")
    s.add_argument("--fork", action="store_true", help="copy the project before changing it")

    a = sub.add_parser("analyze", help="fetch data; compute growth, trust, countries; draw charts")
    a.add_argument("--project", help="project directory or id (default: latest)")
    a.add_argument("--offline", action="store_true", help="use cached data only")
    a.add_argument("--weights", help="ranking weights, e.g. level=0.35,momentum=0.35,size=0.2,gap=0.1")

    v = sub.add_parser("verify", help="robustness check of the verdicts (no network)")
    v.add_argument("--project", help="project directory or id (default: latest)")

    pb = sub.add_parser("publish", help="check numbers in notes and build report.pdf + report.md")
    pb.add_argument("--project", help="project directory or id (default: latest)")
    pb.add_argument("--notes", help="notes file (default: <project>/notes.md)")

    st = sub.add_parser("status", help="short summary of a project")
    st.add_argument("--project", help="project directory or id (default: latest)")
    return p


def main(argv: list[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
    except WirError as err:
        return emit(from_error(err))
    module_name, func_name = COMMANDS[args.command]
    if module_name not in sys.modules and importlib.util.find_spec(module_name) is None:
        return emit(from_error(WirError("NOT_IMPLEMENTED", f"command '{args.command}' is not available yet")))
    project = getattr(args, "project", None)
    try:
        func = getattr(importlib.import_module(module_name), func_name)
        env = func(args)
        return emit(env)
    except WirError as err:
        return emit(from_error(err, project=project))
    except ModuleNotFoundError as exc:
        if exc.name and not exc.name.startswith("wir_core"):  # a third-party dependency is not installed
            return emit(from_error(WirError(
                "DEPS_MISSING", str(exc), fix="Run the tool through scripts/wir (it uses uv to install dependencies)."),
                project=project))
        traceback.print_exc(file=sys.stderr)
        return emit(from_error(WirError("INTERNAL", f"{type(exc).__name__}: {exc}"), project=project))
    except Exception as exc:  # never leak a traceback to stdout
        traceback.print_exc(file=sys.stderr)
        return emit(from_error(WirError(
            "INTERNAL", f"{type(exc).__name__}: {exc}",
            fix="Re-run the same command once. If it fails again, tell the user the tool failed and show this message."),
            project=project))
