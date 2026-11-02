# Benchmark receipt — VRET CLI/CUDA 0.2.0

All numbers below were produced on the machine that produced this release, from
the checkpoint that ships in the wheel. They are **measurements of this
artifact**, reproduced fresh for the release; nothing here is carried over from
an earlier claim without re-measurement.

## Hardware and runtime

| Item | Value |
| --- | --- |
| GPU | Quadro RTX 6000, 24 GB |
| Architecture | Turing, compute capability 7.5 (`sm_75`) |
| Driver | 621.01 |
| CUDA | host NVRTC (version string not asserted by the receipt) |
| OS | Ubuntu 24.04 under WSL2 |
| Python | 3.12 |

Exact NVRTC library path is withheld from the receipt (it is a host path that
leaks the local account name); see
`vret_cli/checkpoint/receipts/fresh-2026-10-31/REDACTIONS.md`.

## What is measured

**Candidate screening throughput** — the rate at which the pipeline evaluates
candidate integers against the SHA-256 prefix predicate on the GPU.

This is **not** ECDSA circuit throughput. The checkpoint's cryptography is
SHA-256 prefix matching; "circuit" inside the checkpoint refers to the agent
optimization circuit (the frozen discovery/ratchet loop), not to a
cryptographic circuit.

The correctness oracle is the CPU evaluator. GPU results are compared against
it bitwise.

## Headline numbers (fresh, serialized run, 2026-10-31)

| Mode | Throughput |
| --- | --- |
| Pipelined (`PIPELINED_POLICY_V1`) | **14,378,740 candidates/s** |
| Non-pipelined GPU | 12,689,379 candidates/s |
| CPU comparator | 1,181,864 candidates/s |
| Pipeline vs non-pipelined | 1.133× |
| Pipeline vs CPU | 12.166× |

## Measurement boundary

**Included** in the timed region: serialization, packing, H2D transfer, kernel
launch, synchronization, D2H transfer, and Python-side digest formatting.
This is an **end-to-end** figure, not a kernel-only figure.

**Excluded and reported separately:**

* Cold engine initialization and kernel compilation: **0.410 s** (measured
  once, reported on its own).
* Telemetry sampling overhead is outside the timed region; telemetry scope is
  the whole device, shared with any other workload on the GPU.

## Repetition and corpus

* Corpus: **65,536 unique** frozen-discovery integers (corpus SHA-256
  `7800d6a147c565bdc908b0c2b8ad618c0f5530b7dd5b7f143e102ce2af12496c`).
* Source space 65,558 → corpus 65,536; reduction ratio 65,514×.
* Workload is a **replay** of a gate-approved frozen discovery space. It is
  **not** a stream of newly discovered unique spaces, and the receipt states
  this explicitly.
* Strict mode: 1 repeat. Bulk mode: 3 repeats.
* A/B: 7 paired, alternating repetitions per mode; the reported value is the
  median of the sustained samples. Best batch size is selected per mode across
  B65536 and B262144 on the same warmed engine and the same corpus.

## Resource telemetry (sustained phase)

| Metric | Value |
| --- | --- |
| GPU utilization | mean 13.2 %, max 14 % |
| Device VRAM | 579 MiB peak |
| Device power | 9.45 W peak |
| Device temperature | 40.4 °C peak |
| Telemetry errors | 0 |

## Correctness and immutability

| Check | Result |
| --- | --- |
| Physical equivalence, GPU vs CPU digest | **500/500**, 0 mismatches |
| Batched CUDA equivalence | 0 mismatches (385 PASS / 115 `discovery_falsified`) |
| Fresh device/CPU equivalence | 100 episodes, 0 mismatches, 1,679 CUDA launches |
| Frozen original results unchanged | 12/12 |
| Protected source hashes verified | 18/18 |
| Pipeline equivalence mismatches | 0 |

`discovery_falsified` is a legitimate outcome, not an error: a candidate that
the CPU oracle also falsifies is a *correct* falsification. Only `mismatches`
would indicate a defect.

## Limits of these claims

* One GPU, one driver, one corpus. These are not universal speedup figures and
  are not extrapolated to other hardware.
* `bulk_semantics_certified_for_circuit: false` — the bulk path is faster but
  is **not** certified as semantically equivalent to the strict path for the
  circuit, and the release does not claim otherwise.
* `strict_break_even: not observed in measured counts`.
* Bulk first measured GPU win at 100,000 candidates.
* Prefetch is bounded to one prepared batch, ≤ 262,144 candidates in the
  measured runs.
* The historical acceptance receipt at the checkpoint root and the fresh A/B
  receipt in `receipts/fresh-2026-10-31/` are kept separate and are not mixed.
  The historical best pipeline figure on the same hardware was
  13,959,719 candidates/s, so the fresh run is consistent with it rather than
  an unrelated number.

## Reproducing

The raw receipts are in the wheel:

* `vret_cli/checkpoint/receipts/fresh-2026-10-31/pipeline_ab.json`
* `vret_cli/checkpoint/receipts/fresh-2026-10-31/benchmark.json`
* `vret_cli/checkpoint/receipts/fresh-2026-10-31/batched_equivalence_cuda.json`
* `vret_cli/checkpoint/receipts/fresh-2026-10-31/equivalence.json`

`vret report` and `vret receipts --list` expose the checkpoint's own receipt
inventory. Re-running the benchmark on a different GPU will produce different
absolute numbers; the ratios and the zero-mismatch correctness results are the
parts that are expected to carry over.
