"""Runtime-semantics contract for the packaged VRET CLI.

The packaged CLI differs from the development copy in exactly one observable
way: ``vret run`` launches the target script through an interpreter shim that
makes ``os.chdir`` tolerate a directory that does not exist. This exists
because four hash-pinned checkpoint modules ``chdir`` into the upstream
workspace path ``/workspace/artifacts/agent-tooling-blueprints``, which is
absent from an installed package.

These tests pin both sides of that difference so it can never become a silent
behaviour change, and they pin the parts of the launch contract that must stay
identical to the development copy:

* the script runs **in place** -- its working directory is the checkpoint root,
  not a scratch copy of it;
* ``sys.argv[0]`` is the script path and the remaining arguments are literal;
* ``__name__`` is ``__main__`` and ``__file__`` is the script path;
* no shell is spawned.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

CLI = Path(__file__).resolve().parent.parent / 'vret_cli' / 'cli.py'
ROOT = str(Path(__file__).resolve().parent.parent / 'vret_cli' / 'checkpoint')

# The upstream workspace directory referenced by hash-pinned checkpoint
# modules. It does not exist in an installed package.
MISSING_WORKSPACE = '/workspace/artifacts/agent-tooling-blueprints'


class RuntimeSemanticsTests(unittest.TestCase):
    def call(self, *args, root=ROOT):
        return subprocess.run(
            [sys.executable, '-B', str(CLI), *args],
            env={**os.environ, 'VRET_ROOT': root, 'PYTHONDONTWRITEBYTECODE': '1'},
            capture_output=True, text=True)

    def test_run_executes_in_place_with_root_as_cwd(self):
        """The checkpoint is executed in place; no scratch copy is used."""
        with tempfile.TemporaryDirectory() as d:
            probe = Path(d, 'probe.py')
            probe.write_text(
                'import json,os,sys;'
                'print(json.dumps({"cwd": os.getcwd(), "argv": sys.argv,'
                ' "name": __name__, "file": __file__}))')
            p = self.call('run', 'probe.py', '--literal', 'a b', '; echo BAD', root=d)
            self.assertEqual(p.returncode, 0, p.stderr)
            data = json.loads(p.stdout)
            self.assertEqual(data['cwd'], os.path.realpath(d))
            self.assertEqual(data['argv'][1:], ['--literal', 'a b', '; echo BAD'])
            self.assertEqual(data['name'], '__main__')
            self.assertEqual(data['file'], str(probe))

    def test_run_tolerates_missing_workspace_chdir(self):
        """Packaged behaviour: a chdir into a missing directory is tolerated."""
        with tempfile.TemporaryDirectory() as d:
            Path(d, 'probe.py').write_text(
                'import os;'
                f'os.chdir({MISSING_WORKSPACE!r});'
                'print("SURVIVED")')
            p = self.call('run', 'probe.py', root=d)
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertIn('SURVIVED', p.stdout)

    def test_direct_execution_without_shim_fails_on_missing_workspace(self):
        """Development-copy behaviour: without the shim the same call fails.

        This is the side of the difference that the packaged CLI deliberately
        does *not* reproduce. It is asserted here so the delta stays visible.
        """
        with tempfile.TemporaryDirectory() as d:
            script = Path(d, 'probe.py')
            script.write_text(
                'import os;'
                f'os.chdir({MISSING_WORKSPACE!r});'
                'print("SURVIVED")')
            p = subprocess.run([sys.executable, '-B', str(script)],
                               capture_output=True, text=True, cwd=d)
            self.assertNotEqual(p.returncode, 0)
            self.assertIn('FileNotFoundError', p.stderr)

    def test_run_does_not_spawn_a_shell(self):
        """Arguments are literal; shell metacharacters never reach a shell."""
        with tempfile.TemporaryDirectory() as d:
            Path(d, 'probe.py').write_text(
                'import json,sys; print(json.dumps(sys.argv[1:]))')
            p = self.call('run', 'probe.py', '; touch /tmp/vret-shell-probe',
                          '$(id)', '`id`', root=d)
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertEqual(
                json.loads(p.stdout),
                ['; touch /tmp/vret-shell-probe', '$(id)', '`id`'])
            self.assertFalse(os.path.exists('/tmp/vret-shell-probe'))


if __name__ == '__main__':
    unittest.main()
