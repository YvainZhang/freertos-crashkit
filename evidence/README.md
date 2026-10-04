# Generated verification evidence

Run `make verify` / `make sanitize` for host results and the README's RV32 build
plus `make qemu-test` for target results. Tests regenerate snapshots, logs and
manifests under `build/` and `evidence/qemu-rv32/`. The QEMU manifest contains
actual source/tool hashes, ELF hashes, dump hashes and case results.

These are test-program snapshots, not customer data. Generated evidence is ignored
by Git and excluded from source releases. Historical Chinese prototype reports
link to generated evidence that appears only after the corresponding tests run;
they are not a substitute for testing your checkout. Local release acceptance is
stored separately in `build/release/ACCEPTANCE.json`.
