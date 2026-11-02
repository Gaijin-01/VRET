def validate_probes(probes):
    required = ["coverage", "reduction_ratio", "provenance_valid", "frozen_integrity"]
    for p in required:
        if p not in probes or "evidence" not in probes[p]:
            return False
    return True

def inject_probes(state, raw):
    last = state.get("trajectory", [{}])[-1] if state.get("trajectory") else {}
    prov = last.get("provenance", {})
    probes = {
        "coverage": {
            "value": last.get("coverage"),
            "evidence": "coverage_probe_raw"
        },
        "reduction_ratio": {
            "value": last.get("reduction_ratio"),
            "evidence": "original/estimated"
        },
        "provenance_valid": {
            "value": bool(prov.get("derived_from")) and prov.get("confidence", 0) > 0.5,
            "evidence": "Provenance.derived_from+confidence"
        },
        "frozen_integrity": {
            "value": state["frozen_eval"].get("data_hash"),
            "evidence": "sha256_check"
        }
    }
    state["boundary_probes"] = probes
    return validate_probes(probes)
