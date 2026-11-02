# Invariants — discovery-execution plane circuit

## Central principle
No brute force before justified search-space reduction.
Executor never sees hidden_target.
Verifier is harness-owned, type-checked, and sealed by actual source hash.
Resource parameters bound from sealed manifest.

## Status
architecture: PASS
Pareto ratchet: PASS
coverage hard gate: PASS
frozen persistence: PASS
pre-sealed baseline: PASS
shipped frozen state: CLEAN (n_iters=0, sealed)
execution verifier isolation: PASS
verifier authenticity: PASS (type is FrozenVerifier + inspect source hash)
sealed config binding: PASS
no-reduction gate: PASS
resource-budget gate: PASS
candidate lazy generation: PASS
analytical coverage: PASS
execution-success gate: PASS
wall-clock semantics: PASS (monotonic)
abstain reasons: SEPARATE
query-context separation: PASS
relation discovery: MINIMAL
GPU execution: NOT IMPLEMENTED

## Hard invariants
INV-01: evaluator does not invent constraints.
INV-02: Provenance.derived_from == [train_0..train_n]; delta == int(max_diff*1.1)+1 exactly.
INV-03: speed alone cannot promote.
INV-04: coverage != 1 → never keep.
INV-05: reduction_ratio < sealed MIN_REDUCTION_RATIO or estimated_size > sealed MAX_CANDIDATES → ABSTAIN.
INV-06: target_found only from frozen verifier match; type(verifier) is FrozenVerifier.
INV-07: packaged baseline must contain data_hash and verifier_code_hash from inspect.getsource; runner never reseals.
