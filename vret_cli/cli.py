#!/usr/bin/env python3
"""VRET CLI: stdlib-only front end for the immutable, locally verified VRET checkpoint."""
import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

PACKAGE_ROOT = Path(__file__).resolve().parent
DEFAULT_ROOT = PACKAGE_ROOT / 'checkpoint'
POLICY = 'PIPELINED_POLICY_V1'
IDENTITY = 'Verified Reduction & Execution Toolkit'


def version():
    return Path(__file__).with_name('VERSION').read_text().strip()


LAUNCHER = (
    "import os,sys\n"
    "target=sys.argv[1]\n"
    "sys.argv=[target]+sys.argv[2:]\n"
    "_chdir=os.chdir\n"
    "def _compat_chdir(path):\n"
    "    try:\n"
    "        _chdir(path)\n"
    "    except (FileNotFoundError,NotADirectoryError):\n"
    "        pass\n"
    "os.chdir=_compat_chdir\n"
    "_code=open(target,'rb').read()\n"
    "_g={'__name__':'__main__','__file__':target,'__builtins__':__builtins__}\n"
    "exec(compile(_code,target,'exec'),_g)\n"
)

def root_path():
    return Path(os.environ.get('VRET_ROOT', str(DEFAULT_ROOT))).expanduser().resolve()


def read_json(path):
    with path.open() as stream:
        return json.load(stream)


def inside(root, name):
    path = (root / name).resolve()
    if not path.is_relative_to(root):
        raise ValueError(f'path escapes VRET root: {name}')
    return path


def metadata(root):
    acceptance = read_json(root / 'receipts/acceptance.json')
    equivalence = read_json(root / 'receipts/pipeline_equivalence_cuda.json')
    benchmark = read_json(root / 'receipts/pipeline_ab.json')
    original = read_json(root / 'original_manifest.json')
    summary = equivalence['summary']
    episodes = equivalence['episodes']
    expected = summary['episodes_per_batch_size'] * len(summary['batch_sizes'])
    if not (acceptance[POLICY] == 'PASS' and acceptance['ACCEPT_PIPELINE']
            and acceptance['PIPELINE_EQUIVALENCE'] == 0
            and summary['mismatches'] == 0 and summary['policy'] == POLICY
            and len(episodes) == expected and expected > 0
            and all(row['ok'] for row in episodes)):
        raise ValueError('checkpoint acceptance/equivalence receipts do not verify')
    hashes = dict(benchmark['hashes_before'])
    hashes.update(original)
    for name, digest in hashes.items():
        if hashlib.sha256(inside(root, name).read_bytes()).hexdigest() != digest:
            raise ValueError(f'checkpoint integrity mismatch: {name}')
    capability = benchmark['compute_capability']
    sm = ''.join(map(str, capability))
    return {'policy': summary['policy'], 'device': summary['device'], 'sm': sm,
            'count': len(episodes), 'throughput': acceptance['BEST_PIPE_CAND_S'],
            'frozen_count': len(original), 'source_hashes_checked': len(hashes)}


def status(root, data):
    print('VRET checkpoint: VERIFIED')
    print('policy:', data['policy'])
    print(f"backend: CUDA {data['device']} / sm_{data['sm']}")
    print('pipeline: available')
    print(f"verified throughput: {data['throughput'] / 1_000_000:.3f}M candidates/s")
    print(f"physical equivalence: {data['count']}/{data['count']}")
    print(f"frozen originals: unchanged ({data['frozen_count']}/{data['frozen_count']})")
    print('root:', root)
    print('verification: local historical receipts + current protected-source hashes; not a live benchmark')


def child_env():
    return {**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'}


def doctor(root):
    failures = 0
    def check(ok, label):
        nonlocal failures
        print(('PASS' if ok else 'FAIL') + ' ' + label)
        failures += not ok
    check(root.is_dir(), f'checkpoint root: {root}')
    for name in ['pipeline_execution.py', 'PIPELINED_POLICY_V1.md', 'PHYSICAL_PIPELINE_REPORT.md', 'receipts']:
        path = root / name
        check(path.is_dir() if name == 'receipts' else path.is_file(), name)
    if root.is_dir():
        code = ("import importlib; "
                "[importlib.import_module(n) for n in "
                "['cuda_execution','batch_execution','pipeline_execution',"
                "'blind50_v0','heldout_v1','unseen_holdout']]")
        try:
            result = subprocess.run([sys.executable, '-B', '-c', code], cwd=root,
                                    env=child_env(), capture_output=True, text=True, timeout=30)
            check(result.returncode == 0, f'toolkit Python imports ({sys.executable})')
            if result.returncode:
                print(result.stderr.strip())
        except (OSError, subprocess.TimeoutExpired) as error:
            check(False, f'toolkit Python imports: {error}')
        try:
            data = metadata(root)
            check(True, f"receipt integrity; {data['source_hashes_checked']} protected source hashes")
        except (OSError, ValueError, KeyError, TypeError) as error:
            check(False, f'checkpoint receipts/integrity: {error}')
    visible = False
    smi = shutil.which('nvidia-smi')
    if smi:
        try:
            result = subprocess.run([smi, '--query-gpu=name', '--format=csv,noheader'],
                                    capture_output=True, text=True, timeout=8)
            visible = result.returncode == 0 and bool(result.stdout.strip())
            print(('PASS NVIDIA GPU: ' + result.stdout.strip()) if visible else
                  'WARN NVIDIA GPU not visible via nvidia-smi; CPU-only commands remain usable')
        except (OSError, subprocess.TimeoutExpired) as error:
            print(f'WARN nvidia-smi: {error}')
    else:
        print('WARN nvidia-smi absent; GPU visibility checked through libcuda if available')
    try:
        cuda = ctypes.CDLL('libcuda.so.1')
        print('PASS libcuda.so.1 available')
        cuda.cuInit.argtypes = [ctypes.c_uint]
        cuda.cuInit.restype = ctypes.c_int
        cuda.cuDeviceGetCount.argtypes = [ctypes.POINTER(ctypes.c_int)]
        cuda.cuDeviceGetCount.restype = ctypes.c_int
        result = cuda.cuInit(0)
        count = ctypes.c_int()
        if result == 0:
            result = cuda.cuDeviceGetCount(ctypes.byref(count))
        if result == 0 and count.value > 0:
            print(f'PASS CUDA visible devices: {count.value}')
        elif visible:
            check(False, f'GPU visible but CUDA driver unavailable: code={result}, count={count.value}')
        else:
            print(f'WARN no usable CUDA GPU: code={result}, count={count.value}; CPU-only commands remain usable')
    except (OSError, AttributeError) as error:
        if visible:
            check(False, f'GPU visible but required libcuda unavailable: {error}')
        else:
            print(f'WARN CUDA unavailable in CPU-only environment: {error}')
    print('DOCTOR:', 'FAIL' if failures else 'PASS (WARN is non-fatal)')
    return 1 if failures else 0


def run_script(root, script, args):
    relative = Path(script)
    if relative.is_absolute() or '..' in relative.parts:
        raise ValueError('script must be relative to VRET root, without ..')
    target = inside(root, relative)
    if not target.is_file() or target.suffix != '.py':
        raise ValueError('target must be an existing .py file inside VRET root')
    # Inherited streams; no shell. Suppress import-cache writes into the checkpoint.
    # The script runs in place, inside the checkpoint root, with the root as its
    # working directory -- the historical contract of this CLI.
    result = subprocess.call([sys.executable, '-B', '-c', LAUNCHER, str(target), *args],
                              cwd=root, env=child_env())
    return result if result >= 0 else 128 - result


def main(argv=None):
    parser = argparse.ArgumentParser(prog='vret', description=f'VRET — {IDENTITY}')
    parser.add_argument('--version', action='version', version=f'VRET {version()} policy={POLICY}')
    sub = parser.add_subparsers(dest='command', required=True)
    for name in ['root', 'status', 'doctor', 'info']:
        sub.add_parser(name)
    report = sub.add_parser('report'); report.add_argument('--cat', action='store_true')
    receipts = sub.add_parser('receipts'); receipts.add_argument('--list', action='store_true')
    run = sub.add_parser('run', help='execute a trusted checkpoint script (not a sandbox)')
    run.add_argument('script'); run.add_argument('args', nargs=argparse.REMAINDER)
    options = parser.parse_args(argv)
    root = root_path()
    try:
        if options.command == 'root':
            print(root)
        elif options.command == 'doctor':
            return doctor(root)
        elif options.command in ['status', 'info']:
            data = metadata(root)
            if options.command == 'info':
                print(f'VRET {version()} — {IDENTITY}')
                print('CLI:', Path(__file__).resolve())
            status(root, data)
            if options.command == 'info':
                print('report:', root / 'PHYSICAL_PIPELINE_REPORT.md')
                print('receipts:', root / 'receipts')
                print('mode: external wrapper; reference pipeline=False retained; no benchmark runs implicitly')
        elif options.command == 'report':
            path = root / 'PHYSICAL_PIPELINE_REPORT.md'
            if not path.is_file(): raise ValueError(f'missing report: {path}')
            if options.cat: print(path.read_text(), end='')
            else: print(path)
        elif options.command == 'receipts':
            path = root / 'receipts'
            if not path.is_dir(): raise ValueError(f'missing receipts: {path}')
            print(path)
            if options.list:
                for entry in sorted(path.iterdir()):
                    print(entry.name + ('/' if entry.is_dir() else ''))
        elif options.command == 'run':
            return run_script(root, options.script, options.args)
        return 0
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f'vret: {error}', file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == '__main__':
    sys.exit(main())
