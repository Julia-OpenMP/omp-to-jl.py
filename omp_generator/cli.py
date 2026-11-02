"""Command line interface: ``python -m omp_generator`` / ``omp-generator``."""

from __future__ import annotations

import argparse
import difflib
import os
import pathlib
import sys
from typing import Callable, Dict, List, NamedTuple, Optional

from . import __version__, api, c_api, julia, spec


class Target(NamedTuple):
    load: Callable  # (spec root, revision=, with_revision=) -> model
    generate: Callable  # model -> {file name: content}


TARGETS = {
    "julia": Target(spec.load, julia.generate),
    "omp_abi": Target(api.load, c_api.generate),
}


def write(out: pathlib.Path, files: Dict[str, str]) -> None:
    for name, content in files.items():
        path = out / name
        path.parent.mkdir(parents=True, exist_ok=True)
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
        description="Generate OpenMP support code from the OpenMP specification sources.",
    )
    p.add_argument(
        "--spec",
        type=pathlib.Path,
        default=os.environ.get("OMP_SPEC_DIR"),
        help="root of the OpenMP specification sources (default: $OMP_SPEC_DIR)",
    )
    p.add_argument("--julia", type=pathlib.Path, help="output directory of the Julia directive syntax")
    p.add_argument("--omp-abi", type=pathlib.Path, help="root of omp-abi: generate its OpenMP API")
    p.add_argument("--revision", help="spec revision recorded in the generated files (default: git revision of --spec)")
    p.add_argument("--no-revision", action="store_true", help="do not record the spec revision")
    p.add_argument("--check", action="store_true", help="only check that the output is up to date (exit 1 if not)")
    p.add_argument("--diff", action="store_true", help="with --check, print the differences")
    p.add_argument("-q", "--quiet", action="store_true", help="do not print the warnings")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    args = p.parse_args(argv)

    if args.spec is None:
        p.error("the specification sources are required: pass --spec or set OMP_SPEC_DIR")
    jobs = [(name, getattr(args, name)) for name in TARGETS if getattr(args, name) is not None]
    if not jobs:
        p.error("pass --julia and/or --omp-abi")

    ok = True
    for name, out_dir in jobs:
        target = TARGETS[name]
        try:
            model = target.load(args.spec, revision=args.revision, with_revision=not args.no_revision)
        except spec.SpecError as e:
            print(f"error: {name}: {e}", file=sys.stderr)
            return 2
        if not args.quiet:
            for w in model.warnings:
                print(f"warning: {name}: {w}", file=sys.stderr)

        files = target.generate(model)
        if args.check:
            if check(out_dir, files, show_diff=args.diff):
                print(f"{out_dir} is up to date")
            else:
                ok = False
        else:
            write(out_dir, files)
    return 0 if ok else 1
