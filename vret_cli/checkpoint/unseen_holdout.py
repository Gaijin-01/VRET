#!/usr/bin/env python3
"""New unseen holdout: index_counter vs affine_ts isolation.
index_counter: irregular timestamps + explicit query index
affine_ts: irregular Δts, no index
"""
import json
import hashlib
import os
import shutil
from pathlib import Path
from loops.ratchet_rci_loop import AgentOptimizationCircuit, FrozenVerifier

def make_public_challenge(target):
    return hashlib.sha256(str(target).encode()).hexdigest()[:16]

def generate(seed):
    base = 3_000_000_000 + seed * 1234
    kind = ["index_counter", "affine_ts", "no_reduction"][seed % 3]
    if kind == "index_counter":
        # Irregular ts, linear in index
        train = [
            {"ts": base, "nonce": 100 + seed},
            {"ts": base + 17, "nonce": 100 + seed + 3},
        ]
        holdout = [{"ts": base + 41, "nonce": 100 + seed + 6}]
        query = {"ts": base + 999, "index": 500 + seed}
        target = 100 + seed + 3 * (500 + seed)
    elif kind == "affine_ts":
        # Irregular Δts, linear in ts
        slope = 2 + (seed % 5)
        train = [
            {"ts": base, "nonce": 1000 + slope * base},
            {"ts": base + 13, "nonce": 1000 + slope * (base + 13)},
        ]
        holdout = [{"ts": base + 29, "nonce": 1000 + slope * (base + 29)}]
        query = {"ts": base + 500}
        target = 1000 + slope * (base + 500)
    else:
        train = [
            {"ts": base, "nonce": 999999 + seed},
            {"ts": base + 7, "nonce": 111111 + seed},
        ]
        holdout = [{"ts": base + 19, "nonce": 222222 + seed}]
        query = {"ts": base + 100}
        target = 333333 + seed
    return train, holdout, query, target, kind

def run(n=30):
    results = []
    base_dir = Path("schemas")
    for i in range(n):
        ep_id = f"unseen_{i:03d}"
        train, holdout, query, target, true_kind = generate(i)
        state_path = base_dir / f"state_{ep_id}.json"
        results_path = base_dir / f"results_{ep_id}.jsonl"
        shutil.copy("schemas/circuit_state.json", state_path)
        c = AgentOptimizationCircuit(state_path=str(state_path), results_path=str(results_path))
        public = make_public_challenge(target)
        verifier = FrozenVerifier(public)
        trial = c.rci_cycle(train, holdout, query, target, verifier)
        outcome = "PASS" if trial.get("kept") else trial.get("reason", "FAIL")
        results.append({
            "episode": ep_id,
            "true_kind": true_kind,
            "outcome": outcome,
            "kept": trial.get("kept", False),
        })
        state_path.unlink(missing_ok=True)
        results_path.unlink(missing_ok=True)
    return results

if __name__ == "__main__":
    os.chdir("/workspace/artifacts/agent-tooling-blueprints")
    res = run(30)
    Path("unseen_holdout.json").write_text(json.dumps(res, indent=2))
    from collections import Counter
    by = {}
    for r in res:
        by.setdefault(r["true_kind"], Counter())[r["outcome"]] += 1
    print(json.dumps({"total": len(res), "by_kind": {k: dict(v) for k, v in by.items()}}, indent=2))
