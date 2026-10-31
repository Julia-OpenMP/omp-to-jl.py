# omp-generator

Generates the OpenMP directive front-end of [OMP.jl](https://github.com/Julia-OpenMP/OMP.jl)
from the sources of the OpenMP specification.

The OpenMP specification sources describe every directive, clause, clause-group, modifier and
modifier-group in JSON (`json/*/`), plus the grammar of compound directive names
(`appendices/grammar_compound_directives.tex`). omp-generator turns them into native Julia
code: data that the hand-written parser of OMP.jl interprets.

**The specification sources are not public, but the generated code is.** Only structural facts
are carried over: names, argument and modifier types, syntactic properties and cross references.
No text of the specification is copied (descriptions, notes, section names, index entries and
source file names are ignored), and the generator itself contains no specification data. The
tests use a synthetic specification (`tests/fixtures/spec`) that checks no prose leaks.

## Usage
Python 3.9+, standard library only.
```bash
# regenerate OMP.jl's front-end data (from this directory)
python3 -m omp_generator --spec /path/to/OpenMP-spec --out ../OMP.jl/src/frontend/generated

# CI: fail if the generated files are out of date (--diff shows the differences)
python3 -m omp_generator --spec /path/to/OpenMP-spec --out ../OMP.jl/src/frontend/generated --check

# or install the `omp-generator` command
pip install -e .
```
`--spec` defaults to `$OMP_SPEC_DIR`. The OpenMP version and the git revision of the
specification sources are recorded in the generated files (`--revision`, `--no-revision`).

## Tests
```bash
python3 -m unittest discover -s tests
```
One test loads the generated code in Julia: it needs `julia` and the OMP.jl sources
(`$OMP_JL_DIR`, default `../OMP.jl`), and is skipped otherwise.

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

### The generated / hand-written boundary in OMP.jl
| file(s)                                | owner                                    |
|----------------------------------------|------------------------------------------|
| `src/frontend/generated/*.jl`          | omp-generator: never edit, regenerate    |
| `src/frontend/schema.jl`               | maintainers: the types the generated code constructs (the contract with this generator) |
| everything else in `src/frontend/`     | maintainers                              |

Changing the contract (a field of a `Schema` type) means changing `schema.jl` and
`julia.py` together. Facts that the JSON gets wrong are not patched in generated code: OMP.jl
lists them in `IGNORED_PROPERTIES` (`src/frontend/conventions.jl`), to be fixed upstream.

### Other targets
`julia.py` is one backend of the model: a backend is a function from `model.Spec` to a map of
file names to contents, registered in `cli.TARGETS`.
