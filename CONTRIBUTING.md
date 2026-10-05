# Contributing

Small fixes, reproducible failure cases and port reviews are welcome. Open an issue
before a new CPU port, format change or broad feature; state the product need and
the memory, execution-time and fault-context constraints. English and Chinese are
both welcome. No contribution implies support for an untested board.

## Development

Run `make verify` and `make sanitize` from the repository root. A target-side change
also needs the complete RV32 build and `make qemu-test` sequence in the README.
Offline/debugger changes also need `scripts/test-debug.py` in the independent
tool image, including actual GDB and corrupt-state cases.
Use C11, four-space indentation in new code, fixed-width serialized fields and
`ck_` names for public functions. Existing compact code can be reformatted in a
separate change. No formatter configuration is enforced; compiler warnings are
errors. Python requires 3.9+, standard library only and explicit UTF-8 for text.

Keep encoder, CPU entry, OS adapter and BSP responsibilities separate. Fatal paths
must not allocate, take normal logging locks, invoke scheduler APIs or traverse
unbounded private kernel lists. Document whitelist, freeze, stack and re-entry
contracts. Never label a compiler fence as durable storage synchronization.

## Tests and pull requests

C assertions are in `tests/test_core.c`; Python tests use `unittest` and names
`test_*.py` / `test_*`. Add tests for new behavior and malformed input. No percentage
coverage threshold is established; relevant failure/degradation cases are required.

A PR should explain the trigger, resulting behavior, limits and commands run.
Link an issue when applicable. CPU changes need original logs plus tool versions,
source hashes, PC/cause checks and firmware-ID matching. Attach rendered screenshots
only for meaningful report changes. Describe failures; do not treat timeout or
nonzero exit as proof of successful negative testing.

Use concise commits such as `fix(reader): reject invalid task ranges` or
`docs(porting): explain mscratch ownership`. There is no older project history to
infer conventions from. Preserve MIT notices and disclose third-party code sources.
Do not upload customer dumps, real memory images, credentials or local build trees.
Generated demo evidence is recreated by tests and is not checked in by default.

Public documents are explicitly listed in `scripts/release.py`. Keep internal
design/planning notes outside the repository. Local collaboration files are not
part of Git or release archives; adding public documentation requires updating
the allowlist and reviewing its publication scope.
