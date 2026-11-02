# omp-generator

Generates OpenMP support code from the sources of the OpenMP specification:

| option          | output                                                         |
|-----------------|----------------------------------------------------------------|
| `--julia DIR`   | the directive syntax, as Julia data constructing `..Schema` types |
| `--omp-abi DIR` | the OpenMP API of [omp-abi](https://github.com/Julia-OpenMP/omp-abi) |

**The specification sources are not public, but the generated code is.** Only structural facts
(names, types, values, properties) are carried over, never prose. The tests use a synthetic
specification (`tests/fixtures/spec`) that checks no prose leaks.

## Usage
Python 3.9+, standard library only.
```bash
python3 -m omp_generator --spec /path/to/OpenMP-spec --julia OUT_DIR --omp-abi /path/to/omp-abi
```
Add `--check` (and `--diff`) to only check that the output is up to date. `--spec` defaults to
`$OMP_SPEC_DIR`.

## Tests
```bash
python3 -m unittest discover -s tests
```
