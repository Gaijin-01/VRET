#!/usr/bin/env python3
"""Held-out suite for honest measurement.
Different parameters from Blind-50 v0.
No family name in episode ID.
"""
import json
import hashlib
import os
import shutil
from pathlib import Path
from loops.ratchet_rci_loop import AgentOptimizationCircuit, FrozenVerifier

def make_public_challenge(target):
    return hashlib.sha256(str(target).encode()).hexdigest()[:16]

def generate_heldout(seed):
    # Deterministic but different from training suite
    base = 2_000_000_000 + seed * 777
    family = ["timestamp", "counter", "modulo", "no_reduction"][seed % 4]
    if family == "timestamp":
        offset = 17 + (seed % 30)
        train = [
            {"ts": base, "nonce": base + offset},
            {"ts": base + 50, "nonce": base + 50 + offset},
        ]
        holdout = [{"ts": base + 100, "nonce": base + 100 + offset}]
        query = {"ts": base + 500_000}
        target = query["ts"] + offset
    elif family == "counter":
        start = 1000 + seed
        step = 3
        train = [
            {"ts": base, "nonce": start},
            {"ts": base + 1, "nonce": start + step},
        ]
        holdout = [{"ts": base + 2, "nonce": start + 2 * step}]
        query = {"ts": base + 50}
        target = start + 50 * step
    elif family == "modulo":
        mod = 256 if seed % 2 == 0 else 1000
        train = [
            {"ts": base, "nonce": base % mod},
            {"ts": base + 1, "nonce": (base + 1) % mod},
        ]
        holdout = [{"ts": base + 2, "nonce": (base + 2) % mod}]
        query = {"ts": base + 200}
        target = (base + 200) % mod
    else:
        train = [
            {"ts": base, "nonce": 999999},
            {"ts": base + 1, "nonce": 111111},
        ]
        holdout = [{"ts": base + 2, "nonce": 222222}]
        query = {"ts": base + 100}
        target = 333333
    return train, holdout, query, target, family

def run_heldout(n=20):
    results = []
    base_dir = Path("schemas")
    for i in range(n):
        ep_id = f"heldout_{i:03d}"
        train, holdout, query, target, true_family = generate_heldout(i)
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
            "true_family": true_family,
            "outcome": outcome,
            "kept": trial.get("kept", False),
            "family_discovered": trial.get("provenance", {}).get("derivation", "")[:20] if trial.get("kept") else None,
        })
        state_path.unlink(missing_ok=True)
        results_path.unlink(missing_ok=True)
    return results

if __name__ == "__main__":
    os.chdir("/workspace/artifacts/agent-tooling-blueprints")
    res = run_heldout(20)
    Path("heldout_results.json").write_text(json.dumps(res, indent=2))
    from collections import Counter
    by_fam = {}
    for r in res:
        by_fam.setdefault(r["true_family"], Counter())[r["outcome"]] += 1
    print(json.dumps({"total": len(res), "by_true_family": {k: dict(v) for k, v in by_fam.items()}}, indent=2))
