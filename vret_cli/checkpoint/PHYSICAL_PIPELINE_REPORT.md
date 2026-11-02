# Physical single-worker pipeline validation — accepted

## Decision

PIPELINED_POLICY_V1 correctness PASS, zero physical equivalence mismatches. Accept the opt-in pipeline for the measured large replay workload: +9.205% throughput versus contemporary best non-pipeline, +10.408% versus the prior accepted 79.090403ms checkpoint. No projected speedup is used.

The prespecified conservative materiality rule required at least 5% throughput improvement against BOTH best contemporaneous non-pipeline batch and historical checkpoint. The pipeline meets both; old non-pipeline executor remains unchanged and available. Small workloads can regress; no universal routing claim.

```json
{
  "PIPELINED_POLICY_V1": "PASS",
  "PIPELINE_EQUIVALENCE": 0,
  "BEST_NONPIPE_CAND_S": 12782993.914700652,
  "BEST_PIPE_CAND_S": 13959719.146732882,
  "PIPE_SPEEDUP_VS_BEST_NONPIPE": 1.092053961684123,
  "PIPE_SPEEDUP_VS_CPU": 11.621629427596186,
  "PREFETCH_MAX_ADVANCE": "1 prepared batch, <=262144 candidates in measured runs",
  "HISTORICAL_SPEEDUP": 1.1040798130820488,
  "NONPIPE_B65536_MS": 85.18917299807072,
  "PIPE_B65536_MS": 79.34344400564441,
  "NONPIPE_B262144_MS": 78.2289349954226,
  "PIPE_B262144_MS": 71.63467899954412,
  "ACCEPT_PIPELINE": true,
  "GPU_UTIL": {
    "mean": 11.88888888888889,
    "max": 15.0
  },
  "POWER_PEAK": 22.49,
  "TEMP_PEAK": 39.4,
  "VRAM_PEAK": 7485.0,
  "telemetry_scope": "all pipeline-tagged A/B, profiling and sustained phases; whole-device sensors",
  "verified_tree": "<UPSTREAM_IMPORT>/agent-tooling-blueprints",
  "reference_files_unchanged": 37,
  "frozen_originals_unchanged": 12,
  "decision": "ACCEPT opt-in pipeline=True for large batches; reference pipeline=False retained unchanged",
  "streams_implemented": false,
  "device_candidate_generation_implemented": false
}
```

## Architecture / scope

- New pipeline_execution.PipelineCircuit(..., pipeline=False|True); False directly delegates to unchanged BatchedCircuit.
- One persistent CUDA worker per engine; capacity-one prepared queue on producer; no second dispatch until current Future resolves. No multiple CUDA streams.
- Worker explicitly sets CUDA primary context and reads it back. First physical worker cuCtxGetCurrent was NULL, then matched the engine context. All 500-suite worker operations used one worker thread and passed context verification.
- Deadline checked in worker before dispatch; accepted in-flight hit may finish after deadline. Prepared next batch is discarded on current hit. Generator errors in a discarded prefetch cannot leak into the evaluator.
- Call shutdown_pipeline(engine) before engine.close(). Same engine supports sequential warmed A/B; concurrent external callers are unsupported.
- Discovery, verifier, relation logic, SHA kernels and all 37 copied prior-checkpoint files remained byte-for-byte unchanged, including 12 frozen originals.

## Correctness receipts

- Existing complete suite was run first: 34/34 PASS (32 + 2 strict CUDA).
- Final original+pipeline suite: 44/44 PASS (32 + 2 strict CUDA + 10 policy tests).
- Physical policy suite: 9/9 PASS, including boundary hit 0, B-1, B, B+1, final batch, adjacent duplicates, no hit; virtual-clock deadlines on physical CUDA; int64 edges, mixed/huge/bool/multi-block fallback.
- Final default unittest discovery: 55 discovered, 53 PASS, 2 explicitly skipped physical duplicates of virtual-driver tests; those two tests passed in the virtual suite. No unavailable-CUDA skips.
- Frozen Blind-50: 250 comparisons; heldout: 100; unseen: 150; total 500, 0 mismatches. Same first observable hit, target_found, full evaluator result, oracle and required logical eval_count. Existing batch-prefix audit also PASS.
- Deadline before first, before next, while current is in flight, in-flight hit after wall deadline, no prefetched result leak, max-one-batch advancement and discarded-prefetch exception PASS.

## Paired warmed A/B

One shared preallocated warmed CUDA engine and identical discovery-approved 65536-element corpus; larger sizes replay it. 7 alternating paired runs per size/batch, medians. Full evaluator wall time includes generation, packing, handoff/queue, H2D, launch, sync/readback and result resolution. CPU timed alongside the same corpus.

| N | Batch | CPU ms | Nonpipeline ms | Pipeline ms | Pipeline wins / 7 |
|---:|---:|---:|---:|---:|---:|
| 10000 | 65536 | 8.491811 | 2.241116 | 2.501148 | 0 |
| 10000 | 262144 | 8.482008 | 2.021524 | 2.437866 | 0 |
| 100000 | 65536 | 84.014893 | 9.013049 | 9.479117 | 3 |
| 100000 | 262144 | 83.539058 | 7.791624 | 8.402200 | 0 |
| 1000000 | 65536 | 830.062777 | 85.189173 | 79.343444 | 6 |
| 1000000 | 262144 | 842.189614 | 78.228935 | 71.634679 | 7 |

Historical B262144 median independently read back from prior physical receipt: 79.090403ms, 12643759 cand/s.

## Sustained corroboration

- nonpipe: 100 matched 1M evaluations at B262144; median 77.978192ms during 8-second sustained block.
- pipe: 108 matched 1M evaluations at B262144; median 71.299643ms during 8-second sustained block.

## Profile: 1M (milliseconds)

Independent 5-run instrumented experiment; each column is the coherent phase vector from its median-total run. Profiling adds a synchronization point. Phases overlap and MUST NOT be summed as a wall-time decomposition. Queue wait means submitted-to-worker-start scheduling; worker idle means gaps between completed worker job and next start; producer idle includes dispatch handshake and unresolved-current-result waits.

| Phase | B65536 pipeline | B262144 pipeline |
|---|---:|---:|
| generation | 29.057624 | 28.731599 |
| pack | 34.328725 | 36.067387 |
| queue_wait | 1.110135 | 0.363116 |
| h2d | 0.878565 | 0.742916 |
| launch | 0.846866 | 0.300703 |
| kernel_sync | 63.026162 | 35.091205 |
| d2h | 7.848231 | 15.528867 |
| worker_idle | 1.872967 | 0.419699 |
| producer_idle | 15.541881 | 4.883424 |
| total | 79.870498 | 70.313565 |

## Direct overlap evidence, not an inference from total

- B65536: producer generation/pack of k+1 intersects worker blocking CUDA calls for k for 58.963725ms, 31 measured interval intersections in the median-profile run.
- B262144: producer generation/pack of k+1 intersects worker blocking CUDA calls for k for 47.348108ms, 10 measured interval intersections in the median-profile run.

Raw same-clock timestamps and worker/main thread identities are in receipts/pipeline_ab.json -> profiles -> runs -> timeline/overlap. These prove host production overlaps worker device-wait intervals. They do NOT imply that GPU compute was busy for all that time: CUDA API intervals include scheduling/GIL reacquisition. kernel_sync is host wait, not pure kernel time.

## First measurement and root cause

Initial correct pipeline released producer before H2D/launch. It measured 79.585ms versus 77.258ms best non-pipeline and zero host/device-wait overlap: producer Python packing could hold the GIL while the worker was still trying to launch the kernel. The receipts of that superseded first measurement are not redistributed in this tree; the accepted receipts below are the current evidence.

A deterministic regression test reproduced prefetch before the simulated kernel launch (unexpected candidate advances [4,5,6,7]); the fix releases CUDA producer handoff only after cuLaunchKernel returns. No kernel/discovery/reference edits were made. Correctness suites and all A/B measurements were rerun after this execution-only fix.

## Telemetry

All pipeline-tagged A/B/profile/sustained phases, whole-device sensors:
```json
{
  "gpu_util_pct": {
    "mean": 11.88888888888889,
    "max": 15.0
  },
  "device_power_w": {
    "mean": 9.637222222222222,
    "max": 22.49
  },
  "device_temp_c": {
    "mean": 38.86111111111111,
    "max": 39.4
  },
  "device_vram_mib": {
    "mean": 7485.0,
    "max": 7485.0
  }
}
```
Samples: 18; telemetry errors: 0.

Sustained pipeline only:
```json
{
  "samples": 14,
  "gpu_util_pct": {
    "mean": 13.285714285714286,
    "max": 15.0
  },
  "device_vram_mib": {
    "mean": 7485.0,
    "max": 7485.0
  },
  "device_power_w": {
    "mean": 8.786428571428571,
    "max": 9.44
  },
  "device_temp_c": {
    "mean": 38.792857142857144,
    "max": 38.9
  }
}
```

Whole-run peak including init/CPU/nonpipeline phases: 57.04W, 40.4C. Whole-device VRAM includes unrelated allocations; no workloads were stopped or unloaded. Coarse power/util samples are not isolated kernel energy measurements.

## Files / reproduce / rollback

Shipped in this tree:

- pipeline_execution.py: production opt-in adapter.
- PIPELINED_POLICY_V1.md: frozen policy.
- batch_execution.py, cuda_execution.py: strict and bulk execution paths.
- cpu_shim/driver.cpp, cpu_shim/shim.h: the CPU oracle the GPU path is compared against.
- blind50_v0.py, heldout_v1.py, unseen_holdout.py, cpu_gpu_equiv.py: the equivalence suites.
- receipts/pipeline_equivalence_cuda.json: 500 results and worker-context evidence.
- receipts/pipeline_ab.json: individual times, profiles, traces and raw telemetry.
- receipts/acceptance.json: final acceptance and explicit telemetry scope.
- receipts/fresh-2026-10-31/: dated fresh measurement and equivalence evidence.

The measurement campaigns that produced the accepted receipts were run in the
upstream workspace. Those driver scripts and their superseded receipts are not
redistributed here, so they cannot be re-run from an installed package; the
accepted receipts and the frozen policy above are the evidence of record.

```sh
vret run blind50_v0.py
vret run heldout_v1.py
vret run unseen_holdout.py
```

Usage:
```python
from batch_execution import CudaBatchSearch
from pipeline_execution import PipelineCircuit, shutdown_pipeline
engine = CudaBatchSearch()
try:
    circuit = PipelineCircuit(engine=engine, batch_size=262144, pipeline=True)
    # circuit.candidate_evaluator(discovery_approved_space, exact_frozen_verifier)
finally:
    shutdown_pipeline(engine)
    engine.close()
```

Rollback selection: set pipeline=False. No accepted prior source was modified. Exact command to return to the untouched prior checkpoint:
```sh
cd <UPSTREAM_IMPORT>/agent-tooling-blueprints
```

Neither two streams nor device-side candidate generation was implemented. Further optimization choice remains untested; no claim that either lever will help.
