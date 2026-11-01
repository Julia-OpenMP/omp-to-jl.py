# omp-generator

Generates, from the sources of the OpenMP specification, everything of
[OMP.jl](https://github.com/Julia-OpenMP/OMP.jl) and [omp-abi](https://github.com/Julia-OpenMP/omp-abi)
that derives from it:

| target    | output                     | from                                             |
|-----------|----------------------------|--------------------------------------------------|
| `julia`   | OMP.jl: `src/frontend/generated/`, the directive syntax, as data that the hand-written parser of OMP.jl interprets | `json/{directive,clause,clause-group,modifier,modifier-group}/`, `appendices/grammar_compound_directives.tex` |
| `omp-abi` | omp-abi: `include/omp-abi/api.h`, the OpenMP API (`omp.h`: routines, types) with portable types; `src/api/{routines.h,native-types.inc}`, its description for the backends | `json/routine/`, `json/typedef/`, `appendices/omp.h` |

OMP.jl gets the API from omp-abi, through its Clang.jl bindings (`OMP.jl/res/wrap.jl`).

**The specification sources are not public, but the generated code is.** Only structural facts
are carried over: names, argument and modifier types, syntactic properties and cross references.
No text of the specification is copied (descriptions, notes, section names, index entries and
source file names are ignored), and the generator itself contains no specification data. The
tests use a synthetic specification (`tests/fixtures/spec`) that checks no prose leaks.

## Usage
Python 3.9+, standard library only.
```bash
# regenerate everything (from this directory): the command to run when the spec evolves
python3 -m omp_generator --spec /path/to/OpenMP-spec --omp-jl ../OMP.jl --omp-abi ../omp-abi

# CI: fail if the generated files are out of date (--diff shows the differences)
python3 -m omp_generator --spec /path/to/OpenMP-spec --omp-jl ../OMP.jl --omp-abi ../omp-abi --check

# a single target, in any directory
python3 -m omp_generator --spec /path/to/OpenMP-spec --target omp-abi --out /tmp/omp-abi

# or install the `omp-generator` command
pip install -e .
```
`--spec` defaults to `$OMP_SPEC_DIR`. Warnings (`-q` hides them) report what was skipped,
e.g. a routine of an unknown type, and the differences between the JSON and `omp.h`. The OpenMP version and the git revision of the
specification sources are recorded in the generated files (`--revision`, `--no-revision`).

## Tests
```bash
python3 -m unittest discover -s tests
```
One test loads the generated Julia code in Julia: it needs `julia` and the OMP.jl sources
(`$OMP_JL_DIR`, default `../OMP.jl`); another compiles the generated C header with `gcc` and
`g++`. Each is skipped when its tools are missing.

## Design
```
spec sources ──spec.py──▶ model (model.py) ──julia.py──▶ OMP.jl/src/frontend/generated/*.jl
 (JSON, tex)      │                                         (constructs Schema types)
                  └─ compound.py: expands the compound directive grammar
```

| module                    | role                                                                |
|---------------------------|---------------------------------------------------------------------|
| `omp_generator/model.py`  | language-neutral model: `Directive`, `Clause`, `Modifier`, `Argument`, ... |
| `omp_generator/spec.py`   | loads and normalizes the JSON, checks cross references               |
| `omp_generator/compound.py` | expands the grammar of compound directive names                   |
| `omp_generator/julia.py`  | Julia backend                                                        |
| `omp_generator/api.py`    | API routines and types: model, loader, `omp.h` parser and cross-check |
| `omp_generator/c_api.py`  | C backend of the API, for omp-abi                                    |
| `omp_generator/cli.py`    | command line                                                         |

Normalization worth knowing:

* every argument, modifier value and list item gets a `kind` out of a closed set (`keyword`,
  `complex`, `list`, `list_item`, `expression`, `variable`, `identifier`, `directive_name`,
  `directive_specification`, `type_name`, `stylized`), the precise OpenMP type being kept in
  `type` (e.g. `"OpenMP logical"`, `"locator list item"`);
* modifier references are resolved (with their clause-local `modifying` and properties), and
  modifier-groups are expanded into the modifiers of each clause plus a modifier-set;
* clause-groups whose members are directive names (`cancel-directive-name`) get the directive
  property that selects them (`cancellable`): this is the only fact not read from the JSON,
  together with the pruning rules of compound directives stated in prose by the specification
  (see `compound.py`);
* names are converted to Julia identifiers (`task-dependence-type` → `task_dependence_type`),
  Julia keywords are quoted (`var"for"`, `Symbol("in")`), and the entity modules are
  `baremodule`s so that constants such as `map` or `filter` do not clash with `Base`.

### The API routines and types
The JSON describes each routine for C and Fortran (`iso_c`, `value`, `intent(in)`, ...):
`api.py` derives its C prototype (`int` for `integer` and `logical`, `const` pointee for an
`intent(in)` pointer, a pointer for an `intent(out)` argument, ...). The JSON is the reference:
the example `omp.h` lacks recent routines. It is only cross-checked against the JSON (any
difference is a warning), and provides what the JSON does not describe: the constants of its
anonymous enumerations (`omp_initial_device`, ...), and the enumerators of the enumerations
that the JSON leaves to the implementation (the `omp_ifr_*` next to `omp_ifr_last`).

`c_api.py` emits the API of omp-abi. Every name gets the `omp_abi_` prefix
(`omp_abi_omp_get_num_threads`, `omp_abi_omp_lock_t`), so that omp-abi never interposes the
runtime's symbols; OMP.jl drops it again. The types are omp-abi's own (portable): each
backend of omp-abi converts them to its runtime's ABI. What the specification leaves to the
implementation is decided by omp-abi's hand-written `include/omp-abi/api-impl.h`, which the
generated header includes:

* the implementation-defined types (locks, `omp_depend_t`, `omp_interop_t`, ...);
* `OMP_ABI_VALUE_<name>`: an implementation-defined enumerator (`omp_ifr_last`); the
  generated header does not compile without it;
* `OMP_ABI_EXTRA_<type>`: extra enumerators (a pointer-sized sentinel for the handles).

For the backends, `src/api/routines.h` lists every routine with its portable and *native*
signature (unprefixed `omp.h` names, which each backend defines for its runtime, defaulting to
the portable types in `native-types.inc`). Device numbers are the native type
`device_number`: integer arguments named `device_num`, `src_device_num`, `dst_device_num` or
`dev`, and the result of `omp_get_*device`, `omp_get_device_num` and `omp_get_device_from_uid`
(`DEVICE_ARGUMENTS`, `DEVICE_RESULTS`), whose implementation-defined values differ between
runtimes.

### The generated / hand-written boundary
| file(s)                                | owner                                    |
|----------------------------------------|------------------------------------------|
| OMP.jl `src/frontend/generated/*.jl`   | omp-generator: never edit, regenerate    |
| OMP.jl `src/frontend/schema.jl`        | maintainers: the types the generated code constructs (the contract with `julia.py`) |
| everything else in OMP.jl `src/frontend/` | maintainers                           |
| omp-abi `include/omp-abi/api.h`, `src/api/routines.h`, `src/api/native-types.inc` | omp-generator: never edit, regenerate |
| omp-abi `include/omp-abi/api-impl.h`   | maintainers: the implementation-defined parts of the API |
| omp-abi `src/api/forward.h`, `src/backend/*/api.cc` | maintainers: the forwarding to each runtime, and its conversions (the contract with `c_api.py`) |

Changing the contract (a field of a `Schema` type) means changing `schema.jl` and
`julia.py` together. Facts that the JSON gets wrong are not patched in generated code: OMP.jl
lists them in `IGNORED_PROPERTIES` (`src/frontend/conventions.jl`), to be fixed upstream.

### Other targets
`julia.py` is one backend of the model: a backend is a function from `model.Spec` to a map of
file names to contents, registered in `cli.TARGETS`.
