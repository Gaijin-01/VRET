import json
import os
import hashlib
import time
import inspect
from datetime import datetime
from dataclasses import dataclass, asdict
from typing import Callable, List, Any, Dict, Optional

@dataclass
class Provenance:
    constraint: str
    derived_from: List[str]
    derivation: str
    confidence: float

    def valid(self) -> bool:
        return (
            bool(self.derived_from)
            and self.confidence > 0.5
            and len(self.constraint) > 0
        )

@dataclass
class ReducedSpace:
    generator: Callable[[], List[Any]]
    estimated_size: int
    provenance: Provenance
    original_space: int = 2**32

    def candidates(self):
        yield from self.generator()

    def to_dict(self) -> Dict:
        d = {
            "estimated_size": self.estimated_size,
            "original_space": self.original_space,
            "provenance": asdict(self.provenance),
            "generator": getattr(self.generator, "__name__", "callable")
        }
        return d

    def contains(self, value: Any) -> bool:
        # Stream check for non-timestamp; analytical for timestamp
        if hasattr(self, "_family") and self._family != "timestamp":
            for c in self.candidates():
                if c == value:
                    return True
            return False
        if hasattr(self, "_lower") and hasattr(self, "_upper"):
            return self._lower <= value <= self._upper
        return False

class FrozenVerifier:
    """Harness-owned verifier. Public challenge = H(hidden).
    Does not contain hidden target. Match via hash compare."""
    def __init__(self, public_challenge: str):
        self.public_challenge = public_challenge  # H(target)

    def __call__(self, candidate: Any) -> float:
        h = hashlib.sha256(str(candidate).encode()).hexdigest()[:16]
        return 1.0 if h == self.public_challenge else 0.0

    @staticmethod
    def code_hash() -> str:
        src = inspect.getsource(FrozenVerifier)
        return hashlib.sha256(src.encode()).hexdigest()[:16]

class AgentOptimizationCircuit:
    def __init__(self, state_path="schemas/circuit_state.json", results_path="results.jsonl"):
        self.state_path = state_path
        self.results_path = results_path
        self.load_state()

    def _compute_frozen_hash(self):
        fe = {k: v for k, v in self.state["frozen_eval"].items() if k != "data_hash"}
        payload = json.dumps(fe, sort_keys=True).encode()
        self.state["frozen_eval"]["data_hash"] = hashlib.sha256(payload).hexdigest()[:16]

    def load_state(self):
        if os.path.exists(self.state_path):
            with open(self.state_path) as f:
                self.state = json.load(f)
        else:
            self.state = {
                "circuit_id": "discovery-execution-rci",
                "best_score": None,
                "n_iters": 0,
                "trajectory": [],
                "frozen_eval": {
                    "metric_name": "pareto_coverage_reduction",
                    "wall_clock_budget_s": 3600
                },
                "last_kept": False,
                "flow": {"skill": 0.5, "challenge": 0.5, "adj": "stay"},
                "boundary_probes": {},
                "dual_process": "SYSTEM 2",
                "data_link": "raw_measurements"
            }
        if "data_hash" not in self.state["frozen_eval"]:
            raise RuntimeError("frozen_eval not pre-sealed — baseline must contain data_hash")
        if not self.check_frozen():
            raise RuntimeError("frozen_eval seal mismatch on load — tamper detected")

    def save_state(self):
        with open(self.state_path, "w") as f:
            json.dump(self.state, f, indent=2)

    def log_trial(self, trial):
        with open(self.results_path, "a") as f:
            f.write(json.dumps(trial) + "\n")

    def check_frozen(self) -> bool:
        current = self.state["frozen_eval"].copy()
        stored_hash = current.pop("data_hash", None)
        payload = json.dumps(current, sort_keys=True).encode()
        return hashlib.sha256(payload).hexdigest()[:16] == stored_hash

    # DISCOVERY PLANE
    def discover_from_observations(self, train: List[Dict], holdout: List[Dict]) -> Optional[Dict]:
        """Try multiple relation families. Accept only if holdout survives and reduction justified."""
        MIN_TRAIN = 2
        MIN_HOLDOUT = 1
        if len(train) < MIN_TRAIN or len(holdout) < MIN_HOLDOUT:
            return None
        candidates = []
        # Family: timestamp offset (only if delta is small)
        diffs = [abs(o["nonce"] - o["ts"]) for o in train]
        if diffs:
            max_diff = max(diffs)
            delta = int(max_diff * 1.1) + 1
            if delta < 10000 and all(abs(o["nonce"] - o["ts"]) <= delta for o in holdout):
                candidates.append({
                    "family": "timestamp",
                    "delta": delta,
                    "constraint": f"nonce ∈ [ts-{delta}, ts+{delta}]",
                    "derivation": "timestamp_offset max_diff*1.1 holdout_pass"
                })
        # Family: index-counter (nonce ≈ a + b * observation_index)
        if len(train) >= 2:
            nonces = [o["nonce"] for o in train]
            slope = nonces[1] - nonces[0]
            intercept = nonces[0]
            hold_ok = True
            for j, o in enumerate(holdout):
                pred = intercept + slope * (len(train) + j)
                if abs(o["nonce"] - pred) > 2:
                    hold_ok = False
                    break
            if hold_ok and abs(slope) < 10000:
                candidates.append({
                    "family": "counter",
                    "delta": 11,
                    "constraint": f"nonce ≈ {intercept} + {slope}*idx ±5",
                    "derivation": "index_counter holdout_pass",
                    "intercept": intercept,
                    "slope": slope
                })
        # Family: timestamp-affine (nonce ≈ a + b * ts)
        if len(train) >= 2:
            t0, n0 = train[0]["ts"], train[0]["nonce"]
            t1, n1 = train[1]["ts"], train[1]["nonce"]
            if t1 != t0:
                slope_ts = (n1 - n0) / (t1 - t0)
                intercept_ts = n0 - slope_ts * t0
                hold_ok = True
                for o in holdout:
                    pred = intercept_ts + slope_ts * o["ts"]
                    if abs(o["nonce"] - pred) > 2:
                        hold_ok = False
                        break
                if hold_ok:
                    candidates.append({
                        "family": "affine_ts",
                        "delta": 11,
                        "constraint": f"nonce ≈ {intercept_ts:.1f} + {slope_ts:.3f}*ts ±5",
                        "derivation": "timestamp_affine holdout_pass",
                        "intercept": intercept_ts,
                        "slope": slope_ts
                    })
        # Family: truncation (low bits) — require full nonce == masked ts
        for bits in (16, 8):
            mask = (1 << bits) - 1
            if all(o["nonce"] == (o["ts"] & mask) for o in train + holdout):
                candidates.append({
                    "family": "truncation",
                    "delta": mask + 1,
                    "constraint": f"nonce == ts & {mask}",
                    "derivation": f"truncation_{bits}bits holdout_pass",
                    "mask": mask
                })
                break
        # Family: prefix (first N digits of ts)
        for n_digits in (4, 5, 6, 7):
            if all(str(o["nonce"]) == str(o["ts"])[:n_digits] for o in train + holdout):
                candidates.append({
                    "family": "prefix",
                    "delta": 10 ** n_digits,
                    "constraint": f"nonce == first {n_digits} digits of ts",
                    "derivation": f"prefix_{n_digits}digits holdout_pass",
                    "n_digits": n_digits
                })
                break
        # Family: modulo — require nonce < mod and exact match
        for mod in (1000, 256, 100):
            if all(o["nonce"] < mod and o["nonce"] == o["ts"] % mod for o in train + holdout):
                candidates.append({
                    "family": "modulo",
                    "delta": mod,
                    "constraint": f"nonce == ts % {mod}",
                    "derivation": f"modulo_{mod} holdout_pass"
                })
                break
        if not candidates:
            return None
        derived_ids = [f"train_{i}" for i in range(len(train))]
        return {
            "hypotheses": candidates,
            "provenance": Provenance(
                constraint=" | ".join(c["constraint"] for c in candidates),
                derived_from=derived_ids,
                derivation="union_of_surviving:" + ",".join(c["family"] for c in candidates),
                confidence=0.9
            )
        }

    # EXECUTION PLANE
    def compile_reduced_space(self, hyp: Dict, train: List[Dict], query_context: Dict) -> Optional[ReducedSpace]:
        prov = hyp.get("provenance")
        if not isinstance(prov, Provenance) or not prov.valid():
            return ("ABSTAIN_PROVENANCE", None)
        # Exact observation identity
        expected_ids = [f"train_{i}" for i in range(len(train))]
        if prov.derived_from != expected_ids:
            return ("ABSTAIN_PROVENANCE", None)
        # Derivation check only for single timestamp hyp
        if "hypotheses" not in hyp and hyp.get("family", "timestamp") == "timestamp":
            max_diff = max(abs(o["nonce"] - o["ts"]) for o in train)
            expected_delta = int(max_diff * 1.1) + 1
            if hyp["delta"] != expected_delta:
                return ("ABSTAIN_DERIVATION", None)
        # Relation only; location from query_context
        query_ts = query_context.get("ts")
        if query_ts is None:
            return ("ABSTAIN_NO_QUERY", None)
        def gen():
            seen = set()
            hyps = hyp.get("hypotheses", [hyp])
            for h in hyps:
                base = query_ts
                delta = h["delta"]
                family = h.get("family", "timestamp")
                extra = h
                if family == "timestamp":
                    for v in range(base - delta, base + delta + 1):
                        if v not in seen:
                            seen.add(v)
                            yield v
                elif family == "counter":
                    # Requires explicit index; no ts fallback
                    if "index" not in query_context:
                        continue
                    intercept = extra.get("intercept", 0)
                    slope = extra.get("slope", 1)
                    idx = query_context["index"]
                    pred = int(intercept + slope * idx)
                    for d in range(-5, 6):
                        v = pred + d
                        if v not in seen:
                            seen.add(v)
                            yield v
                elif family == "affine_ts":
                    intercept = extra.get("intercept", 0)
                    slope = extra.get("slope", 0)
                    pred = int(intercept + slope * base)
                    for d in range(-5, 6):
                        v = pred + d
                        if v not in seen:
                            seen.add(v)
                            yield v
                elif family == "prefix":
                    n_digits = extra.get("n_digits", 6)
                    s = str(base)
                    prefix = int(s[:n_digits]) if len(s) >= n_digits else int(s)
                    for d in range(-5, 6):
                        v = prefix + d
                        if v not in seen:
                            seen.add(v)
                            yield v
                elif family == "modulo":
                    for v in range(delta):
                        if v not in seen:
                            seen.add(v)
                            yield v
                elif family == "truncation":
                    mask = extra.get("mask", 0xFFFF)
                    for v in range(mask + 1):
                        if v not in seen:
                            seen.add(v)
                            yield v
                else:
                    for v in range(base - delta, base + delta + 1):
                        if v not in seen:
                            seen.add(v)
                            yield v
        hyps = hyp.get("hypotheses", [hyp])
        estimated_size = 0
        for h in hyps:
            if h.get("family") == "prefix":
                estimated_size += 11
            elif h.get("family") == "truncation":
                estimated_size += h.get("mask", 0xFFFF) + 1
            elif h.get("family") in ("counter", "affine_ts"):
                estimated_size += 11
            else:
                estimated_size += h["delta"] * 2 + 1
        original = hyp.get("original", 2**32)
        reduction_ratio = original / max(estimated_size, 1)
        fe = self.state["frozen_eval"]
        min_ratio = fe.get("MIN_REDUCTION_RATIO", 2.0)
        max_candidates = fe.get("MAX_CANDIDATES", 1_000_000)
        if reduction_ratio < min_ratio:
            return ("ABSTAIN_NO_JUSTIFIED_REDUCTION", None)
        if estimated_size > max_candidates + 10:
            return ("ABSTAIN_RESOURCE_BUDGET", None)
        space = ReducedSpace(
            generator=gen,
            estimated_size=estimated_size,
            provenance=prov,
            original_space=original
        )
        space._lower = query_ts - 10000
        space._upper = query_ts + 10000  # loose bounds; contains uses stream for union
        space._family = "union" if "hypotheses" in hyp else hyp.get("family", "timestamp")
        return ("OK", space)

    def coverage_probe(self, space: ReducedSpace, hidden_target: Any) -> bool:
        return space.contains(hidden_target)

    def gpu_evaluator(self, space: ReducedSpace, metric_fn: Callable) -> Dict:
        """GPU-style evaluator. Must match CPU bit-for-bit on hit/target_found.
        Uses batched processing; same early-exit and deadline semantics."""
        import time
        deadline = time.monotonic() + self.state["frozen_eval"].get("wall_clock_budget_s", 3600)
        max_metric = float("-inf")
        eval_count = 0
        hit = None
        target_found = False
        deadline_exceeded = False
        batch = []
        BATCH = 64
        for c in space.candidates():
            if time.monotonic() > deadline:
                deadline_exceeded = True
                break
            batch.append(c)
            if len(batch) >= BATCH:
                for cand in batch:
                    m = metric_fn(cand)
                    eval_count += 1
                    if m > max_metric:
                        max_metric = m
                        hit = cand
                    if m > 0.5:
                        target_found = True
                        hit = cand
                        batch = []
                        break
                if target_found:
                    break
                batch = []
        if not target_found and batch:
            for cand in batch:
                if time.monotonic() > deadline:
                    deadline_exceeded = True
                    break
                m = metric_fn(cand)
                eval_count += 1
                if m > max_metric:
                    max_metric = m
                    hit = cand
                if m > 0.5:
                    target_found = True
                    hit = cand
                    break
        return {
            "max_metric": max_metric if eval_count else 0,
            "eval_count": eval_count,
            "hit": hit,
            "target_found": target_found,
            "deadline_exceeded": deadline_exceeded,
            "completed": not deadline_exceeded
        }

    def candidate_evaluator(self, space: ReducedSpace, metric_fn: Callable) -> Dict:
        import time
        deadline = time.monotonic() + self.state["frozen_eval"].get("wall_clock_budget_s", 3600)
        max_metric = float("-inf")
        eval_count = 0
        hit = None
        target_found = False
        deadline_exceeded = False
        for c in space.candidates():
            if time.monotonic() > deadline:
                deadline_exceeded = True
                break
            m = metric_fn(c)
            eval_count += 1
            if m > max_metric:
                max_metric = m
                hit = c
            if m > 0.5:  # observable match threshold; metric alone decides
                target_found = True
                hit = c
                break
        return {
            "max_metric": max_metric if eval_count else 0,
            "eval_count": eval_count,
            "hit": hit,
            "target_found": target_found,
            "deadline_exceeded": deadline_exceeded,
            "completed": not deadline_exceeded
        }

    def pareto_score(self, coverage: bool, reduction_ratio: float, eval_count: int, wall_time: float) -> tuple:
        return (
            1 if coverage else 0,
            reduction_ratio,
            -eval_count,
            -wall_time
        )

    def dominates(self, new: tuple, old: Optional[tuple]) -> bool:
        if new[0] != 1:  # hard coverage gate
            return False
        if old is None:
            return True
        # true Pareto on secondary axes
        return (
            all(n >= o for n, o in zip(new[1:], old[1:]))
            and
            any(n > o for n, o in zip(new[1:], old[1:]))
        )

    def rci_cycle(self, train: List[Dict], holdout: List[Dict], query_context: Dict, hidden_target: Any, verifier: FrozenVerifier):
        if not self.check_frozen():
            raise RuntimeError("frozen_eval hash mismatch")
        if type(verifier) is not FrozenVerifier:
            raise RuntimeError("untrusted verifier type")
        expected_vhash = self.state["frozen_eval"].get("verifier_code_hash")
        if expected_vhash and FrozenVerifier.code_hash() != expected_vhash:
            raise RuntimeError("verifier not frozen")
        start = datetime.utcnow()
        # Discovery
        hyp = self.discover_from_observations(train, holdout)
        if hyp is None:
            trial = {"kept": False, "reason": "discovery_falsified", "coverage": False}
            self.log_trial(trial)
            return trial
        # Compile
        status, space = self.compile_reduced_space(hyp, train, query_context)
        if status != "OK":
            trial = {"kept": False, "reason": status, "coverage": None, "space_coverage": None}
            self.log_trial(trial)
            return trial
        # Space coverage (analytical)
        space_coverage = self.coverage_probe(space, hidden_target)
        # Execution
        eval_res = self.candidate_evaluator(space, verifier)
        wall_time = (datetime.utcnow() - start).total_seconds()
        reduction_ratio = space.original_space / max(space.estimated_size, 1)
        # Execution success required for promotion
        if not space_coverage:
            trial = {"kept": False, "reason": "FALSE_EXCLUSION", "coverage": False, "space_coverage": False}
            self.log_trial(trial)
            return trial
        if not eval_res.get("target_found"):
            trial = {"kept": False, "reason": "EXECUTION_INCOMPLETE", "coverage": None, "space_coverage": True, "eval_count": eval_res["eval_count"], "deadline_exceeded": eval_res["deadline_exceeded"]}
            self.log_trial(trial)
            return trial
        # Benchmark oracle (outside execution plane)
        if eval_res.get("hit") != hidden_target:
            trial = {"kept": False, "reason": "ORACLE_MISMATCH", "coverage": None, "space_coverage": True, "eval_count": eval_res["eval_count"]}
            self.log_trial(trial)
            return trial
        score = self.pareto_score(True, reduction_ratio, eval_res["eval_count"], wall_time)
        # Ratchet
        kept = self.dominates(score, self.state["best_score"])
        if kept:
            self.state["best_score"] = score
        self.state["trajectory"].append({
            "iter": self.state["n_iters"] + 1,
            "score": score,
            "kept": kept,
            "coverage": True,
            "space_coverage": True,
            "target_found": True,
            "reduction_ratio": reduction_ratio,
            "provenance": asdict(space.provenance)
        })
        self.state["n_iters"] += 1
        self.state["last_kept"] = kept
        # Probes
        from probes.boundary_probes import inject_probes
        inject_probes(self.state, eval_res)
        trial = {
            "score": score,
            "kept": kept,
            "coverage": True,
            "space_coverage": True,
            "target_found": True,
            "reduction_ratio": reduction_ratio,
            "eval_count": eval_res["eval_count"],
            "provenance": asdict(space.provenance),
            "dual_process": "SYSTEM 2",
            "data_link": "discovery+coverage+eval"
        }
        self.log_trial(trial)
        self.save_state()
        return trial

    def short_analysis(self):
        s = self.state
        best = s.get("best_score")
        return f"""circuit={s['circuit_id']} best={best} n={s['n_iters']}
flow skill={s['flow']['skill']} chal={s['flow']['challenge']} adj={s['flow']['adj']}
last kept={s['last_kept']} metric={best} sys=2 origin=discovery_plane
{{"boundary_probes":{json.dumps(s.get('boundary_probes', {}))}}}"""
