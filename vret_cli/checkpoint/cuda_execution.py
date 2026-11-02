"""Physical CUDA Driver/NVRTC backend. No third-party Python dependencies.

Only the SHA256 primitive is ported; decimal serialization and candidate
ordering remain owned by the frozen source. No hidden target is accepted.
"""
import array
import ctypes as C
import glob
import os
from pathlib import Path
import time
from loops.ratchet_rci_loop import AgentOptimizationCircuit, FrozenVerifier


class CudaCircuit(AgentOptimizationCircuit):
    """Uses the frozen reference loop verbatim, with a physical device metric.

    Deliberately one candidate per launch: preserves lazy generator access,
    first-hit short circuit and the per-candidate deadline boundary. Bulk
    digest is a separate primitive, not silently substituted for this loop.
    """
    def __init__(self, *args, engine=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.engine = engine if engine is not None else CudaSHA256()
        self.execution_audit = []
        self.last_execution_seconds = None

    def candidate_evaluator(self, space, metric_fn):
        if type(metric_fn) is not FrozenVerifier:
            raise ValueError('CUDA adapter requires the exact FrozenVerifier type')
        expected = self.state['frozen_eval'].get('verifier_code_hash')
        if expected and FrozenVerifier.code_hash() != expected:
            raise ValueError('verifier not frozen')
        audit = []
        def device_metric(candidate):
            # The verifier public challenge is deliberately not sent to device.
            digest = self.engine.digest([str(candidate).encode()])[0][0]
            audit.append(candidate)
            return 1.0 if digest == metric_fn.public_challenge else 0.0
        started = time.perf_counter()
        result = super().candidate_evaluator(space, device_metric)
        self.last_execution_seconds = time.perf_counter() - started
        self.execution_audit.append(audit)
        return result


class CudaSHA256:
    def __init__(self):
        self.cuda = C.CDLL('libcuda.so.1')
        paths = glob.glob('/home/sefi/venvs/*/lib/python*/site-packages/nvidia/cuda_nvrtc/lib/libnvrtc.so.12')
        nvrtc = os.environ.get('NVRTC_LIBRARY')
        if not nvrtc:
            nvrtc = next((p for p in paths if '/vllm312/' in p), paths[0] if paths else 'libnvrtc.so')
        self.nvrtc_library = nvrtc
        self.nvrtc = C.CDLL(nvrtc)
        self._api(self.cuda, {
            'cuInit': [C.c_uint], 'cuDeviceGet': [C.POINTER(C.c_int), C.c_int],
            'cuDeviceGetName': [C.c_void_p, C.c_int, C.c_int],
            'cuDeviceGetAttribute': [C.POINTER(C.c_int), C.c_int, C.c_int],
            'cuDevicePrimaryCtxRetain': [C.POINTER(C.c_void_p), C.c_int],
            'cuCtxSetCurrent': [C.c_void_p], 'cuCtxSynchronize': [],
            'cuModuleLoadData': [C.POINTER(C.c_void_p), C.c_void_p],
            'cuModuleGetFunction': [C.POINTER(C.c_void_p), C.c_void_p, C.c_char_p],
            'cuMemAlloc_v2': [C.POINTER(C.c_uint64), C.c_size_t],
            'cuMemFree_v2': [C.c_uint64],
            'cuMemcpyHtoD_v2': [C.c_uint64, C.c_void_p, C.c_size_t],
            'cuMemcpyDtoH_v2': [C.c_void_p, C.c_uint64, C.c_size_t],
            'cuLaunchKernel': [C.c_void_p] + [C.c_uint]*7 + [C.c_void_p, C.c_void_p, C.c_void_p],
        })
        self._api(self.nvrtc, {
            'nvrtcCreateProgram': [C.POINTER(C.c_void_p), C.c_char_p, C.c_char_p, C.c_int, C.c_void_p, C.c_void_p],
            'nvrtcCompileProgram': [C.c_void_p, C.c_int, C.POINTER(C.c_char_p)],
            'nvrtcGetPTXSize': [C.c_void_p, C.POINTER(C.c_size_t)],
            'nvrtcGetPTX': [C.c_void_p, C.c_void_p],
            'nvrtcGetProgramLogSize': [C.c_void_p, C.POINTER(C.c_size_t)],
            'nvrtcGetProgramLog': [C.c_void_p, C.c_void_p],
            'nvrtcDestroyProgram': [C.POINTER(C.c_void_p)],
        })
        self._call('cuInit', 0)
        dev = C.c_int()
        self._call('cuDeviceGet', C.byref(dev), 0)
        name = C.create_string_buffer(256)
        self._call('cuDeviceGetName', name, len(name), dev)
        self.device_name = name.value.decode()
        major, minor = C.c_int(), C.c_int()
        self._call('cuDeviceGetAttribute', C.byref(major), 75, dev)
        self._call('cuDeviceGetAttribute', C.byref(minor), 76, dev)
        self.compute_capability = (major.value, minor.value)
        self.context = C.c_void_p()
        self._call('cuDevicePrimaryCtxRetain', C.byref(self.context), dev)
        self._call('cuCtxSetCurrent', self.context)
        prog = C.c_void_p()
        source = Path(__file__).with_name('sha256_device.cu').read_bytes()
        self._nv('nvrtcCreateProgram', C.byref(prog), source, b'sha256_device.cu', 0, None, None)
        try:
            opts = (C.c_char_p*1)(f'--gpu-architecture=compute_{major.value}{minor.value}'.encode())
            err = self.nvrtc.nvrtcCompileProgram(prog, 1, opts)
            if err:
                n = C.c_size_t()
                self._nv('nvrtcGetProgramLogSize', prog, C.byref(n))
                log = C.create_string_buffer(n.value)
                self._nv('nvrtcGetProgramLog', prog, log)
                raise RuntimeError(f'NVRTC {err}: {log.value.decode()}')
            n = C.c_size_t()
            self._nv('nvrtcGetPTXSize', prog, C.byref(n))
            ptx = C.create_string_buffer(n.value)
            self._nv('nvrtcGetPTX', prog, ptx)
            self.module = C.c_void_p()
            self._call('cuModuleLoadData', C.byref(self.module), ptx)
        finally:
            self._nv('nvrtcDestroyProgram', C.byref(prog))
        self.function = C.c_void_p()
        self._call('cuModuleGetFunction', C.byref(self.function), self.module, b'sha256_prefix')
        self.launch_count = 0
        self._storage = []

    def reserve(self, sizes):
        """Keep bounded reusable buffers; avoid allocator traffic per candidate."""
        self._call('cuCtxSetCurrent', self.context)
        for i, size in enumerate(sizes):
            if i == len(self._storage):
                self._storage.append((C.c_uint64(), 0))
            ptr, capacity = self._storage[i]
            if capacity < size:
                if capacity:
                    self._call('cuMemFree_v2', ptr)
                    self._storage[i] = (C.c_uint64(), 0)
                capacity = max(256, 1 << (size-1).bit_length())
                ptr = C.c_uint64()
                self._call('cuMemAlloc_v2', C.byref(ptr), capacity)
                self._storage[i] = (ptr, capacity)
        return [p for p, _ in self._storage]

    def close(self):
        if not getattr(self, '_storage', None):
            return
        self._call('cuCtxSetCurrent', self.context)
        for ptr, capacity in self._storage:
            if capacity:
                self._call('cuMemFree_v2', ptr)
        self._storage = []

    @staticmethod
    def _api(lib, functions):
        for name, args in functions.items():
            f = getattr(lib, name)
            f.argtypes, f.restype = args, C.c_int

    def _call(self, name, *args):
        err = getattr(self.cuda, name)(*args)
        if err:
            raise RuntimeError(f'{name}: CUDA error {err}')

    def _nv(self, name, *args):
        err = getattr(self.nvrtc, name)(*args)
        if err:
            raise RuntimeError(f'{name}: NVRTC error {err}')

    def digest(self, payloads, echo=False):
        """Includes packing, buffer growth, H2D, launch, sync and D2H.

        Device buffers are reused; close() frees them outside the hot path.

        Echo reads back the exact device input, for equivalence auditing.
        Returns the first 64 SHA256 bits as the frozen 16 hex characters.
        """
        count = len(payloads)
        if not count:
            return [], [] if echo else None
        offsets, lengths = array.array('Q'), array.array('I')
        position = 0
        for p in payloads:
            offsets.append(position)
            lengths.append(len(p))
            position += len(p)
        raw = b''.join(payloads)
        buffers = [C.create_string_buffer(raw),
                   C.create_string_buffer(offsets.tobytes()),
                   C.create_string_buffer(lengths.tobytes())]
        sizes = [max(1, len(raw)), count*8, count*4, count*8]
        pointers = self.reserve(sizes)
        for p, buf, size in zip(pointers, buffers, sizes):
            self._call('cuMemcpyHtoD_v2', p, buf, size)
        n = C.c_uint(count)
        args = (C.c_void_p*5)(*[C.addressof(p) for p in pointers], C.addressof(n))
        self._call('cuLaunchKernel', self.function, (count+255)//256, 1, 1, 256, 1, 1, 0, None, args, None)
        self.launch_count += 1
        self._call('cuCtxSynchronize')
        output = (C.c_uint64*count)()
        self._call('cuMemcpyDtoH_v2', output, pointers[3], count*8)
        echoed = None
        if echo:
            b = C.create_string_buffer(max(1, len(raw)))
            self._call('cuMemcpyDtoH_v2', b, pointers[0], len(raw))
            echoed = [b.raw[o:o+l] for o,l in zip(offsets,lengths)]
        return [f'{x:016x}' for x in output], echoed
