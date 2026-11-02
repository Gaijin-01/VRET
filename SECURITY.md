# Security policy

## Scope

This repository publishes the VRET **CLI/CUDA line**, version 0.2.0: a
standard-library CLI, the immutable GPU checkpoint it drives, and the receipts
produced by previous runs.

## Trust boundaries

* **No network, no credentials, no telemetry.** The CLI and every checkpoint
  module import only the Python standard library. Nothing in this release
  opens a socket, reads a credential store, or phones home.
* **`vret run` is not a sandbox.** The script path must be relative and must
  resolve inside the checkpoint root; absolute paths, `..` traversal and
  symlink escapes are rejected, and no shell is ever spawned — arguments are
  passed literally to the interpreter. Beyond that, an allowed script runs with
  your own privileges and may modify files it can reach. Run only scripts you
  trust.
* **The checkpoint is treated as immutable.** `vret run` executes the selected
  script in place, with the checkpoint root as its working directory. No file
  is copied, patched or rewritten by a run. The only behavioural difference
  from the development copy is the tolerant `chdir` described below, which is
  covered by `tests/test_runtime_semantics.py`.
* **`VERIFIED` is a local statement.** `vret status` compares the checkpoint's
  protected files against the SHA-256 digests recorded in its own bundled
  receipts. It is not a signature, not a certificate, and not an attestation
  about any workload you run.
* **The CUDA backend loads NVRTC from the host.** `cuda_execution.py`
  discovers `libnvrtc` and prefers a path pattern that matched the machine
  where the checkpoint was developed. On a different host it falls back to the
  platform loader name, and `NVRTC_LIBRARY` can be set to point at an explicit
  library. A host library is trusted host code; verify it as you would any
  other native dependency.
* **Four checkpoint modules reference an upstream workspace path**
  (`/workspace/artifacts/agent-tooling-blueprints`) inside their `__main__`
  blocks. Those files are hash-pinned by the bundled receipts and are
  therefore shipped unchanged. The script launcher installed with this package
  tolerates a `chdir` into that missing directory, so the scripts still run
  from an installed checkpoint; the development copy of the CLI has no such
  shim and raises `FileNotFoundError` there. This is the only runtime-semantics
  difference between the two, it is deliberate, and it is tested.

## Reporting

Report suspected vulnerabilities or unsafe behaviour privately to the
maintainers through the repository's private vulnerability reporting form.
Please include the affected file, the version, and a reproduction. Do not
open a public issue for an unfixed vulnerability.

## Scope note

The separate **VRET Research Reference** product lives at
<https://github.com/Gaijin-01/VRET-Research-Reference> and has its own
security policy. The two products are distinct and neither inherits the
other's advisories.
