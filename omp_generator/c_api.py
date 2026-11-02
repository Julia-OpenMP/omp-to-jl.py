"""The OpenMP API of omp-abi: ``omp.h`` with every name prefixed ``omp_abi_`` and portable
types, which omp-abi converts to the selected runtime's. omp-abi defines what the
specification leaves to the implementation in ``include/omp-abi/api-impl.h``.
"""

from __future__ import annotations

import re
from typing import Dict, Iterable, List

from .api import (
    ALIAS,
    ENUMERATION,
    FUNCTION_POINTER,
    IMPLEMENTATION_DEFINED,
    STRUCTURE,
    Api,
    CType,
    Routine,
    Typedef,
)

PREFIX = "omp_abi_"
WIDTH = 92
INDENT = "    "

# integer arguments holding a device number
DEVICE_ARGUMENTS = re.compile(r"(src_|dst_)?device_num|dev")
# routines returning a device number
DEVICE_RESULTS = re.compile(r"omp_get_\w*device(_num|_from_uid)?")

# native type of the above: device numbers have implementation-defined values
DEVICE_TYPE = "device_number"


def portable(name: str) -> str:
    """Name of an omp.h entity in omp-abi: omp_lock_t -> omp_abi_omp_lock_t."""
    return PREFIX + name


def c_type(ct: CType, typedefs: Iterable[str], *, native: bool = False) -> str:
    """Spelling of a C type: portable (omp_abi_omp_lock_t) or native (omp_lock_t)."""
    base = ct.base if native or ct.base not in typedefs else portable(ct.base)
    s = ("const " if ct.const and ct.pointer else "") + base
    return s + (" " + "*" * ct.pointer if ct.pointer else "")


def declaration(type_: str, name: str) -> str:
    """'int *', 'x' -> 'int *x'."""
    return f"{type_}{'' if type_.endswith('*') else ' '}{name}"


def wrap(head: str, items: List[str], tail: str, indent: str) -> List[str]:
    """`head a, b, c tail` on one line if it fits, else one item per line."""
    one = head + ", ".join(items) + tail
    if len(one) <= WIDTH or len(items) < 2:
        return [one]
    return [head + items[0] + ","] + [indent + it + "," for it in items[1:-1]] + [indent + items[-1] + tail]


def c_value(v: int) -> str:
    return f"{v}u" if v > 2**31 - 1 else str(v)


def c_str(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


class Emitter:
    def __init__(self, api: Api):
        self.api = api
        self.typenames = {t.cname for t in api.typedefs.values()}
        self.enumerators = {e.name for t in api.typedefs.values() for e in t.enumerators + t.predefined}

    def header(self, what: str, *lines: str) -> List[str]:
        rev = f", revision {self.api.revision}" if self.api.revision else ""
        return (
            [f"/* {what}"]
            + [f" * {line}".rstrip() for line in lines]
            + [" *", f" * Generated from the OpenMP {self.api.version} specification{rev}: do not edit.", " */"]
        )

    def ctype(self, ct: CType, *, native: bool = False) -> str:
        return c_type(ct, self.typenames, native=native)

    def default(self, value: str) -> str:
        return portable(value) if value in self.enumerators else value

    # -- types ---------------------------------------------------------------------------

    def ordered_typedefs(self) -> List[Typedef]:
        """Definition order: a type is defined after the types it refers to."""
        ts = sorted(self.api.typedefs.values(), key=lambda t: t.cname)
        by_cname = {t.cname: t for t in ts}
        out: List[Typedef] = []
        seen = set()

        def visit(t: Typedef):
            if t.cname in seen:
                return
            seen.add(t.cname)
            deps = []
            if t.kind == ALIAS and t.ctype:
                deps.append(t.ctype.base)
            deps += [f.ctype.base for f in t.fields]
            if t.signature:
                deps += [t.signature.ret.base] + [p.ctype.base for p in t.signature.parameters]
            for d in deps:
                if d in by_cname:
                    visit(by_cname[d])
            out.append(t)

        for t in ts:
            visit(t)
        return out

    def enumeration(self, t: Typedef) -> List[str]:
        L: List[str] = []
        for e in t.enumerators:
            if e.value is None:
                macro = f"OMP_ABI_VALUE_{e.name}"
                L += [
                    f"#ifndef {macro}",
                    f'# error "{e.name} is implementation defined: define {macro} in omp-abi/api-impl.h"',
                    "#endif",
                ]
        name = portable(t.cname)
        L.append(f"typedef enum {name} {{")
        for e in t.enumerators:
            value = f"OMP_ABI_VALUE_{e.name}" if e.value is None else c_value(e.value)
            note = "  /* of the example omp.h */" if e.from_header else ""
            L.append(f"{INDENT}{portable(e.name)} = {value},{note}")
        extra = f"OMP_ABI_EXTRA_{t.cname}"
        L += [f"#ifdef {extra}", f"{INDENT}{extra}", "#endif", f"}} {name};"]
        return L

    def typedef(self, t: Typedef) -> List[str]:
        name = portable(t.cname)
        if t.kind == ALIAS:
            return [f"typedef {self.ctype(t.ctype)} {name};"]
        if t.kind == IMPLEMENTATION_DEFINED:
            L = [f"/* {name}: implementation defined, in omp-abi/api-impl.h */"]
            for p in t.predefined:
                if p.value is None:
                    L.append(f"/* {p.name}: implementation defined, not provided */")
                else:
                    L.append(f"#define {portable(p.name)} {c_value(p.value)}")
            return L
        if t.kind == ENUMERATION:
            return self.enumeration(t)
        if t.kind == STRUCTURE:
            L = [f"typedef struct {name} {{"]
            L += [f"{INDENT}{declaration(self.ctype(f.ctype), f.name)};" for f in t.fields]
            L.append(f"}} {name};")
            return L
        if t.kind == FUNCTION_POINTER:
            sig = t.signature
            params = [declaration(self.ctype(p.ctype), p.name) for p in sig.parameters] or ["void"]
            return wrap(f"typedef {self.ctype(sig.ret)} (*{name})(", params, ");", INDENT * 2)
        raise AssertionError(t.kind)

    # -- routines ------------------------------------------------------------------------

    def prototype(self, r: Routine) -> List[str]:
        params = []
        for p in r.parameters:
            d = declaration(self.ctype(p.ctype), p.name)
            if p.default is not None:
                d += f" OMP_ABI_DEFAULT({self.default(p.default)})"
            params.append(d)
        ret = self.ctype(r.ret)
        head = f"{ret}{'' if ret.endswith('*') else ' '}OMP_ABI({r.name})("
        return wrap(head, params or ["void"], ");", " " * len(head))

    def native_type(self, r: Routine, ct: CType, name: str = "") -> str:
        if ct.base == "int" and ct.pointer == 0:
            if (name and DEVICE_ARGUMENTS.fullmatch(name)) or (not name and DEVICE_RESULTS.fullmatch(r.name)):
                return DEVICE_TYPE
        return self.ctype(ct, native=True)

    def x_entry(self, r: Routine) -> List[str]:
        params = [declaration(self.ctype(p.ctype), p.name) for p in r.parameters] or ["void"]
        args = [p.name for p in r.parameters]
        native = [self.native_type(r, p.ctype, p.name) for p in r.parameters] or ["void"]
        cols = [
            f"X({r.name}, {self.ctype(r.ret)},",
            f"({', '.join(params)}),",
            f"({', '.join(args)}),",
            f"{self.native_type(r, r.ret)}, ({', '.join(native)}))",
        ]
        return [f"{INDENT}{c}" if i == 0 else f"{INDENT}  {c}" for i, c in enumerate(cols)]

    # -- files ---------------------------------------------------------------------------

    def api_h(self) -> str:
        a = self.api
        L = self.header(
            "The OpenMP API, prefixed with omp_abi_, with portable types.",
        )
        L += [
            "",
            "#ifndef OMP_ABI_API_H",
            "#define OMP_ABI_API_H",
            "",
            "#include <stddef.h>",
            "#include <stdint.h>",
            "",
            '#include "omp-abi/prefix.h"',
            '#include "omp-abi/api-impl.h"',
            "",
            "#ifdef __cplusplus",
            'extern "C" {',
            "# define OMP_ABI_DEFAULT(value) = value",
            "#else",
            "# define OMP_ABI_DEFAULT(value)",
            "#endif",
            "",
            f"#define OMP_ABI_OPENMP_VERSION {c_str(a.version)}",
        ]
        if a.revision:
            L.append(f"#define OMP_ABI_OPENMP_SPEC_REVISION {c_str(a.revision)}")
        L += ["", "/* -- types " + "-" * 79 + " */"]
        for t in self.ordered_typedefs():
            L += [""] + self.typedef(t)
        if a.constants:
            L += ["", "/* -- constants of the example omp.h " + "-" * 53 + " */", ""]
            for c in sorted(a.constants.values(), key=lambda c: c.name):
                v = c_value(c.value)
                L.append(f"#define {portable(c.name)} {'(' + v + ')' if c.value < 0 else v}")
        L += ["", "/* -- routines " + "-" * 76 + " */", ""]
        for n in sorted(a.routines):
            L += self.prototype(a.routines[n])
        L += ["", "#ifdef __cplusplus", "}", "#endif", "", "#endif /* OMP_ABI_API_H */", ""]
        return "\n".join(L)

    def routines_h(self) -> str:
        L = self.header(
            "The API routines: X(name, return type, (parameters), (arguments),",
            "native return type, (native parameter types)). Native types are unprefixed, and",
            f"`{DEVICE_TYPE}` for device numbers.",
        )
        L += ["", "#ifndef OMP_ABI_SRC_API_ROUTINES_H", "#define OMP_ABI_SRC_API_ROUTINES_H", ""]
        L += [f"#define OMP_ABI_API_ROUTINE_COUNT {len(self.api.routines)}", ""]
        body: List[str] = []
        for n in sorted(self.api.routines):
            body += self.x_entry(self.api.routines[n])
        L.append("#define OMP_ABI_API_ROUTINES(X) \\")
        L += [line + " \\" for line in body[:-1]] + [body[-1]] if body else ["    /* none */"]
        L += ["", "#endif /* OMP_ABI_SRC_API_ROUTINES_H */", ""]
        return "\n".join(L)

    def native_types_inc(self) -> str:
        L = self.header(
            "Native types defaulting to the portable ones, unless OMP_ABI_NATIVE_<type>.",
        )
        L.append("")
        for t in self.ordered_typedefs():
            L += [
                f"#ifndef OMP_ABI_NATIVE_{t.cname}",
                f"typedef ::{portable(t.cname)} {t.cname};",
                "#endif",
            ]
        L.append("")
        return "\n".join(L)

    def files(self) -> Dict[str, str]:
        return {
            "include/omp-abi/api.h": self.api_h(),
            "src/api/routines.h": self.routines_h(),
            "src/api/native-types.inc": self.native_types_inc(),
        }


def generate(api: Api) -> Dict[str, str]:
    """Map of file name (relative to the root of omp-abi) -> content."""
    return Emitter(api).files()
