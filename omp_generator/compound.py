"""Compound directive names, from the grammar of the specification
(``appendices/grammar_compound_directives.tex``).

The grammar is a list of rules::

    \\plc{nonterminal}:
       <production>
       ...

where each production is a whitespace-separated sequence of ``\\plc{nonterminal}`` and
``\\code{leaf-directive}`` symbols, and the first nonterminal is the start symbol.

The grammar alone over-generates: the following restrictions on compound directives
(stated in prose by the specification) prune the expansion:

* a leaf directive appears at most once;
* ``target_data``, ``target_enter_data``, ``target_exit_data`` and ``target_update`` must
  not appear after ``target``;
* no leaf directive appears twice once ``target`` and ``target_data`` are flattened into
  their implicit constituents (``target_data`` behaves as ``target_enter_data task
  target_exit_data``, ``target`` as ``target_enter_data target target_exit_data``).
"""

from __future__ import annotations

import re
from typing import Dict, Iterator, List, Tuple

Symbol = Tuple[str, str]  # ("nt" | "t", name)

DISALLOWED_AFTER_TARGET = ("target_data", "target_update", "target_enter_data", "target_exit_data")
IMPLICIT_CONSTITUENTS = {
    "target_data": ("target_enter_data", "task", "target_exit_data"),
    "target": ("target_enter_data", "target", "target_exit_data"),
}

_RULE = re.compile(r"^\\plc\{([^}]*)\}\s*:\s*$")
_SYMBOL = re.compile(r"\\(plc|code)\{([^}]*)\}")


def parse_grammar(text: str) -> Tuple[str, Dict[str, List[List[Symbol]]]]:
    grammar: Dict[str, List[List[Symbol]]] = {}
    start = None
    current = None
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("%") or line.startswith("\\begin") or line.startswith("\\end"):
            continue
        m = _RULE.match(line)
        if m:
            current = m.group(1)
            grammar[current] = []
            start = start or current
            continue
        if current is None:
            raise ValueError(f"production outside of a rule: {line!r}")
        symbols = [("nt" if k == "plc" else "t", n) for k, n in _SYMBOL.findall(line)]
        if not symbols:
            raise ValueError(f"cannot parse production {line!r}")
        grammar[current].append(symbols)
    if start is None:
        raise ValueError("empty grammar")
    for prods in grammar.values():
        for prod in prods:
            for k, n in prod:
                if k == "nt" and n not in grammar:
                    raise ValueError(f"undefined nonterminal {n!r}")
    return start, grammar


def _expand(grammar, pending: Tuple[Symbol, ...], prefix: Tuple[str, ...]) -> Iterator[Tuple[str, ...]]:
    if not pending:
        yield prefix
        return
    (kind, name), rest = pending[0], pending[1:]
    if kind == "t":
        if name in prefix:
            return
        if "target" in prefix and name in DISALLOWED_AFTER_TARGET:
            return
        yield from _expand(grammar, rest, prefix + (name,))
    else:
        for prod in grammar[name]:
            yield from _expand(grammar, tuple(prod) + rest, prefix)


def _flattened_unique(leafs: Tuple[str, ...]) -> bool:
    flat = [x for leaf in leafs for x in IMPLICIT_CONSTITUENTS.get(leaf, (leaf,))]
    return len(flat) == len(set(flat))


def compound_directives(text: str) -> List[Tuple[str, ...]]:
    """Sorted list of compound directives (tuples of leaf names, outermost first)."""
    start, grammar = parse_grammar(text)
    out = {
        leafs
        for leafs in _expand(grammar, (("nt", start),), ())
        if len(leafs) > 1 and _flattened_unique(leafs)
    }
    return sorted(out, key=lambda leafs: " ".join(leafs))
