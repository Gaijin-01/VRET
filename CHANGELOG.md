# Changelog

All notable changes to the VRET CLI/CUDA line are recorded here.

This project follows a line of its own. It is **not** the successor of the VRET
Research Reference `v0.2.0` release; that is a separate product with its own
version line (see <https://github.com/Gaijin-01/VRET-Research-Reference>).

## [0.2.0] — 2026-11-02

Publication rebuild. The public repository is republished from a clean tree so
that the published tree matches exactly what the package ships, with no
leftover research lane and no superseded receipts.

### Changed

* **Shipped tree reduced to the minimal redistributable set**: 49 files
  remain, of which 31 are the checkpoint. 32 files were removed — the
  bulk/physical benchmark drivers, the host-ceiling probe, the iteration loop,
  and the superseded first-pass receipts and logs. An AST import-graph audit
  of the packaged tree confirms none of them was imported by a shipped module,
  and none was required by the CLI's `doctor` checks or by the protected
  executors' runtime contract.
* **`cpu_shim/` is retained.** `batch_execution.py` compiles
  `cpu_shim/driver.cpp` as the CPU oracle the GPU path is compared against,
  so it is a runtime dependency rather than research material.
* **Documentation rewritten against the shipped tree.** `README.md`,
  `docs/provenance.md`, `docs/release_acceptance.md`,
  `docs/benchmark_receipt.md` and the checkpoint's
  `PHYSICAL_PIPELINE_REPORT.md` no longer reference files that are not
  published, and no longer point at the upstream research drivers as if they
  were redistributable.
* **Version metadata synchronised to `0.2.0`** across `vret_cli/VERSION`,
  `vret_cli/__init__.py`, `pyproject.toml`, the build backend and
  `CITATION.cff`.

### Not changed

* No receipt was edited, regenerated or re-measured. `acceptance.json`,
  `pipeline_ab.json`, `pipeline_equivalence_cuda.json` and the dated fresh
  receipts ship byte-identical to the previous release.
* All 18 hash-pinned protected files ship byte-identical. `vret status`
  still reports `VERIFIED` on the reduced tree.
* No measured value changed. The screening rates, ratios, equivalence counts
  and telemetry in `docs/benchmark_receipt.md` are the same numbers, on the
  same hardware, as before.
* The runtime contract of `vret run`, including the single deliberate
  `chdir` difference from the development copy, is unchanged and still pinned
  by `tests/test_runtime_semantics.py`.

### Added

* An executable preflight checklist driving the whole publish path — tree
  shape, backups, protected hashes, secret scan, media absence, manifest
  consistency, tests, package build, version consistency, removed-artifact
  audit, host-path disclosure, delete authorisation, tag/tree equivalence,
  anonymous clone and release-asset digests. It runs from the release
  workspace and is not part of the shipped tree, because it necessarily
  references the local workspace paths and the authorisation record.

## [0.1.0] — 2026-11-01

First public release of the working VRET CLI/CUDA line.

### Added

* `vret` console script (also `vret-cli`): stdlib-only front end with
  `root`, `status`, `doctor`, `info`, `report`, `receipts` and `run`
  subcommands, and `--version`.
* The immutable VRET checkpoint, shipped inside the wheel as package data:
  CUDA kernels (`sha256_device.cu`, `sha256_batch.cu`), the strict / bulk /
  pipeline executors, the CPU shim, the validation suites and the receipt
  inventory.
* `PIPELINED_POLICY_V1` policy document, hash-pinned as a protected file.
* Receipts: frozen historical acceptance and A/B receipts at the checkpoint
  root, plus dated fresh evidence under `receipts/fresh-2026-10-31/`.

### Measured on this release

* Pipeline screening throughput **14,378,740 candidates/s**; non-pipelined
  12,689,379 candidates/s; CPU comparator 1,181,864 candidates/s.
* Physical equivalence **500/500** episodes, 0 mismatches; frozen original
  results unchanged 12/12.
* Protected source hashes verified: 18/18.

### Changed relative to the internal working copy

Two runtime adjustments, both required by packaging and both covered by the
release test suite:

* the default checkpoint root is now resolved relative to the installed
  package (`<package>/checkpoint`) instead of an absolute path on the
  development machine; `VRET_ROOT` still overrides it;
* `vret run` executes the selected script in place, with the checkpoint root as
  the working directory, exactly as the development copy does. Path
  containment checks, the no-shell rule and literal argument passing are
  unchanged;
* `vret run` launches the script through a small interpreter shim that makes
  `os.chdir` tolerate a directory that does not exist. The development copy has
  no shim and propagates `FileNotFoundError`. This exists because four
  hash-pinned checkpoint modules `chdir` into the upstream workspace path that
  is absent from an installed package. `tests/test_runtime_semantics.py` pins
  the difference, so it is a deliberate and documented delta, not a silent
  cleanup.

No checkpoint file was edited to produce this release. The 18 hash-pinned
files are byte-identical to the working checkpoint.
