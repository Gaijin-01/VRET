# Release acceptance report — VRET CLI/CUDA 0.2.0

Every row was checked against the artifact that ships in this release, not
against an earlier run of it. Machine-specific paths are not reproduced here.

## A. Source integrity and provenance

| Check | Result |
| --- | --- |
| Source of truth identified | `/home/sefi/vret-cli/vret_cli.py` (CLI), imported `agent-tooling-blueprints` tree (checkpoint) |
| CLI version / policy | `0.2.0` / `PIPELINED_POLICY_V1` |
| Protected checkpoint files verified | **18/18**, 0 missing, 0 mismatched |
| Working source tree unmodified during the audit | yes — validated against an immutable copy, SHA-256 manifests identical |
| Third-party exact copies found in checkpoint | none |
| Distinctive overlap with operator-supplied native guide/runner | none |
| Runtime dependencies | none (Python standard library only) |

## B. Clean install

| Check | Result |
| --- | --- |
| Wheel build (stdlib-only PEP 517 backend) | pass |
| Source distribution build | pass |
| Install into a clean virtual environment | pass |
| `vret --version` from the installed wheel | `VRET 0.2.0 policy=PIPELINED_POLICY_V1` |
| `vret root` from the installed wheel | resolves to the packaged checkpoint inside the installed package |
| `VRET_ROOT` override honoured | pass |
| `vret status` from the installed wheel | `VERIFIED` |

## C. Command matrix (installed wheel)

| Command | Expected | Result |
| --- | --- | --- |
| `--version` | version and policy line | pass |
| `root` | packaged checkpoint path | pass |
| `status` | `VERIFIED` + verified throughput | pass |
| `doctor` | environment report, warnings not failures | pass |
| `info` | component metadata | pass |
| `report` | report content | pass |
| `receipts --list` | receipt inventory | pass |
| `run <script>` | script executes, exit code and argv preserved | pass |

## D. Tests

| Suite | Result |
| --- | --- |
| Packaged CLI contract (9 tests, adapted from the working CLI's own contract) | **9/9 PASS** |
| Runtime-semantics contract (4 tests, new — pins the one deliberate delta vs the working CLI) | **4/4 PASS** |
| Toolkit suite | 55 OK, 2 skipped |
| Strict CUDA checkpoint suite | 2/2 OK |
| Batched CUDA equivalence | 0 mismatches |
| Physical equivalence (GPU vs CPU digest) | **500/500**, 0 mismatches |
| Fresh device/CPU equivalence | 100 episodes, 0 mismatches, 1,679 CUDA launches |
| Frozen original results unchanged | 12/12 |

The packaged suite is executed against the packaged tree, not against the
development tree.

## D2. Shipped-tree reduction (0.2.0)

| Check | Result |
| --- | --- |
| Files removed from the previous release tree | 32 (bulk/physical benchmark drivers, host-ceiling probe, iteration loop, superseded first-pass receipts and logs) |
| Files shipped | 49 (checkpoint: 31) |
| AST import-graph audit of the packaged tree | no unresolved or dangling local import after removal |
| Runtime dependency on the removed lane | none — `cpu_shim/` is retained because `batch_execution.py` compiles `cpu_shim/driver.cpp` as the CPU oracle |
| Receipts changed | none — `acceptance.json`, `pipeline_ab.json`, `pipeline_equivalence_cuda.json` and the dated fresh receipts are byte-identical |
| Protected hashes after removal | **18/18**, 0 missing, 0 mismatched |
| Measured values after removal | unchanged — no benchmark number was re-measured, edited or hard-coded |

The removal is a packaging decision, not a change of the artifact's claims.
`docs/provenance.md` states exactly which lane was withheld and why.

## E. Path and shell boundary

| Case | Expected | Result |
| --- | --- | --- |
| `..` traversal in `run` | rejected | pass |
| absolute path in `run` | rejected | pass |
| symlink escape in `run` | rejected | pass |
| wrong file extension in `run` | rejected | pass |
| shell metacharacters in script arguments | passed literally, no shell | pass |
| missing file in `run` | rejected | pass |

## F. Security scan

| Check | Result |
| --- | --- |
| Secrets / tokens / API keys / private URLs | **0** |
| `.env`, credential files, SSH material | none shipped |
| Absolute host paths in publishable files | 5 hash-pinned checkpoint files (4 reference `/workspace/artifacts/agent-tooling-blueprints`, 1 a `/home/sefi/venvs/...` NVRTC glob; disclosed, unchangeable without breaking the pinned digests) + 1 fresh receipt (redacted) |
| Oversized artifacts, generated blobs | none |
| Personal data in shipped files | none |
| `__pycache__`, `.pyc`, `.bak` | excluded |

## G. License and distribution

| Check | Result |
| --- | --- |
| License | MIT (`LICENSE`), first-party project |
| Third-party licenses to reproduce | none — no third-party code vendored |
| Checkpoint components cleared for redistribution | yes — first-party generated output; operator-supplied inputs identified and checked for overlap |
| Research Reference (`v0.2.0`) untouched | yes — separate repository, tag and release intact |

## H. Benchmark reproducibility

| Metric | Value |
| --- | --- |
| Pipelined | 14,378,740 candidates/s |
| Non-pipelined | 12,689,379 candidates/s |
| CPU comparator | 1,181,864 candidates/s |
| Ratios | 1.133× and 12.166× |
| Cold init + compile (reported separately) | 0.410 s |
| Corpus | 65,536 unique frozen-discovery integers (replay) |
| Repetitions | strict 1, bulk 3, A/B 7 paired alternating runs, median reported |
| Boundary | serialization, packing, H2D, launch, sync, D2H, Python digest formatting included; cold init excluded |

Full detail, hardware and limits: `docs/benchmark_receipt.md`.

## I. Namespace separation

| Item | Value |
| --- | --- |
| Research Reference repository | `Gaijin-01/VRET-Research-Reference` (renamed; repository ID, `v0.2.0` tag object, release and all six assets intact) |
| History rewritten / tag moved / assets deleted / force-push | none |
| Canonical repository for this release | `Gaijin-01/VRET` |
| This release's version line | `0.2.0` — independent of the Research Reference's `v0.2.0` |

## J. Publication

| Check | Result |
| --- | --- |
| Initial commit | see `git/` audit workspace and the published repository |
| Tag | `v0.2.0` |
| Release assets | wheel, source distribution, `source_manifest.json`, `SHA256SUMS.txt` |
| Public readback | performed against the published repository after the push |

## K. Runtime-semantics delta versus the working CLI

Exactly one observable difference exists between this package and the working
CLI at `/home/sefi/vret-cli/vret_cli.py`. It is deliberate, documented and
tested.

| Aspect | Working CLI | This package |
| --- | --- | --- |
| `run` working directory | checkpoint root | checkpoint root (identical) |
| `run` copies the checkpoint | no | no (identical) |
| `sys.argv` / `__file__` / `__name__` | script path / script path / `__main__` | identical |
| Shell usage | none | none (identical) |
| `os.chdir` into a missing directory | raises `FileNotFoundError` | tolerated by an interpreter shim |

The shim exists because four hash-pinned checkpoint modules `chdir` into
`/workspace/artifacts/agent-tooling-blueprints`, a path that does not exist in
an installed package. No checkpoint file was modified; the 18 pinned files are
byte-identical to the working checkpoint. The difference is pinned on both
sides by `tests/test_runtime_semantics.py`.

No other runtime semantics were changed. Packaging-only changes: the default
checkpoint root resolves relative to the installed package instead of an
absolute development path, and `VRET_ROOT` still overrides it.

## Known limitations

1. Five hash-pinned checkpoint files still contain absolute host paths
   (`/workspace/artifacts/agent-tooling-blueprints` in four of them, a
   `/home/sefi/venvs/...` NVRTC glob in `cuda_execution.py`). They cannot
   be edited without invalidating the digests that `vret status` verifies. The
   CLI's script launcher tolerates the absent `/workspace` directory.
2. `bulk_semantics_certified_for_circuit: false` — the bulk path is faster but
   is not certified as semantically equivalent to the strict path.
3. The measured corpus is a replay of a frozen discovery space, not a stream of
   new unique spaces.
4. Throughput figures are single-GPU, single-driver, single-corpus measurements
   and are not universal speedup claims.
5. The benchmark was measured with the GPU otherwise idle; concurrent device
   workloads share the device and invalidate timing.
