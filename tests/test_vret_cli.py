"""Release test suite for the packaged VRET CLI.

Adapted from the authoritative 9-test contract of the working CLI
(``test_vret_cli.py`` in the source tree). The CLI under test is
``vret_cli/cli.py`` and the checkpoint is the packaged
``vret_cli/checkpoint`` tree, so these tests exercise exactly what a wheel
installation ships.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

CLI=Path(__file__).resolve().parent.parent / 'vret_cli' / 'cli.py'
ROOT=str(Path(__file__).resolve().parent.parent / 'vret_cli' / 'checkpoint')
class CLITests(unittest.TestCase):
    def call(self,*args,root=ROOT):
        return subprocess.run([sys.executable,'-B',str(CLI),*args],env={**os.environ,'VRET_ROOT':root,'PYTHONDONTWRITEBYTECODE':'1'},capture_output=True,text=True)
    def test_version(self):
        p=self.call('--version');self.assertEqual(p.returncode,0,p.stderr)
        self.assertEqual(p.stdout.strip(),'VRET 0.2.0 policy=PIPELINED_POLICY_V1')
    def test_status_from_receipts(self):
        p=self.call('status');self.assertEqual(p.returncode,0,p.stderr)
        self.assertIn('VRET checkpoint: VERIFIED',p.stdout)
        self.assertIn('13.960M candidates/s',p.stdout)
        self.assertIn('500/500',p.stdout)
    def test_root_override(self):
        with tempfile.TemporaryDirectory() as d:
            p=self.call('root',root=d);self.assertEqual(p.returncode,0,p.stderr);self.assertEqual(p.stdout.strip(),d)
    def test_missing_required_doctor_fails(self):
        with tempfile.TemporaryDirectory() as d:
            p=self.call('doctor',root=d);self.assertNotEqual(p.returncode,0);self.assertIn('FAIL',p.stdout)
    def test_run_preserves_exit_args_and_cwd(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d,'probe.py').write_text('import sys,os,json; print(json.dumps([os.getcwd(),sys.argv[1:]])); sys.exit(17)')
            p=self.call('run','probe.py','--literal','a b','; echo BAD',root=d)
            self.assertEqual(p.returncode,17,p.stderr)
            self.assertEqual(json.loads(p.stdout),[d,['--literal','a b','; echo BAD']])
    def test_run_rejects_escape_and_symlink(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d,'root');root.mkdir();outside=Path(d,'outside.py');outside.write_text('print("LEAK")')
            (root/'link.py').symlink_to(outside)
            for target in ['../outside.py','link.py',str(outside),'missing.py']:
                with self.subTest(target=target):
                    p=self.call('run',target,root=str(root));self.assertNotEqual(p.returncode,0)
                    self.assertNotIn('LEAK',p.stdout)
    def doctor_mocked(self, import_returncode):
        import contextlib
        import importlib.util
        import io
        from unittest.mock import patch
        spec=importlib.util.spec_from_file_location('vret_under_test',CLI)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        imports=subprocess.CompletedProcess([],import_returncode,'','mock missing dependency' if import_returncode else '')
        output=io.StringIO()
        with patch.object(module.shutil,'which',return_value=None), \
             patch.object(module.ctypes,'CDLL',side_effect=OSError('CPU-only test')), \
             patch.object(module.subprocess,'run',return_value=imports), \
             contextlib.redirect_stdout(output):
            result=module.doctor(Path(ROOT))
        return result,output.getvalue()
    def test_cpu_only_doctor_warns_not_fails(self):
        result,output=self.doctor_mocked(0)
        self.assertEqual(result,0,output);self.assertIn('WARN',output);self.assertNotIn('FAIL',output)
    def test_required_python_import_failure_is_fatal(self):
        result,output=self.doctor_mocked(1)
        self.assertEqual(result,1,output);self.assertIn('FAIL toolkit Python imports',output)
    def test_metadata_commands(self):
        for args in [('info',),('report',),('report','--cat'),('receipts',),('receipts','--list')]:
            with self.subTest(args=args):
                p=self.call(*args);self.assertEqual(p.returncode,0,p.stderr);self.assertTrue(p.stdout.strip())

if __name__=='__main__':unittest.main()
