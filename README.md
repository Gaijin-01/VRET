# VRET — Verified Reduction & Execution Toolkit (CLI + CUDA checkpoint)

`vret` is a stdlib-only command line front end for an immutable, receipt-verified
CUDA/GPU checkpoint. This repository publishes the **working CLI/CUDA line**:
the launcher, the CLI implementation, the verified GPU checkpoint tree, and the
measurement receipts that back the numbers below.

* Version: **0.2.0**
* Policy: **PIPELINED_POLICY_V1**
* Console script: `vret` (alias `vret-cli`)
* Python: **>= 3.10**, standard library only — no third-party runtime dependencies

## 1. What is VRET?

VRET reduces a large candidate space to a small *reduced space* that a GPU
kernel can evaluate, then verifies that the GPU result is identical to the
authoritative CPU result. The tool ships two things:

1. a **checkpoint** — an immutable tree containing CUDA kernels (`.cu`), the
   Python execution paths (`cuda_execution.py`, `batch_execution.py`,
   `pipeline_execution.py`), the CPU oracle (`cpu_shim/`), the frozen policy
   and equivalence suites, and the JSON receipts produced by previous runs;
2. a **CLI** — `vret`, a standard-library-only program that locates the
   checkpoint, re-verifies it against its own receipts, reports metadata, and
   runs the checkpoint's validation scripts.

## 2. What is the CLI?

`vret` does not reimplement the checkpoint. It is a thin, auditable front end:

| Command | Purpose |
| --- | --- |
| `vret --version` | version and policy banner (`VRET 0.2.0 policy=PIPELINED_POLICY_V1`) |
| `vret root` | print the resolved checkpoint root |
| `vret status` | re-verify the checkpoint and print `VRET checkpoint: VERIFIED` plus key receipt figures |
| `vret doctor` | environment and import checks (CUDA driver, NVRTC, toolkit imports) |
| `vret info` | policy, checkpoint and receipt metadata |
| `vret report` | policy report; `--cat` prints it verbatim |
| `vret receipts` | receipt inventory; `--list` lists receipt names |
| `vret run <script.py> [args…]` | run a checkpoint script (no shell; see §11) |

The checkpoint root is resolved as: `VRET_ROOT` environment variable if set,
otherwise the `checkpoint/` directory shipped inside the installed package.

## 3. GPU / CUDA execution

CUDA is part of this lineage, not an optional extra. The checkpoint contains
NVRTC-compiled kernels (`sha256_device.cu`, `sha256_batch.cu`) and three
execution paths:

* **strict** — one candidate set per device round-trip; used when the budget is
  small or the caller needs per-episode behaviour;
* **bulk** — a batched primitive that amortizes host↔device transfer;
* **pipeline** — the opt-in prefetch pipeline governed by `PIPELINED_POLICY_V1`,
  where one prepared batch is in flight while the current one is evaluated.

`vret doctor` reports the detected device and whether the CUDA runtime and
NVRTC are usable. The backend discovers NVRTC through the normal CUDA
locations and honours the `NVRTC_LIBRARY` environment variable as an explicit
override.

## 4. What is `PIPELINED_POLICY_V1`?

The policy is the authoritative description of when the pipelined executor may
be used, how much prefetch advance is allowed, and what must be re-verified
before a pipeline result is accepted. It is shipped as
`checkpoint/PIPELINED_POLICY_V1.md` and is one of the hash-pinned files: if it
changes, `vret status` stops reporting `VERIFIED`. The short form: pipeline
mode is **opt-in**, permits at most one prepared batch in flight, and only for
large batches; the non-pipelined path stays the default reference behaviour.

## 5. What does `VERIFIED` mean?

`vret status` prints `VRET checkpoint: VERIFIED` only when the checkpoint's
receipts are internally consistent and the protected files still hash to the
values recorded in the receipts. It is a **local integrity and receipt
consistency statement**, not a signature, not an attestation, and not a
guarantee about any workload you run. If a protected file has been edited, the
status degrades to `DEGRADED` or `FAILED` with the offending file named.

## 6. What is `candidates/s`?

`candidates/s` is the measured **screening rate**: how many candidate items per
second the GPU path processed in a measured run. It is a throughput number for
one workload on one machine — not a score, not a success rate, and not a claim
about any cryptographic operation. The exact measurement boundary is in §8.

## 7. What is the authoritative correctness criterion?

The authoritative oracle is the **CPU evaluator**, not the GPU. The checkpoint's
equivalence suites replay frozen fixtures on both paths and compare:

* the candidate set,
* the evaluated sequence,
* the evaluator result,
* and the oracle verdict.

A mismatch on any of those invalidates the run. The fresh validation recorded
in this release ran **500 episodes with 0 mismatches** (385 `PASS`, 115
`discovery_falsified` — the latter is a legitimate negative outcome, not an
error), and the frozen original result files were confirmed unchanged
(12/12). A second, smaller receipt of **100 episodes / 0 mismatches / 1679 CUDA
launches** reproduces the historical `receipts/equivalence.json` byte-for-byte:
both files hash to SHA-256 `b7132d1203db61d5…`. That historical receipt is not
part of the checkpoint import that backs this tree, so the regenerated copy
ships under `checkpoint/receipts/fresh-2026-10-31/equivalence.json`.

## 8. Benchmark and measurement boundary

Measured on the machine that produced the receipts in this repository:

* GPU: **Quadro RTX 6000 24GB**, Turing, **compute capability 7.5**
* Driver: **621.01**
* Corpus: **65,536** unique candidates; estimated source size 65,558 →
  source reduction **65,514×**
* Cold init + compile: **0.410 s** (measured separately, *not* in the rate)
* Strict repeats: 1, bulk repeats: 3; A/B repetitions: 7, alternating paired runs

The headline rate is measured at **n = 1,000,000 candidate evaluations** — a
*replay* of the frozen 65,536-unique-candidate corpus (larger n replays the
same corpus, it does not discover new candidates). The rate is the best of the
two batch sizes (65,536 and 262,144), each the median of 7 alternating paired
runs on a warmed engine.

Fresh measurement (this release, `checkpoint/receipts/fresh-2026-10-31/`):

| Mode | Throughput |
| --- | --- |
| Pipeline | **14,378,740 candidates/s** |
| Non-pipelined | 12,689,379 candidates/s |
| CPU comparator | 1,181,864 candidates/s |

Pipeline is **1.133×** the best non-pipelined mode and **12.166×** the CPU
comparator in the same run. The historical receipt bundled with the checkpoint
records **13,959,719 candidates/s** (1.092× / 11.622×) under the same policy.
The fresh figure is *higher* than the historical one; both are reported rather
than the better one alone.

**Measurement boundary.** The timed region includes candidate serialization,
packing, host→device transfer, kernel launch, synchronization, device→host
transfer and Python-side digest formatting. Cold start and NVRTC compilation
are outside it and reported separately. This is an **end-to-end** rate, not a
kernel-only rate; the two are not mixed anywhere in this repository.

Explicit non-claims: this is **not** ECDSA circuit throughput, **not** a
universal speedup, and **not** a claim about bulk semantics for a circuit —
`bulk_semantics_certified_for_circuit` is `false` in the receipts.

## 9. Install and run

```bash
pip install vret_cli-0.2.0-py3-none-any.whl     # wheel ships the checkpoint
vret --version
vret status
vret doctor
```

From a source checkout:

```bash
python3 -m pip install .
vret --version
```

Point the CLI at any other checkpoint with `VRET_ROOT`:

```bash
VRET_ROOT=/path/to/checkpoint vret status
```

Run the checkpoint's own suites:

```bash
vret run blind50_v0.py
vret run heldout_v1.py
vret run unseen_holdout.py
vret run cpu_gpu_equiv.py
```

These are the suites that ship in this tree. The upstream research lane
(bulk/physical benchmark drivers and their superseded receipts) is not
redistributed here; see `docs/provenance.md`.

## 10. Security and trust boundaries

* **No network access, no credentials, no telemetry.** The CLI and the
  checkpoint are standard-library-only and offline.
* **`vret run` is not a sandbox.** The script path must be relative and must
  stay inside the checkpoint (absolute paths, `..` traversal and symlink
  escapes are rejected), and no shell is ever spawned — arguments are passed
  literally. But an allowed script runs with your permissions and may modify
  files. Run only scripts you trust.
* **The checkpoint is treated as immutable.** `vret run` executes the selected
  script in place, with the checkpoint root as its working directory, and never
  copies or rewrites checkpoint files. See §11 for the exact runtime contract.
* **`VERIFIED` is local.** It compares files against bundled receipts; it is
  not a signature and not an attestation.
* **No hardened service, no stable SDK.** This is a research-grade tool with a
  published receipt trail.

## 11. Runtime contract of `vret run`

`vret run <script.py> [args…]` executes a script that lives inside the
checkpoint. The contract is:

* the script path must be **relative** and must resolve **inside** the
  checkpoint root; absolute paths, `..` traversal and symlink escapes are
  rejected;
* the script must be an existing `.py` file;
* **no shell is spawned.** Arguments are passed literally to the interpreter;
* the script runs **in place**, with the checkpoint root as its working
  directory (`cwd=root`) — the checkpoint is never copied and never rewritten;
* `sys.argv[0]` is the script path and `sys.argv[1:]` are the literal
  arguments; `__name__` is `__main__` and `__file__` is the script path.

**One deliberate difference from the development copy.** This package launches
the script through a small interpreter shim that makes `os.chdir` tolerate a
directory that does not exist. Four hash-pinned checkpoint modules `chdir` into
the upstream workspace path `/workspace/artifacts/agent-tooling-blueprints`,
which is absent from an installed package; the development copy of the CLI has
no such shim and propagates `FileNotFoundError` there. Everything else about
the launch is identical, and `tests/test_runtime_semantics.py` pins both sides
of the difference. No checkpoint file was modified to achieve this.

## What this release actually is

This is the VRET **CLI/CUDA line** at version 0.2.0: a standard-library CLI plus
the immutable GPU checkpoint it drives, with the receipts that were measured on
a Quadro RTX 6000 (sm_75). It is published with the checkpoint included, so the
numbers in this README are reproducible from the installed artifact alone.
It is **not** the VRET Research Reference: that is a separate, domain-neutral
product with its own repository, its own version line and its own synthetic
benchmarks, and none of its measurements are used as evidence here. The two
products share a name and a mission, not an artifact lineage.
This release contains no ECDSA circuit work and makes no claim about one.
It is a research-grade release: correctness is demonstrated on frozen fixtures,
not a proof for arbitrary inputs.

## Repository and provenance

* Canonical repository: <https://github.com/Gaijin-01/VRET>
* The separate Research Reference product lives at
  <https://github.com/Gaijin-01/VRET-Research-Reference> and is not the
  successor of this version line.
* `docs/release_acceptance.md` — full acceptance report.
* `docs/benchmark_receipt.md` — measurement receipt and boundary.
* `docs/source_manifest.json` — file-by-file manifest with SHA-256 digests.
* `docs/provenance.md` — where every published file came from.
* `SECURITY.md` — trust boundaries and reporting guidance.
* `LICENSE` — MIT.
