#!/usr/bin/env python3
"""Blind-50 v0 diagnostic suite.
Timestamp family expected PASS.
All other families expected ABSTAIN or FAIL.
Public challenge = H(target). Per-episode fresh state.
"""
import json
import hashlib
import os
import tempfile
import shutil
from pathlib import Path
from loops.ratchet_rci_loop import AgentOptimizationCircuit, FrozenVerifier

FAMILIES = [
    ("timestamp", 8),
    ("counter", 8),
    ("truncation", 8),
    ("modulo", 6),
    ("prefix", 6),
    ("affine", 6),
    ("no_reduction", 8),
]

def make_public_challenge(target):
    return hashlib.sha256(str(target).encode()).hexdigest()[:16]

def generate_episode(family, idx):
    base = 1_700_000_000 + idx * 1000
    if family == "timestamp":
        # nonce ≈ ts + 42
        train = [
            {"ts": base, "nonce": base + 42},
            {"ts": base + 100, "nonce": base + 142},
        ]
        holdout = [{"ts": base + 200, "nonce": base + 242}]
        query = {"ts": base + 1_000_000}
        target = query["ts"] + 42
    elif family == "counter":
        train = [
            {"ts": base, "nonce": 10},
            {"ts": base + 1, "nonce": 11},
        ]
        holdout = [{"ts": base + 2, "nonce": 12}]
        query = {"ts": base + 100}
        target = 110
    elif family == "truncation":
        train = [
            {"ts": base, "nonce": base & 0xFFFF},
            {"ts": base + 1, "nonce": (base + 1) & 0xFFFF},
        ]
        holdout = [{"ts": base + 2, "nonce": (base + 2) & 0xFFFF}]
        query = {"ts": base + 100}
        target = (base + 100) & 0xFFFF
    elif family == "modulo":
        train = [
            {"ts": base, "nonce": base % 1000},
            {"ts": base + 1, "nonce": (base + 1) % 1000},
        ]
        holdout = [{"ts": base + 2, "nonce": (base + 2) % 1000}]
        query = {"ts": base + 100}
        target = (base + 100) % 1000
    elif family == "prefix":
        train = [
            {"ts": base, "nonce": int(str(base)[:6])},
            {"ts": base + 1, "nonce": int(str(base + 1)[:6])},
        ]
        holdout = [{"ts": base + 2, "nonce": int(str(base + 2)[:6])}]
        query = {"ts": base + 100}
        target = int(str(base + 100)[:6])
    elif family == "affine":
        train = [
            {"ts": base, "nonce": 2 * base + 7},
            {"ts": base + 1, "nonce": 2 * (base + 1) + 7},
        ]
        holdout = [{"ts": base + 2, "nonce": 2 * (base + 2) + 7}]
        query = {"ts": base + 100}
        target = 2 * (base + 100) + 7
    else:  # no_reduction
        train = [
            {"ts": base, "nonce": 123456789},
            {"ts": base + 1, "nonce": 987654321},
        ]
        holdout = [{"ts": base + 2, "nonce": 555555555}]
        query = {"ts": base + 100}
        target = 111111111
    return train, holdout, query, target

def run_suite():
    results = []
    base_dir = Path("schemas")
    for family, count in FAMILIES:
        for i in range(count):
            ep_id = f"{family}_{i:02d}"
            train, holdout, query, target = generate_episode(family, i)
            # Fresh state per episode
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
                "family": family,
                "outcome": outcome,
                "kept": trial.get("kept", False),
                "coverage": trial.get("coverage"),
                "eval_count": trial.get("eval_count"),
                "reduction_ratio": trial.get("reduction_ratio"),
            })
            # Cleanup episode state
            state_path.unlink(missing_ok=True)
            results_path.unlink(missing_ok=True)
    return results

if __name__ == "__main__":
    os.chdir("/workspace/artifacts/agent-tooling-blueprints")
    res = run_suite()
    Path("blind50_results.json").write_text(json.dumps(res, indent=2))
    # Summary
    from collections import Counter
    by_family = {}
    for r in res:
        by_family.setdefault(r["family"], Counter())[r["outcome"]] += 1
    print(json.dumps({"total": len(res), "by_family": {k: dict(v) for k, v in by_family.items()}}, indent=2))
