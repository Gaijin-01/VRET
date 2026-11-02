"""Production batched executor (semantics-certified against the frozen CPU loop).

Contract (frozen as BATCHED_POLICY_V1):
  * candidates are pulled in ordered chunks of <= B from the unchanged generator
  * deadline is checked once per chunk, after the chunk is pulled and BEFORE dispatch
    (mirrors CPU: pull -> clock check -> evaluate). A dispatched chunk is in-flight:
    its first valid hit is accepted even if the clock expires meanwhile.
  * the returned hit is the LOWEST matching index in stream order; later matches and
    later speculative evaluations inside a dispatched chunk have no observable effect
  * eval_count is the LOGICAL count (index+1 on hit, chunk length on miss) == CPU for
    completed runs; physical SHA count and timeout eval_count are NOT claimed equal
  * the generator may be advanced up to the end of the dispatched chunk (speculative
    prefetch). Anything else (hidden target, verifier code) is untouched.
Engines: HashlibBatchSearch (reference), ShimBatchSearch (real kernel source on host),
CudaBatchSearch (physical, NVRTC). Original files are not modified.
"""
import array
import ctypes as C
import hashlib
import itertools
import re
import subprocess
import tempfile
import time
from pathlib import Path

from cuda_execution import CudaSHA256
from loops.ratchet_rci_loop import AgentOptimizationCircuit, FrozenVerifier

HERE = Path(__file__).resolve().parent
FAST_MAX_LEN = 55           # single SHA block: len + 1 (0x80) + 8 (length) <= 64
MAX_BATCH_BYTES = 2**32 - 128
_HEX16 = re.compile(r'[0-9a-f]{16}')


class Packed:
    __slots__ = ('n', 'data', 'offsets', 'max_len')

    def __init__(self, n, data, offsets, max_len):
        self.n, self.data, self.offsets, self.max_len = n, data, offsets, max_len


def pack(batch):
    """All-C-level serialisation: str() per candidate == frozen verifier's str(candidate).encode()."""
    strs = list(map(str, batch))
    joined = ''.join(strs)
    if joined.isascii():
        data = joined.encode('ascii')
        lens = list(map(len, strs))
    else:
        enc = [s.encode() for s in strs]
        data = b''.join(enc)
        lens = list(map(len, enc))
    if len(data) > MAX_BATCH_BYTES:
        raise ValueError('batch exceeds 32-bit offset range')
    return Packed(len(strs), data, array.array('I', itertools.accumulate(lens, initial=0)), max(lens))


def challenge_to_u64(challenge):
    """None = can never match (frozen verifier compares 16 lowercase-hex strings by equality)."""
    if isinstance(challenge, str) and _HEX16.fullmatch(challenge):
        return int(challenge, 16)
    return None


class _Timers(dict):
    def add(self, k, dt): self[k] = self.get(k, 0.0) + dt


class HashlibBatchSearch:
    """Reference engine: no device. Same interface; used for executor-logic tests."""
    name = 'hashlib'
    def __init__(self): self.launch_count = 0; self.timers = _Timers()

    def first_match(self, p, challenge):
        self.launch_count += 1
        want = challenge.to_bytes(8, 'big')
        d, o = p.data, p.offsets
        for i in range(p.n):
            if hashlib.sha256(d[o[i]:o[i+1]]).digest()[:8] == want:
                return i
        return -1


    def first_match_i64(self, vals, challenge):
        self.launch_count += 1
        want = challenge.to_bytes(8, 'big')
        for i, v in enumerate(vals):
            if hashlib.sha256(str(v).encode()).digest()[:8] == want:
                return i
        return -1


class ShimBatchSearch:
    """Runs the REAL sha256_batch.cu source as host C++ (grid emulated). Logic test only."""
    name = 'shim'
    _lib = None

    def __init__(self):
        if ShimBatchSearch._lib is None:
            so = Path(tempfile.mkdtemp(prefix='shim-')) / 'shim.so'
            subprocess.run(['g++', '-O2', '-shared', '-fPIC', '-std=c++17', '-w', '-o', str(so),
                            str(HERE/'cpu_shim'/'driver.cpp')], check=True)
            lib = C.CDLL(str(so))
            lib.shim_launch.argtypes = [C.c_int, C.c_uint, C.c_uint, C.c_char_p, C.c_void_p,
                                        C.c_uint, C.c_uint64, C.POINTER(C.c_uint)]
            lib.shim_launch_i64.argtypes = [C.c_uint, C.c_uint, C.c_void_p, C.c_uint, C.c_uint64, C.POINTER(C.c_uint)]
            ShimBatchSearch._lib = lib
        self.launch_count = 0; self.timers = _Timers()

    def first_match(self, p, challenge):
        res = C.c_uint(0xFFFFFFFF)
        off = (C.c_uint * len(p.offsets)).from_buffer(p.offsets)
        self._lib.shim_launch(int(p.max_len > FAST_MAX_LEN), (p.n + 255)//256, 256, p.data,
                              C.addressof(off), p.n, challenge, C.byref(res))
        self.launch_count += 1
        return -1 if res.value == 0xFFFFFFFF else res.value


    def first_match_i64(self, vals, challenge):
        res = C.c_uint(0xFFFFFFFF)
        self._lib.shim_launch_i64((len(vals) + 255)//256, 256, vals.buffer_info()[0], len(vals), challenge, C.byref(res))
        self.launch_count += 1
        return -1 if res.value == 0xFFFFFFFF else res.value


class CudaBatchSearch(CudaSHA256):
    """Physical engine. Reuses the verified driver bindings; compiles sha256_batch.cu."""
    name = 'cuda'

    def __init__(self, profile=False):
        super().__init__()
        self.profile = profile
        self.timers = _Timers()
        self._api(self.cuda, {'cuMemsetD32_v2': [C.c_uint64, C.c_uint, C.c_size_t]})
        prog = C.c_void_p()
        src = (HERE/'sha256_batch.cu').read_bytes()
        self._nv('nvrtcCreateProgram', C.byref(prog), src, b'sha256_batch.cu', 0, None, None)
        try:
            major, minor = self.compute_capability
            opts = (C.c_char_p*1)(f'--gpu-architecture=compute_{major}{minor}'.encode())
            err = self.nvrtc.nvrtcCompileProgram(prog, 1, opts)
            if err:
                n = C.c_size_t(); self._nv('nvrtcGetProgramLogSize', prog, C.byref(n))
                log = C.create_string_buffer(n.value); self._nv('nvrtcGetProgramLog', prog, log)
                raise RuntimeError(f'NVRTC {err}: {log.value.decode()}')
            n = C.c_size_t(); self._nv('nvrtcGetPTXSize', prog, C.byref(n))
            ptx = C.create_string_buffer(n.value); self._nv('nvrtcGetPTX', prog, ptx)
            self.batch_module = C.c_void_p()
            self._call('cuModuleLoadData', C.byref(self.batch_module), ptx)
        finally:
            self._nv('nvrtcDestroyProgram', C.byref(prog))
        self.kernels = {}
        for k in ('fast', 'generic', 'i64'):
            f = C.c_void_p()
            self._call('cuModuleGetFunction', C.byref(f), self.batch_module, f'sha256_match_{k}'.encode())
            self.kernels[k] = f
        self._bufs = {}

    def _buf(self, slot, size):
        ptr, cap = self._bufs.get(slot, (C.c_uint64(), 0))
        if cap < size:
            if cap: self._call('cuMemFree_v2', ptr)
            cap = max(4096, 1 << (size-1).bit_length()); ptr = C.c_uint64()
            self._call('cuMemAlloc_v2', C.byref(ptr), cap)
            self._bufs[slot] = (ptr, cap)
        return ptr

    def close(self):
        super().close()
        self._call('cuCtxSetCurrent', self.context)
        for ptr, cap in self._bufs.values():
            if cap: self._call('cuMemFree_v2', ptr)
        self._bufs = {}

    def _stage(self, p):
        """H2D of packed batch; returns device pointers."""
        t = time.perf_counter()
        d = self._buf('data', max(1, len(p.data)))
        o = self._buf('off', len(p.offsets)*4)
        r = self._buf('res', 4)
        self._call('cuMemcpyHtoD_v2', d, p.data, len(p.data))
        self._call('cuMemcpyHtoD_v2', o, p.offsets.buffer_info()[0], len(p.offsets)*4)
        self.timers.add('h2d', time.perf_counter()-t)
        return d, o, r

    def _launch(self, p, challenge, d, o, r):
        self._call('cuMemsetD32_v2', r, 0xFFFFFFFF, 1)
        n, ch = C.c_uint(p.n), C.c_uint64(challenge)
        args = (C.c_void_p*5)(C.addressof(d), C.addressof(o), C.addressof(n), C.addressof(ch), C.addressof(r))
        fn = self.kernels['generic' if p.max_len > FAST_MAX_LEN else 'fast']
        self._call('cuLaunchKernel', fn, (p.n+255)//256, 1, 1, 256, 1, 1, 0, None, args, None)
        self.launch_count += 1

    def first_match(self, p, challenge):
        d, o, r = self._stage(p)
        t = time.perf_counter()
        self._launch(p, challenge, d, o, r)
        if self.profile:                       # separates kernel time from the D2H wait
            self.timers.add('launch', time.perf_counter()-t)
            t = time.perf_counter(); self._call('cuCtxSynchronize'); self.timers.add('kernel_sync', time.perf_counter()-t)
        t = time.perf_counter()
        out = C.c_uint(0)
        self._call('cuMemcpyDtoH_v2', C.byref(out), r, 4)   # synchronising on the default stream
        self.timers.add('d2h' if self.profile else 'launch_sync_d2h', time.perf_counter()-t)
        return -1 if out.value == 0xFFFFFFFF else out.value

    def first_match_i64(self, vals, challenge):
        n = len(vals)
        t = time.perf_counter()
        d = self._buf('vals', n*8); r = self._buf('res', 4)
        self._call('cuMemcpyHtoD_v2', d, vals.buffer_info()[0], n*8)
        self.timers.add('h2d', time.perf_counter()-t)
        t = time.perf_counter()
        self._call('cuMemsetD32_v2', r, 0xFFFFFFFF, 1)
        cn, ch = C.c_uint(n), C.c_uint64(challenge)
        args = (C.c_void_p*4)(C.addressof(d), C.addressof(cn), C.addressof(ch), C.addressof(r))
        self._call('cuLaunchKernel', self.kernels['i64'], (n+255)//256, 1, 1, 256, 1, 1, 0, None, args, None)
        self.launch_count += 1
        if self.profile:
            self.timers.add('launch', time.perf_counter()-t)
            t = time.perf_counter(); self._call('cuCtxSynchronize'); self.timers.add('kernel_sync', time.perf_counter()-t)
        t = time.perf_counter(); out = C.c_uint(0)
        self._call('cuMemcpyDtoH_v2', C.byref(out), r, 4)
        self.timers.add('d2h' if self.profile else 'launch_sync_d2h', time.perf_counter()-t)
        return -1 if out.value == 0xFFFFFFFF else out.value

    def kernel_attrs(self):
        """Register / local-memory (spill) report per kernel. UNTESTED on device until run on the RTX 6000."""
        self._api(self.cuda, {'cuFuncGetAttribute': [C.POINTER(C.c_int), C.c_int, C.c_void_p]})
        out = {}
        for k, f in self.kernels.items():
            r, l = C.c_int(), C.c_int()
            self._call('cuFuncGetAttribute', C.byref(r), 4, f)   # CU_FUNC_ATTRIBUTE_NUM_REGS
            self._call('cuFuncGetAttribute', C.byref(l), 3, f)   # CU_FUNC_ATTRIBUTE_LOCAL_SIZE_BYTES
            out[k] = {'regs': r.value, 'local_bytes': l.value}
        return out

    def kernel_only_rate(self, p, challenge, reps=50):
        """Resident-data kernel throughput (no H2D/D2H): the device ceiling."""
        d, o, r = self._stage(p)
        self._call('cuCtxSynchronize')
        t = time.perf_counter()
        for _ in range(reps): self._launch(p, challenge, d, o, r)
        self._call('cuCtxSynchronize')
        return p.n*reps/(time.perf_counter()-t)


class BatchedCircuit(AgentOptimizationCircuit):
    """Drop-in candidate_evaluator under BATCHED_POLICY_V1. Frozen discovery untouched."""
    def __init__(self, *args, engine=None, batch_size=16384, use_i64=True, **kwargs):
        super().__init__(*args, **kwargs)
        if batch_size < 1: raise ValueError('batch_size')
        self.engine = engine if engine is not None else CudaBatchSearch()
        self.batch_size = batch_size
        self.use_i64 = use_i64 and hasattr(self.engine, 'first_match_i64')
        self.batch_audit = []          # per evaluator call: list of dispatched chunks (stream order)
        self.timers = _Timers()

    def candidate_evaluator(self, space, metric_fn):
        if type(metric_fn) is not FrozenVerifier:
            raise ValueError('batched adapter requires the exact FrozenVerifier type')
        expected = self.state['frozen_eval'].get('verifier_code_hash')
        if expected and FrozenVerifier.code_hash() != expected:
            raise ValueError('verifier not frozen')
        challenge = challenge_to_u64(metric_fn.public_challenge)   # public only; hidden target never seen
        deadline = time.monotonic() + self.state['frozen_eval'].get('wall_clock_budget_s', 3600)
        eval_count, first, hit, found, exceeded = 0, None, None, False, False
        dispatched = []
        it = space.candidates()
        while True:
            batch = list(itertools.islice(it, self.batch_size))
            if not batch:
                break
            if time.monotonic() > deadline:           # check AFTER pull, BEFORE dispatch (CPU order)
                exceeded = True
                break
            dispatched.append(batch)
            if first is None:
                first = batch[0]
            idx = -1
            if challenge is not None:
                try:
                    t = time.perf_counter(); ib = None
                    if self.use_i64 and set(map(type, batch)) == {int}:   # exact int only: bool/str/float keep str() path
                        try: ib = array.array('q', batch)
                        except OverflowError: ib = None            # beyond int64 -> generic path
                    p = ib if ib is not None else pack(batch)
                    self.timers.add('pack', time.perf_counter()-t)
                except Exception:
                    # unserialisable candidate: replay the CPU scalar semantics so any exception
                    # surfaces exactly where the frozen loop would raise it
                    idx = self._scalar_first(batch, metric_fn)
                else:
                    idx = (self.engine.first_match_i64(p, challenge) if ib is not None
                           else self.engine.first_match(p, challenge))
            if idx >= 0:
                eval_count += idx + 1
                hit, found = batch[idx], True
                break
            eval_count += len(batch)
        self.batch_audit.append(dispatched)
        if not found and eval_count:
            hit = first
        return {'max_metric': (1.0 if found else 0.0) if eval_count else 0,
                'eval_count': eval_count, 'hit': hit, 'target_found': found,
                'deadline_exceeded': exceeded, 'completed': not exceeded}

    @staticmethod
    def _scalar_first(batch, metric_fn):
        for i, c in enumerate(batch):
            if metric_fn(c) > 0.5:
                return i
        return -1
