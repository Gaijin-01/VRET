# PIPELINED_POLICY_V1

This policy is distinct from BATCHED_POLICY_V1. Discovery, candidate construction, FrozenVerifier, oracle and CUDA kernels are unchanged.

- Exactly one CUDA worker, default CUDA stream only. At most one dispatched batch in flight; no worker device operation overlaps another batch's device operation.
- Main thread generates/packs at most one next batch into a capacity-one prepared queue. It cannot advance another batch until the current result is resolved.
- A dispatch handshake is required before next-batch prefetch, so a first batch rejected by deadline does not advance two undispatched batches. For CUDA, the producer is released only after cuLaunchKernel returns; H2D and launch therefore cannot be starved by producer-side Python packing. Non-CUDA/scalar fallback releases at dispatch acceptance.
- CUDA worker explicitly binds and reads back the shared CUDA primary context. Context inheritance is never assumed.
- Deadline is checked in the worker immediately before accepting dispatch. Equality is allowed. If expired, no device launch; prepared batch has no evaluator effect.
- An accepted batch can finish after the wall deadline and return its first valid hit.
- Results resolve in original candidate order. Current batch's lowest match wins; the prefetched batch is discarded on a current hit.
- Prefetch generation errors and pack fallback are deferred; a discarded batch cannot supply a hit, metric, count or exception to the evaluator.
- Logical eval_count for completed runs matches the CPU first-hit policy. Physical SHA evaluations need not match. Deadline counts are not asserted equal across differently paced executors.
- pipeline=False delegates directly to the untouched verified BatchedCircuit. pipeline=True selects this policy.
- Caller owns engine lifetime. Call shutdown_pipeline(engine) before engine.close(). Sequential reuse of the same warmed engine is supported; concurrent external callers using the same engine are unsupported.
