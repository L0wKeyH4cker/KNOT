"""Black-box monitoring of independently extracted runner packages."""
from __future__ import annotations

import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
import zipfile

from backend.bundle import build_bundle
from backend.template import load_template


class TerminalClientTests(unittest.TestCase):
    def setUp(self):
        scratch = Path(__file__).resolve().parents[1] / '.test-tmp'
        scratch.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='terminal-client-', dir=scratch)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.environment = {**os.environ, 'KNOT_RUNS_DIR': str(self.root / 'registry'), 'PYTHONIOENCODING': 'utf-8'}
        self.environment.pop('PYTHONPATH', None)

    def unpack(self, name='monitor test', delay=10):
        workflow = load_template()
        workflow['project']['name'] = name
        for node in workflow['nodes']:
            if node['type'] == 'agent_task':
                node['config']['mock_delay_ms'] = delay
        folder = self.root / name
        folder.mkdir()
        with zipfile.ZipFile(io.BytesIO(build_bundle(workflow))) as archive:
            for member in ('knot.py', 'knot.cmd', 'knot.sh', 'runtime/monitor.py', 'runtime/registry.py', 'runtime/activity.py', 'runtime/terminal_brand.py'):
                self.assertIn(member, archive.namelist())
            archive.extractall(folder)
        return folder

    def cli(self, folder, *args):
        return subprocess.run([sys.executable, 'knot.py', *args], cwd=folder, env=self.environment,
                              capture_output=True, text=True, encoding='utf-8', timeout=30)

    def test_exported_client_run_and_read_only_review_snapshot(self):
        folder = self.unpack()
        ran = self.cli(folder, 'run', '--mode', 'mock', '--plain', '--no-splash')
        self.assertEqual(ran.returncode, 2, ran.stdout + ran.stderr)
        paths = [folder / name for name in ('workflow.json', 'knot.json', 'logs/run-state.json', 'logs/run-state.progress.json', 'logs/events.jsonl')]
        before = {str(path): path.read_bytes() for path in paths}
        snapshot = self.cli(folder, 'status', '--json')
        self.assertEqual(snapshot.returncode, 0, snapshot.stderr)
        self.assertNotIn('\x1b', snapshot.stdout)
        runs = json.loads(snapshot.stdout)
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]['display_status'], 'waiting_review')
        self.assertEqual(runs[0]['nodes']['research']['status'], 'succeeded')
        self.assertNotIn('results', runs[0])
        self.assertFalse((folder / 'results/report.md').exists())
        self.assertEqual(before, {str(path): path.read_bytes() for path in paths})
        display = self.cli(folder, 'monitor', '--once', '--no-splash')
        self.assertEqual(display.returncode, 0, display.stderr)
        self.assertNotIn('\x1b', display.stdout)
        self.assertIn('REVIEW', display.stdout)
        self.assertIn('mock', display.stdout)

    def test_noninteractive_output_has_no_splash_or_terminal_controls(self):
        folder = self.unpack()
        # Default branding must not depend on users opting out for pipes/scripts.
        for arguments in (('status',), ('monitor', '--once'), ('monitor',)):
            with self.subTest(arguments=arguments):
                observed = self.cli(folder, *arguments)
                self.assertEqual(observed.returncode, 0, observed.stderr)
                self.assertTrue(observed.stdout.startswith('KNOT'), observed.stdout)
                self.assertNotIn('\x1b', observed.stdout)
                self.assertIn('No local workflows found', observed.stdout)
        for arguments in (('status', '--json'), ('monitor', '--json'), ('monitor', '--json', '--no-splash')):
            with self.subTest(arguments=arguments):
                observed = self.cli(folder, *arguments)
                self.assertEqual(observed.returncode, 0, observed.stderr)
                self.assertEqual(json.loads(observed.stdout), [])
                self.assertNotIn('\x1b', observed.stdout)
        self.assertFalse((folder / 'logs/run-state.json').exists())
        self.assertFalse((self.root / 'registry').exists())

    def test_empty_monitor_does_not_start_agents_or_create_registration(self):
        folder = self.unpack()
        observed = self.cli(folder)
        self.assertEqual(observed.returncode, 0, observed.stderr)
        self.assertIn('No local workflows found', observed.stdout)
        self.assertFalse((folder / 'logs/run-state.json').exists())
        self.assertFalse((self.root / 'registry').exists())
        self.assertFalse((folder / '.env').exists())

    def test_explicit_root_reads_legacy_unregistered_state(self):
        observer = self.unpack('observer')
        old = self.root / 'old project'
        (old / 'logs').mkdir(parents=True)
        workflow = load_template()
        (old / 'workflow.json').write_text(json.dumps(workflow), encoding='utf-8')
        state = {'run_id': 'legacy', 'status': 'running', 'mode': 'local', 'nodes': {'research': {'status': 'running'}}, 'events': []}
        (old / 'logs/run-state.json').write_text(json.dumps(state), encoding='utf-8')
        observed = self.cli(observer, 'status', '--root', str(old), '--json')
        self.assertEqual(observed.returncode, 0, observed.stderr)
        runs = json.loads(observed.stdout)
        self.assertEqual(runs[0]['display_status'], 'disconnected')
        self.assertEqual(runs[0]['nodes']['research']['type'], 'agent_task')
        self.assertFalse((old / 'logs/run-state.progress.json').exists())

    def test_two_running_packages_are_discovered_without_explicit_roots(self):
        folders = [self.unpack('Project A', 1200), self.unpack('Project B', 1200)]
        processes = [subprocess.Popen([sys.executable, 'knot.py', 'run', '--mode', 'mock', '--plain'],
                                     cwd=folder, env=self.environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                     text=True, encoding='utf-8') for folder in folders]
        try:
            deadline = time.monotonic() + 15
            runs = []
            while time.monotonic() < deadline:
                observed = self.cli(folders[0], 'status', '--json')
                self.assertEqual(observed.returncode, 0, observed.stderr)
                runs = json.loads(observed.stdout)
                if len(runs) == 2 and all(run['live'] and run['nodes']['research']['status'] == 'running' for run in runs):
                    break
                time.sleep(0.03)
            else:
                self.fail('Both live workflows were not discovered: ' + json.dumps(runs))
            self.assertEqual({run['project']['name'] for run in runs}, {'Project A', 'Project B'})
            self.assertTrue(all(process.poll() is None for process in processes), 'Reading progress stopped a workflow')
            for process in processes:
                out, err = process.communicate(timeout=20)
                self.assertEqual(process.returncode, 2, out + err)
            finished = json.loads(self.cli(folders[0], 'status', '--json').stdout)
            self.assertTrue(all(run['display_status'] == 'waiting_review' and not run['live'] for run in finished))
        finally:
            for process in processes:
                if process.poll() is None:
                    process.kill()
                process.communicate(timeout=5)

    @unittest.skipUnless(os.name == 'nt', 'Windows command launcher')
    def test_windows_monitor_shortcut_uses_python_without_setup_writes(self):
        folder = self.unpack()
        result = subprocess.run(['cmd.exe', '/d', '/c', 'knot.cmd', 'status', '--json'], cwd=folder,
                                env=self.environment, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout), [])
        self.assertFalse((folder / '.env').exists())
        self.assertFalse((folder / '.venv').exists())


if __name__ == '__main__':
    unittest.main()
