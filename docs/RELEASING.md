# Preparing and publishing a release

## Local candidate

Run from the repository root:

```sh
make verify
make sanitize
python3 scripts/fetch-freertos.py
# Build all RV32 cases using the README's Docker command (or make rv32-build).
make qemu-test
make package
python3 scripts/verify-release.py build/release/freertos-crashkit-0.1.0.tar.gz
```

Packaging uses an explicit source allowlist and fixed archive metadata. It writes
a deterministic tar.gz, SHA256SUMS and an embedded per-file MANIFEST.json. The
manifest is not a signature. Runtime evidence, binaries, toolchains, upstream
archives, Git metadata and private knowledge-base material are excluded.

The verifier checks safe member names, member types, exact manifest membership,
sizes and hashes, then extracts to a fresh directory and runs `make verify` and
`make sanitize`. Use `--output path` to retain that extraction for a clean RV32
build and `make qemu-test`; `--output` must not already exist. Reuse an official
archive with `scripts/fetch-freertos.py --archive path` if testing offline. Never
reuse a previously populated build tree as evidence of clean-source usability.

Tests and the archive must correspond to the final source. Any later source or
build-script change requires rebuilding and rerunning relevant checks. Keep an
external acceptance record (`build/release/ACCEPTANCE.json`) with candidate SHA,
checks, versions and limitations; do not put a self-referencing hash inside the
archive. The packager checks VERSION against the public header version.

## Remote publication (separate from local preparation)

Create an independent public repository only when the owner authorizes publication.
Publish only its source tree, never the surrounding personal knowledge base.
No remote URL, badge success or CI run is fabricated by this candidate.

After pushing reviewed source, require the host and RV32 GitHub Actions jobs to
pass on that exact commit. The workflow uses a pinned checkout commit, read-only
contents permission and ordinary pull_request events; it does not publish releases
or consume deployment secrets. See GitHub's [secure-use guidance](https://docs.github.com/en/actions/reference/security/secure-use)
and the pinned [checkout release](https://github.com/actions/checkout/releases/tag/v7.0.1).
The build container runs with the checkout owner's UID/GID and no capabilities,
so write access follows normal Unix ownership even on a Linux runner.
The workflow targets GitHub-hosted Ubuntu 24.04 runners; checkout uses Node 24
and needs runner v2.327.1+ if adapted to self-hosting, per its [official README](https://github.com/actions/checkout/blob/v7.0.1/README.md).
CI configuration supplied locally is not remote CI evidence.

Then check changelog/version, third-party notices, the real repository's reporting
channel and issue templates. Create an annotated `v0.1.0` tag for the tested commit;
attach the verified source archive and SHA256SUMS, label the release experimental,
and repeat the support matrix and known gaps. Git tags are not automatically signed.
Update this guide's candidate status only after actual publication.

## Initial scope

0.1.0 closes the capture/inspect/test/distribute loop. Real-board ports, persistent
storage, automatic task lifecycle, assert/overflow entry and precise stack unwinding
are subsequent milestones; they are not prerequisites falsely marked complete by
the publication work. Chinese roadmap: [验收与后续任务](RELEASING.md).
