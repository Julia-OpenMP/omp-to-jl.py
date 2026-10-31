"""Command line interface: ``python -m omp_generator`` / ``omp-generator``."""

from __future__ import annotations

import argparse
import difflib
import os
import pathlib
import sys
from typing import Dict, List, Optional

from . import __version__, julia, spec

TARGETS = {"julia": julia.generate}


def write(out: pathlib.Path, files: Dict[str, str]) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        path = out / name
        if not path.exists() or path.read_text(encoding="utf-8") != content:
            path.write_text(content, encoding="utf-8")
            print(f"wrote {path}")


def check(out: pathlib.Path, files: Dict[str, str], *, show_diff: bool) -> bool:
    ok = True
    for name, content in files.items():
        path = out / name
        current = path.read_text(encoding="utf-8") if path.exists() else ""
        if current != content:
            ok = False
            print(f"out of date: {path}", file=sys.stderr)
            if show_diff:
                sys.stderr.writelines(
                    difflib.unified_diff(
                        current.splitlines(True), content.splitlines(True), str(path), f"{path} (generated)"
                    )
                )
    return ok


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(
        prog="omp-generator",
        description="Generate the OpenMP directive front-end from the OpenMP specification sources.",
    )
    p.add_argument(
        "--spec",
        type=pathlib.Path,
        default=os.environ.get("OMP_SPEC_DIR"),
        help="root of the OpenMP specification sources (default: $OMP_SPEC_DIR)",
    )
    p.add_argument("--out", type=pathlib.Path, required=True, help="output directory")
    p.add_argument("--target", choices=sorted(TARGETS), default="julia", help="target language (default: julia)")
    p.add_argument("--revision", help="spec revision recorded in the generated files (default: git revision of --spec)")
    p.add_argument("--no-revision", action="store_true", help="do not record the spec revision")
    p.add_argument("--check", action="store_true", help="only check that the output is up to date (exit 1 if not)")
    p.add_argument("--diff", action="store_true", help="with --check, print the differences")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    args = p.parse_args(argv)

    if args.spec is None:
        p.error("the specification sources are required: pass --spec or set OMP_SPEC_DIR")

    try:
        model = spec.load(args.spec, revision=args.revision, with_revision=not args.no_revision)
    except spec.SpecError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    for w in model.warnings:
        print(f"warning: {w}", file=sys.stderr)

    files = TARGETS[args.target](model)
    if args.check:
        if check(args.out, files, show_diff=args.diff):
            print(f"{args.out} is up to date")
            return 0
        return 1
    write(args.out, files)
    return 0
