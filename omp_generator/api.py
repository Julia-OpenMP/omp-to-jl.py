"""Load the OpenMP API routines and types (``omp.h``) from the specification sources:
``json/routine/omp_*.json``, ``json/typedef/*.json``, and ``appendices/omp.h``, which is only
cross-checked, plus the source of what the JSON lacks (constants of anonymous enumerations,
enumerators of implementation-defined enumerations).

The JSON describes C and Fortran (``iso_c``, ``intent(in)``, ...): the C prototypes are derived.
"""

from __future__ import annotations

import json
import pathlib
import re
from dataclasses import dataclass, field, replace
from typing import Dict, List, Optional, Tuple

from .spec import SpecError, _git_revision, _version

# -- model -------------------------------------------------------------------------------


@dataclass(frozen=True)
class CType:
    """``const`` qualifies the pointee; a ``const`` value is not part of the interface."""

    base: str
    pointer: int = 0
    const: bool = False

    def __str__(self) -> str:
        s = ("const " if self.const and self.pointer else "") + self.base
        return s + (" " + "*" * self.pointer if self.pointer else "")


@dataclass(frozen=True)
class Parameter:
    name: str
    type: str  # spec type: "integer", "c_ptr", "sched", ...
    ctype: CType
    properties: Tuple[str, ...] = ()
    # C++ default argument (literal or enumerator), or NULL for an optional pointer
    default: Optional[str] = None

    @property
    def optional(self) -> bool:
        return "optional" in self.properties


@dataclass(frozen=True)
class Routine:
    name: str
    category: str  # "function" | "subroutine"
    return_type: Optional[str]  # spec type, None for subroutines
    ret: CType
    parameters: Tuple[Parameter, ...]
    properties: Tuple[str, ...] = ()

    @property
    def logical(self) -> bool:
        """Returns an OpenMP logical (a C int)."""
        return self.return_type == "logical"

    def prototype(self) -> str:
        params = ", ".join(f"{p.ctype}{'' if p.ctype.pointer else ' '}{p.name}" for p in self.parameters)
        sep = "" if self.ret.pointer else " "
        return f"{self.ret}{sep}{self.name}({params or 'void'});"


@dataclass(frozen=True)
class Enumerator:
    name: str
    value: Optional[int]  # None: implementation defined
    spelling: str  # as written in the spec
    from_header: bool = False  # only in the example omp.h, not in the JSON


# kinds of Typedef
ENUMERATION = "enumeration"
STRUCTURE = "structure"
ALIAS = "alias"  # a C integer type, or another typedef
IMPLEMENTATION_DEFINED = "implementation-defined"  # opaque, or an implementation-defined integer
FUNCTION_POINTER = "function-pointer"


@dataclass(frozen=True)
class Typedef:
    name: str  # spec name: "sched"
    cname: str  # C name: "omp_sched_t"
    kind: str
    # enumeration: C type that holds every value ("int" or "unsigned int")
    # alias: the aliased C type
    ctype: Optional[CType] = None
    enumerators: Tuple[Enumerator, ...] = ()
    fields: Tuple[Parameter, ...] = ()  # structure members
    signature: Optional[Routine] = None  # function pointer
    predefined: Tuple[Enumerator, ...] = ()  # predefined instances: omp_interop_none
    properties: Tuple[str, ...] = ()


@dataclass(frozen=True)
class Constant:
    """A constant of the example header that the JSON does not describe."""

    name: str
    value: int


@dataclass
class Api:
    version: str
    revision: Optional[str]
    typedefs: Dict[str, Typedef] = field(default_factory=dict)  # by spec name
    routines: Dict[str, Routine] = field(default_factory=dict)
    constants: Dict[str, Constant] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)


# -- spec types -> C types ---------------------------------------------------------------

# Spec types that are C (or Fortran ISO_C_BINDING) scalar types
SCALARS = {
    "integer": "int",
    "logical": "int",
    "c_int": "int",
    "c_size_t": "size_t",
    "size_t": "size_t",
    "double": "double",
    "char": "char",
    "const char": "char",
    "void": "void",
    "c_ptr": "void",  # TYPE(C_PTR): a void * in C (see `ctype`)
    "c_intptr_t": "intptr_t",
    "c_uintptr_t": "uintptr_t",
}

POINTER_PROPERTIES = {"pointer", "C/C++ pointer"}

# C macros found as enumerator values
C_LIMITS = {
    "INT32_MAX": 2**31 - 1,
    "INT_MAX": 2**31 - 1,
    "UINT32_MAX": 2**32 - 1,
    "UINT_MAX": 2**32 - 1,
}


def cname(typedef: str) -> str:
    """Spec name of a type -> its C name: 'sched' -> 'omp_sched_t'."""
    return f"omp_{typedef}_t"


def parse_int(s: str) -> Optional[int]:
    """A C integer literal ('0x80000000u', '-1') or limit macro, else None."""
    s = s.strip()
    if s in C_LIMITS:
        return C_LIMITS[s]
    m = re.fullmatch(r"([+-]?)\s*(0[xX][0-9a-fA-F]+|\d+)[uUlL]*", s)
    if not m:
        return None
    v = int(m.group(2), 0)
    return -v if m.group(1) == "-" else v


class Loader:
    def __init__(self, root: pathlib.Path):
        self.root = pathlib.Path(root)
        self.json = self.root / "json"
        if not self.json.is_dir():
            raise SpecError(f"{self.json} is not a directory: is {self.root} the root of the OpenMP spec sources?")
        self.warnings: List[str] = []
        self.typedefs: Dict[str, dict] = {}

    def warn(self, msg: str):
        self.warnings.append(msg)

    def load_raw(self, kind: str) -> Dict[str, dict]:
        out: Dict[str, dict] = {}
        d = self.json / kind
        if not d.is_dir():
            raise SpecError(f"{d} is not a directory")
        for f in sorted(d.glob("*.json")):
            try:
                raw = json.loads(f.read_text(encoding="utf-8"))
            except json.JSONDecodeError as e:
                raise SpecError(f"{f}: invalid JSON: {e}") from e
            name = raw.get("$name")
            if not name:
                raise SpecError(f"{f}: missing $name")
            out[name] = raw
        return out

    def ctype(self, type_: str, properties, *, by_value_ptr: bool = True) -> CType:
        """C type of a parameter / field / return value from its spec type and properties.
        Raises KeyError for an unknown spec type."""
        props = set(properties or ())
        if type_ in SCALARS:
            base = SCALARS[type_]
        elif type_ in self.typedefs:
            base = cname(type_)
        else:
            raise KeyError(type_)
        # an output argument is passed by address in C, even when the JSON (written for
        # Fortran as well) does not say so (e.g. `ret_code` of omp_get_interop_int)
        ptr = 1 if props & POINTER_PROPERTIES or "intent(out)" in props else 0
        if type_ == "c_ptr" and by_value_ptr:
            ptr += 1
        const = bool(ptr) and ("intent(in)" in props or type_ == "const char")
        return CType(base, ptr, const)

    # -- typedefs --------------------------------------------------------------------------

    def typedef(self, name: str, raw: dict) -> Optional[Typedef]:
        base = raw.get("basetype")
        props = tuple(raw.get("properties") or ())
        cn = cname(name)
        if base == "enumeration":
            enums = []
            for v in raw.get("values") or ():
                spelling = str(v.get("val", "")).strip()
                enums.append(Enumerator(v["$name"], parse_int(spelling), spelling))
            known = [e.value for e in enums if e.value is not None]
            fits_int = all(-(2**31) <= x < 2**31 for x in known)
            return Typedef(name, cn, ENUMERATION, CType("int" if fits_int else "unsigned int"), tuple(enums),
                           properties=props)  # fmt: skip
        if base == "structure":
            fields = []
            for f in raw.get("fields") or ():
                try:
                    ct = self.ctype(f["$type"], f.get("properties"))
                except KeyError:
                    self.warn(f"type {name}: field {f.get('$name')}: unknown type {f['$type']!r}: type skipped")
                    return None
                fields.append(Parameter(f["$name"], f["$type"], ct, tuple(f.get("properties") or ())))
            return Typedef(name, cn, STRUCTURE, fields=tuple(fields), properties=props)
        if base == "pod":
            common = raw.get("commontype")
            if common in SCALARS:
                ct = CType(SCALARS[common])
            elif common in self.typedefs:
                ct = CType(cname(common))
            else:
                self.warn(f"type {name}: unknown common type {common!r}: type skipped")
                return None
            return Typedef(name, cn, ALIAS, ct, properties=props)
        if base in ("opaque", "implementation-defined-int"):
            predefined = tuple(
                Enumerator(p["$name"], parse_int(str(p.get("val", ""))), str(p.get("val", "")))
                for p in raw.get("predefined_instances") or ()
            )
            return Typedef(name, cn, IMPLEMENTATION_DEFINED, predefined=predefined, properties=props)
        if base == "fptr":
            sig = self.routine(cn, raw, what="type")
            if sig is None:
                return None
            return Typedef(name, cn, FUNCTION_POINTER, signature=sig, properties=props)
        self.warn(f"type {name}: unknown basetype {base!r}: type skipped")
        return None

    # -- routines --------------------------------------------------------------------------

    def routine(self, name: str, raw: dict, *, what: str = "routine") -> Optional[Routine]:
        category = raw.get("category", "function")
        rtype = raw.get("return_type") if category == "function" else None
        try:
            if rtype is None:
                ret = CType("void")
            else:
                ret = self.ctype(rtype, raw.get("return_type_properties"))
        except KeyError:
            self.warn(f"{what} {name}: unknown return type {rtype!r}: {what} skipped")
            return None
        params = []
        for a in raw.get("arguments") or ():
            props = tuple(dict.fromkeys(a.get("properties") or ()))  # some properties are repeated
            try:
                ct = self.ctype(a["$type"], props)
            except KeyError:
                self.warn(f"{what} {name}: argument {a.get('$name')}: unknown type {a['$type']!r}: {what} skipped")
                return None
            default = a.get("default_value")
            if default is None and "optional" in props and ct.pointer:
                default = "NULL"
            params.append(Parameter(a["$name"], a["$type"], ct, props, default))
        # a default value is only usable when all the following parameters have one
        out: List[Parameter] = []
        trailing = True
        for p in reversed(params):
            trailing = trailing and p.default is not None
            out.append(p if trailing or p.default is None else Parameter(p.name, p.type, p.ctype, p.properties))
        return Routine(name, category, rtype, ret, tuple(reversed(out)), tuple(raw.get("properties") or ()))


# -- the example header (appendices/omp.h) -----------------------------------------------


def _preprocess(text: str) -> str:
    """Strip comments, and keep the C (not C++) branches of ``#if[n]def __cplusplus``."""
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    text = re.sub(r"//[^\n]*", "", text)
    out, stack = [], []  # stack of "is this branch kept"
    for line in text.splitlines():
        s = line.strip()
        m = re.match(r"#\s*(ifdef|ifndef|if|elif|else|endif)\b\s*(.*)", s)
        if m:
            d, arg = m.groups()
            if d in ("ifdef", "ifndef", "if"):
                cpp = arg.strip() in ("__cplusplus", "defined(__cplusplus)", "defined __cplusplus")
                keep = (not cpp) if d in ("ifdef", "if") else True
                stack.append((keep, cpp))
            elif d in ("else", "elif") and stack:
                keep, cpp = stack.pop()
                stack.append(((not keep) if cpp else keep, cpp))
            elif d == "endif" and stack:
                stack.pop()
            continue
        if s.startswith("#"):
            continue
        if all(k for k, _ in stack):
            out.append(line)
    return "\n".join(out)


_QUALIFIERS = {"const", "volatile", "extern", "struct", "enum", "signed", "unsigned", "restrict"}


def _parse_ctype(decl: str, *, has_name: bool) -> Tuple[CType, Optional[str]]:
    """'const omp_lock_t *lock' -> (CType('omp_lock_t', 1, True), 'lock')."""
    decl = decl.strip()
    array = decl.endswith("]")
    decl = re.sub(r"\[[^\]]*\]$", "", decl).strip()
    tokens = re.findall(r"[A-Za-z_]\w*|\*", decl)
    name = None
    words = [t for t in tokens if t != "*" and t not in _QUALIFIERS]
    if has_name and tokens and tokens[-1] != "*" and tokens[-1] not in _QUALIFIERS and len(words) >= 2:
        name = tokens.pop()
        words.pop()
    ptr = tokens.count("*") + (1 if array else 0)
    base = " ".join(t for t in tokens if t not in ("*", "const", "volatile", "extern", "struct", "enum", "restrict"))
    if base in ("unsigned", "signed"):
        base += " int"
    # const before the first '*' qualifies the pointee
    first_star = tokens.index("*") if "*" in tokens else len(tokens)
    const = ptr > 0 and "const" in tokens[:first_star]
    return CType(base, ptr, const), name


@dataclass
class Header:
    prototypes: Dict[str, Tuple[CType, Tuple[CType, ...]]] = field(default_factory=dict)
    enumerators: Dict[str, Optional[int]] = field(default_factory=dict)  # of named enums
    enums: Dict[str, Dict[str, Optional[int]]] = field(default_factory=dict)  # by type name
    constants: Dict[str, Optional[int]] = field(default_factory=dict)  # of anonymous enums


def parse_header(text: str) -> Header:
    h = Header()
    src = _preprocess(text)
    for m in re.finditer(r"(typedef\s+)?enum\s*(\w*)\s*\{([^}]*)\}\s*(\w*)\s*;", src):
        anonymous = not m.group(2) and not m.group(4)
        values: Dict[str, Optional[int]] = {}
        prev: Optional[int] = -1
        for e in m.group(3).split(","):
            e = e.strip()
            mm = re.fullmatch(r"(\w+)\s*(?:=\s*(.+))?", e, re.S)
            if not mm:
                continue
            n, expr = mm.groups()
            if expr is None:
                v = None if prev is None else prev + 1
            else:
                v = parse_int(expr)
                if v is None:
                    v = values.get(expr.strip(), h.enumerators.get(expr.strip()))
            values[n] = v
            prev = v
        (h.constants if anonymous else h.enumerators).update(values)
        if not anonymous:
            h.enums[m.group(4) or m.group(2)] = values
    for m in re.finditer(r"([^;{}()]*?)\b(omp_\w+)\s*\(([^()]*)\)\s*;", src):
        ret_decl, name, params = m.groups()
        if "typedef" in ret_decl:
            continue
        ret, _ = _parse_ctype(ret_decl, has_name=False)
        ps: List[CType] = []
        for p in params.split(","):
            if p.strip() and p.strip() != "void":
                ps.append(_parse_ctype(p, has_name=True)[0])
        h.prototypes[name] = (ret, tuple(ps))
    return h


def _cross_check(api: Api, header: Header, L: Loader):
    """Report the differences between the JSON and the example header."""
    for name, r in sorted(api.routines.items()):
        if name not in header.prototypes:
            continue
        hret, hparams = header.prototypes[name]
        diffs = []
        if str(hret) != str(r.ret):
            diffs.append(f"returns {r.ret} (omp.h: {hret})")
        if len(hparams) != len(r.parameters):
            diffs.append(f"{len(r.parameters)} parameters (omp.h: {len(hparams)})")
        else:
            for p, hp in zip(r.parameters, hparams):
                if str(p.ctype) != str(hp):
                    diffs.append(f"parameter {p.name} is {p.ctype} (omp.h: {hp})")
        if diffs:
            L.warn(f"omp.h: routine {name}: " + "; ".join(diffs))
    only_json = sorted(set(api.routines) - set(header.prototypes))
    only_header = sorted(set(header.prototypes) - set(api.routines))
    if only_json:
        L.warn(f"omp.h: {len(only_json)} routines are missing (generated from the JSON): {', '.join(only_json)}")
    if only_header:
        L.warn(f"omp.h: {len(only_header)} routines are not in the JSON (not generated): {', '.join(only_header)}")
    for t in api.typedefs.values():
        for e in t.enumerators:
            hv = header.enumerators.get(e.name)
            if e.name in header.enumerators and e.value is not None and hv is not None and hv != e.value:
                L.warn(f"omp.h: {e.name} is {e.value} (omp.h: {hv})")


def _merge_enumerators(api: Api, header: Header):
    """Add the header-only enumerators of the enumerations having an implementation-defined
    enumerator; elsewhere, header-only enumerators are deprecated aliases or typos."""
    for name, t in list(api.typedefs.items()):
        if t.kind != ENUMERATION or t.cname not in header.enums:
            continue
        if all(e.value is not None for e in t.enumerators):
            continue
        known = {e.name for e in t.enumerators}
        extra = tuple(
            Enumerator(n, v, "omp.h", from_header=True)
            for n, v in header.enums[t.cname].items()
            if n not in known and v is not None and not n.startswith("__")
        )
        if extra:
            api.typedefs[name] = replace(t, enumerators=extra + t.enumerators)


# -- entry point -------------------------------------------------------------------------


def load(root, *, revision: Optional[str] = None, with_revision: bool = True) -> Api:
    """Load the API routines and types of the specification sources rooted at ``root``."""
    root = pathlib.Path(root)
    L = Loader(root)
    api = Api(version=_version(root), revision=(revision or (_git_revision(root) if with_revision else None)))

    L.typedefs = L.load_raw("typedef")
    for name, raw in L.typedefs.items():
        t = L.typedef(name, raw)
        if t is not None:
            api.typedefs[name] = t

    for name, raw in L.load_raw("routine").items():
        if not name.startswith("omp_"):  # ompd_*, ompt_*: tool interfaces
            continue
        r = L.routine(name, raw)
        if r is not None:
            api.routines[name] = r

    header_file = root / "appendices" / "omp.h"
    if header_file.is_file():
        header = parse_header(header_file.read_text(encoding="utf-8"))
        _cross_check(api, header, L)
        defined = {e.name for t in api.typedefs.values() for e in t.enumerators + t.predefined}
        for n, v in header.constants.items():
            if n in defined or n.startswith("__"):
                continue
            if v is None:
                L.warn(f"omp.h: cannot evaluate the value of {n}: skipped")
            else:
                api.constants[n] = Constant(n, v)
        _merge_enumerators(api, header)
    else:
        L.warn(f"{header_file} not found: no cross-check, and no constants of the header")

    _check(api)
    api.warnings = L.warnings
    return api


def _check(api: Api):
    names: Dict[str, str] = {}

    def define(n: str, what: str):
        if n in names:
            raise SpecError(f"{n} is defined twice ({names[n]}, {what})")
        names[n] = what

    for t in api.typedefs.values():
        define(t.cname, f"type {t.name}")
        for e in t.enumerators + t.predefined:
            define(e.name, f"type {t.name}")
    for c in api.constants.values():
        define(c.name, "constant")
    for r in api.routines.values():
        define(r.name, "routine")
