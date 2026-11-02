"""Single-worker PIPELINED_POLICY_V1; verified BatchedCircuit remains untouched."""
import array
import ctypes as C
import itertools
import queue
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from batch_execution import BatchedCircuit, FrozenVerifier, challenge_to_u64, pack

POLICY = 'PIPELINED_POLICY_V1'
_CREATION_LOCK = threading.Lock()

def _worker(engine):
    with _CREATION_LOCK:
        if not hasattr(engine, '_single_pipeline_executor'):
            engine._single_pipeline_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='cuda-single')
            engine._single_pipeline_lock = threading.Lock()
    return engine._single_pipeline_executor

def shutdown_pipeline(engine):
    executor = getattr(engine, '_single_pipeline_executor', None)
    if executor is not None:
        executor.shutdown(wait=True)
        del engine._single_pipeline_executor
        del engine._single_pipeline_lock

class PipelineCircuit(BatchedCircuit):
    def __init__(self, *args, pipeline=False, clock=None, trace=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.pipeline = pipeline
        self.clock = clock or time.monotonic
        self.trace = trace
        self.timeline = []
        self.pipeline_stats = {}

    def _span(self, name, start, end, batch):
        if self.trace:
            self.timeline.append({'name': name, 'start': start, 'end': end, 'batch': batch,
                                  'thread': threading.current_thread().name})

    def candidate_evaluator(self, space, metric_fn):
        if not self.pipeline:
            return super().candidate_evaluator(space, metric_fn)
        executor = _worker(self.engine)
        with self.engine._single_pipeline_lock:
            return self._evaluate(space, metric_fn, executor)

    def _evaluate(self, space, metric_fn, executor):
        if type(metric_fn) is not FrozenVerifier:
            raise ValueError('batched adapter requires the exact FrozenVerifier type')
        expected = self.state['frozen_eval'].get('verifier_code_hash')
        if expected and FrozenVerifier.code_hash() != expected:
            raise ValueError('verifier not frozen')
        challenge = challenge_to_u64(metric_fn.public_challenge)
        deadline = self.clock() + self.state['frozen_eval'].get('wall_clock_budget_s', 3600)
        it = space.candidates()
        prepared_queue = queue.Queue(maxsize=1)
        self.pipeline_stats = {'prefetch_max_batches': 0, 'prefetch_max_candidates': 0,
                               'max_inflight': 0, 'discarded_candidates': 0, 'contexts': []}
        stats = self.pipeline_stats
        eval_count, first, hit, found, exceeded = 0, None, None, False, False
        dispatched = []
        worker_ends = []

        def prepare(number):
            started = time.perf_counter()
            try:
                batch = list(itertools.islice(it, self.batch_size))
            except Exception as error:
                ended = time.perf_counter(); self.timers.add('generation', ended-started)
                self._span('generation', started, ended, number)
                return {'generation_error': error, 'number': number, 'batch': []}
            ended = time.perf_counter(); self.timers.add('generation', ended-started)
            self._span('generation', started, ended, number)
            if not batch:
                return None
            job = {'batch': batch, 'number': number, 'packed': None, 'i64': False}
            if challenge is not None:
                started = time.perf_counter()
                try:
                    ib = None
                    if self.use_i64 and set(map(type, batch)) == {int}:
                        try: ib = array.array('q', batch)
                        except OverflowError: pass
                    job['packed'] = ib if ib is not None else pack(batch)
                    job['i64'] = ib is not None
                except Exception:
                    job['scalar'] = True
                ended = time.perf_counter(); self.timers.add('pack', ended-started)
                self._span('pack', started, ended, number)
            return job

        def execute(job, accepted, submitted):
            started = time.perf_counter()
            self.timers.add('queue_wait', started-submitted)
            if worker_ends:
                self.timers.add('worker_idle', max(0, started-worker_ends[-1]))
            # A CUDA primary context is thread-local. Verify explicit binding in this worker.
            if hasattr(self.engine, 'cuda'):
                self.engine._api(self.engine.cuda, {'cuCtxGetCurrent': [C.POINTER(C.c_void_p)]})
                before, after = C.c_void_p(), C.c_void_p()
                self.engine._call('cuCtxGetCurrent', C.byref(before))
                self.engine._call('cuCtxSetCurrent', self.engine.context)
                self.engine._call('cuCtxGetCurrent', C.byref(after))
                if after.value != self.engine.context.value:
                    raise RuntimeError('CUDA worker context mismatch')
                stats['contexts'].append({'before': before.value, 'after': after.value,
                                          'expected': self.engine.context.value,
                                          'thread_id': threading.get_ident()})
            # Last policy observation before dispatch; never launch a queued expired batch.
            if self.clock() > deadline:
                accepted.set()
                return {'expired': True, 'idx': -1}
            job['dispatched'] = True
            stats['max_inflight'] = 1
            # CUDA handoff occurs AFTER cuLaunchKernel returns: otherwise producer
            # GIL-heavy packing can starve the worker before it even queues the kernel.
            # Non-CUDA/scalar jobs still hand off before execution.
            cuda_handoff = hasattr(self.engine, 'cuda') and challenge is not None and not job.get('scalar')
            if not cuda_handoff:
                accepted.set()
            original_call = getattr(self.engine, '_call', None)
            if cuda_handoff or (self.trace and original_call is not None):
                def traced_call(name, *args):
                    begin = time.perf_counter() if self.trace else 0
                    try:
                        result = original_call(name, *args)
                        if name == 'cuLaunchKernel': accepted.set()
                        return result
                    finally:
                        if self.trace:
                            label = {'cuCtxSynchronize': 'device_wait', 'cuMemcpyDtoH_v2': 'device_readback_wait'}.get(name)
                            if label: self._span(label, begin, time.perf_counter(), job['number'])
                self.engine._call = traced_call
            try:
                idx = -1
                if challenge is not None:
                    if job.get('scalar'):
                        idx = self._scalar_first(job['batch'], metric_fn)
                    else:
                        idx = (self.engine.first_match_i64(job['packed'], challenge) if job['i64']
                               else self.engine.first_match(job['packed'], challenge))
                return {'expired': False, 'idx': idx}
            finally:
                if cuda_handoff or (self.trace and original_call is not None): self.engine._call = original_call
                accepted.set()  # wake producer on pre-launch failure or no-launch invalid challenge
                worker_ends.append(time.perf_counter())

        job = prepare(0)
        future = None
        try:
            while job is not None:
                if 'generation_error' in job:
                    raise job['generation_error']
                accepted = threading.Event()
                future = executor.submit(execute, job, accepted, time.perf_counter())
                # Wait for the dispatch decision, not device completion. This prevents an
                # already-expired first dispatch from speculatively advancing TWO batches.
                t = time.perf_counter()
                while not accepted.wait(0.01):
                    if future.done(): future.result()  # surface context/setup failures
                self.timers.add('producer_idle', time.perf_counter()-t)
                if job.get('dispatched'):
                    dispatched.append(job['batch'])
                    if first is None: first = job['batch'][0]
                    next_job = prepare(job['number']+1)
                    if next_job is not None:
                        prepared_queue.put_nowait(next_job)
                        stats['prefetch_max_batches'] = 1
                        stats['prefetch_max_candidates'] = max(stats['prefetch_max_candidates'], len(next_job['batch']))
                t = time.perf_counter(); result = future.result(); future = None
                self.timers.add('producer_idle', time.perf_counter()-t)
                if result['expired']:
                    exceeded = True
                    break
                idx = result['idx']
                if idx >= 0:
                    eval_count += idx+1; hit = job['batch'][idx]; found = True
                    if not prepared_queue.empty():
                        stats['discarded_candidates'] = len(prepared_queue.get_nowait()['batch'])
                    break
                eval_count += len(job['batch'])
                job = prepared_queue.get_nowait() if not prepared_queue.empty() else None
        finally:
            # No running operation escapes an evaluator on exception or early exit.
            if future is not None: future.result()
        self.batch_audit.append(dispatched)
        if not found and eval_count: hit = first
        return {'max_metric': (1.0 if found else 0.0) if eval_count else 0,
                'eval_count': eval_count, 'hit': hit, 'target_found': found,
                'deadline_exceeded': exceeded, 'completed': not exceeded}
