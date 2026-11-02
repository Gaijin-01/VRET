#!/usr/bin/env python3
"""CPU vs GPU executor equivalence gate.
Must be 0 mismatches on hit, target_found, oracle verdict.
"""
import json
import hashlib
import os
import shutil
from pathlib import Path
from loops.ratchet_rci_loop import AgentOptimizationCircuit, FrozenVerifier

def make_public(target):
    return hashlib.sha256(str(target).encode()).hexdigest()[:16]

def run_equiv(n=20):
    mismatches = []
    base_dir = Path("schemas")
    for i in range(n):
        ep = f"equiv_{i:03d}"
        # Mix of families
        base = 4_000_000_000 + i * 100
        if i % 3 == 0:
            train = [{"ts": base, "nonce": base + 42}, {"ts": base + 1, "nonce": base + 43}]
            holdout = [{"ts": base + 2, "nonce": base + 44}]
            query = {"ts": base + 1000}
            target = query["ts"] + 42
        elif i % 3 == 1:
            train = [{"ts": base, "nonce": 10}, {"ts": base + 10, "nonce": 13}]
            holdout = [{"ts": base + 30, "nonce": 16}]
            query = {"ts": base + 500, "index": 100}
            target = 10 + 3 * 100
        else:
            train = [{"ts": base, "nonce": 1000}, {"ts": base + 5, "nonce": 1010}]
            holdout = [{"ts": base + 15, "nonce": 1030}]
            query = {"ts": base + 200}
            target = 1000 + 2 * 200
        state_path = base_dir / f"state_{ep}.json"
        shutil.copy("schemas/circuit_state.json", state_path)
        c = AgentOptimizationCircuit(state_path=str(state_path), results_path="/dev/null")
        public = make_public(target)
        v = FrozenVerifier(public)
        # Discover + compile once
        hyp = c.discover_from_observations(train, holdout)
        if hyp is None:
            state_path.unlink(missing_ok=True)
            continue
        status, space = c.compile_reduced_space(hyp, train, query)
        if status != "OK":
            state_path.unlink(missing_ok=True)
            continue
        # CPU
        cpu = c.candidate_evaluator(space, v)
        # GPU
        gpu = c.gpu_evaluator(space, v)
        # Oracle
        cpu_ok = cpu.get("hit") == target and cpu.get("target_found")
        gpu_ok = gpu.get("hit") == target and gpu.get("target_found")
        if cpu.get("hit") != gpu.get("hit") or cpu.get("target_found") != gpu.get("target_found") or cpu_ok != gpu_ok:
            mismatches.append({
                "ep": ep,
                "cpu_hit": cpu.get("hit"),
                "gpu_hit": gpu.get("hit"),
                "cpu_found": cpu.get("target_found"),
                "gpu_found": gpu.get("target_found"),
            })
        state_path.unlink(missing_ok=True)
    return mismatches

if __name__ == "__main__":
    os.chdir("/workspace/artifacts/agent-tooling-blueprints")
    mm = run_equiv(30)
    print(json.dumps({"mismatches": len(mm), "details": mm}, indent=2))
