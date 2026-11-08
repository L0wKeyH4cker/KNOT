"""Launcher acceptance: one local backend, explicit reviews, no silent mock fallback."""
from __future__ import annotations

import contextlib
import io
import json
import os
from pathlib import Path
import signal
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import run
from backend.template import load_template
from runtime.engine import Engine
from runtime.local_config import DEFAULT_EXECUTION, load_execution, save_execution, validate_execution


class LocalLauncherTests(unittest.TestCase):
    def setUp(self):
        scratch = Path(__file__).resolve().parents[1] / '.test-tmp'
        scratch.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='local-launcher-', dir=scratch)
        self.root = Path(self.temp.name)
        environment = patch.dict(os.environ, {'KNOT_RUNS_DIR': str(self.root / '.test-registry')})
        environment.start()
        self.addCleanup(environment.stop)
        self.workflow = load_template()
        for agent in self.workflow['agents']:
            agent['model'] = ''
        for resource in self.workflow['resources']:
            if 'content' in resource:
                target = self.root / resource['path']
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(resource['content'], encoding='utf-8')
        (self.root / 'workflow.json').write_text(json.dumps(self.workflow), encoding='utf-8')

    def tearDown(self):
        self.temp.cleanup()

    def launch(self, *arguments, answers=()):
        output, errors = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors), patch('sys.stdin.isatty', return_value=False):
            with patch('builtins.input', side_effect=list(answers)) as prompt:
                code = run.main(['--root', str(self.root), *arguments])
        return code, output.getvalue(), errors.getvalue(), prompt

    def test_default_without_choice_fails_instead_of_running_mock(self):
        code, out, err, prompt = self.launch()
        self.assertEqual(code, 1)
        self.assertIn('--backend codex', err)
        self.assertFalse((self.root / 'logs').exists())
        self.assertFalse((self.root / 'knot.json').exists())
        prompt.assert_not_called()

    def test_configure_saves_one_backend_and_shared_optional_model_without_running(self):
        with patch('run.Engine') as engine, patch('run.check_backend') as backend:
            code, out, err, _ = self.launch('--configure', '--backend', 'claude', '--model', 'sonnet')
        self.assertEqual(code, 0, err)
        self.assertEqual(load_execution(self.root), {**DEFAULT_EXECUTION, 'backend': 'claude', 'model': 'sonnet'})
        self.assertIn('every Agent', out)
        self.assertFalse((self.root / 'logs').exists())
        engine.assert_not_called()
        backend.assert_not_called()

    def test_interactive_setup_asks_once_and_keeps_existing_choice(self):
        code, _, err, prompt = self.launch('--interactive', '--configure', answers=['2'])
        self.assertEqual(code, 0, err)
        self.assertEqual(prompt.call_count, 1)
        self.assertEqual(load_execution(self.root)['backend'], 'claude')
        with patch('run.check_backend', return_value={'available': True, 'version': 'fixture'}) as backend:
            code, out, err, prompt = self.launch('--validate')
        self.assertEqual(code, 0, out + err)
        prompt.assert_not_called()
        backend.assert_called_once_with('claude')
        self.assertEqual(json.loads(out)['mode'], 'local')
        self.assertFalse((self.root / 'logs').exists())

    def test_validate_local_accepts_blank_agent_models_and_writes_nothing(self):
        with patch('run.check_backend', return_value={'available': True, 'version': 'fixture'}):
            code, out, err, prompt = self.launch('--backend', 'codex', '--validate')
        self.assertEqual(code, 0, out + err)
        payload = json.loads(out)
        self.assertEqual(payload['execution']['backend'], 'codex')
        self.assertFalse(any(issue['code'] in ('model', 'credential_missing') for issue in payload['issues']))
        self.assertFalse((self.root / 'knot.json').exists())
        self.assertFalse((self.root / 'logs').exists())
        self.assertFalse((self.root / '.knot').exists())
        prompt.assert_not_called()

    def test_validate_missing_cli_is_actionable_and_does_not_fallback(self):
        with patch('run.check_backend', return_value={'available': False, 'message': 'Install Claude Code locally.'}):
            code, out, err, _ = self.launch('--backend', 'claude', '--validate')
        self.assertEqual(code, 1, err)
        self.assertIn('Install Claude Code locally.', out)
        self.assertFalse((self.root / 'results').exists())
        self.assertFalse((self.root / 'logs').exists())

    def test_missing_cli_keeps_selection_but_does_not_start_a_failed_run(self):
        with patch('run.check_backend', return_value={'available': False, 'message': 'Install Claude Code locally.'}):
            code, out, err, _ = self.launch('--backend', 'claude')
        self.assertEqual(code, 1, out + err)
        self.assertIn('Install Claude Code locally.', err)
        self.assertEqual(load_execution(self.root)['backend'], 'claude')
        self.assertFalse((self.root / 'logs').exists())
        self.assertFalse((self.root / '.knot').exists())

    def test_interactive_eof_does_not_select_an_assistant(self):
        with patch('builtins.input', side_effect=EOFError), patch('sys.stdin.isatty', return_value=False), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            code = run.main(['--root', str(self.root), '--interactive'])
        self.assertEqual(code, 1)
        self.assertFalse((self.root / 'knot.json').exists())

    def test_existing_review_never_approves_on_enter_and_can_be_resumed(self):
        code, out, err, _ = self.launch('--mode', 'mock')
        self.assertEqual(code, 2, out + err)
        before = (self.root / 'logs/run-state.json').read_bytes()
        code, out, err, prompt = self.launch('--mode', 'mock', '--interactive', answers=[''])
        self.assertEqual(code, 2, out + err)
        self.assertEqual(prompt.call_count, 1)
        self.assertEqual(before, (self.root / 'logs/run-state.json').read_bytes())
        self.assertFalse((self.root / 'results/report.md').exists())
        code, out, err, _ = self.launch('--mode', 'mock', '--interactive', answers=['approve'])
        self.assertEqual(code, 0, out + err)
        state = json.loads((self.root / 'logs/run-state.json').read_text(encoding='utf-8'))
        self.assertEqual(state['nodes']['review']['decision'], 'approve')
        self.assertEqual(state['nodes']['review']['reviewer_id'], 'member-3')
        self.assertTrue((self.root / 'results/report.md').is_file())
        finished = (self.root / 'logs/run-state.json').read_bytes()
        code, out, err, prompt = self.launch('--mode', 'mock', '--interactive')
        self.assertEqual(code, 0, out + err)
        self.assertIn('already completed', out)
        prompt.assert_not_called()
        self.assertEqual(finished, (self.root / 'logs/run-state.json').read_bytes())

    def test_rejection_blocks_output_and_records_configured_owner(self):
        code, out, err, _ = self.launch('--mode', 'mock', '--interactive', answers=['reject'])
        self.assertEqual(code, 1, out + err)
        state = json.loads((self.root / 'logs/run-state.json').read_text(encoding='utf-8'))
        self.assertEqual(state['nodes']['review']['decision'], 'reject')
        self.assertEqual(state['nodes']['review']['reviewer_id'], 'member-3')
        self.assertFalse((self.root / 'results/report.md').exists())

    def test_review_eof_preserves_waiting_state(self):
        state = {'nodes': {'review': {'status': 'waiting_review', 'owner_id': 'member', 'instructions': 'Check it', 'input_nodes': []}}}
        with patch('builtins.input', side_effect=EOFError), contextlib.redirect_stdout(io.StringIO()):
            self.assertIsNone(run.ask_review(state, self.root))
        self.assertEqual(state['nodes']['review']['status'], 'waiting_review')

    def test_review_shows_actual_indexed_workspace(self):
        folder = self.root / '.knot/tasks/task-003-work/work'
        folder.mkdir(parents=True)
        state = {'nodes': {'review': {'status': 'waiting_review', 'owner_id': 'member', 'instructions': 'Check it', 'input_nodes': ['work']}}, 'results': {'work': {'content': 'Code and tests ready', 'workspace': '.knot/tasks/task-003-work/work'}}}
        output = io.StringIO()
        with patch('builtins.input', return_value='later'), contextlib.redirect_stdout(output):
            self.assertIsNone(run.ask_review(state, self.root))
        self.assertIn(str(folder), output.getvalue())

    def test_local_run_uses_one_persisted_backend_for_every_task(self):
        save_execution(self.root, {**DEFAULT_EXECUTION, 'backend': 'codex', 'model': 'one-model'})
        calls = []
        def fake_task(backend, model, cwd, prompt, timeout, **kwargs):
            calls.append((backend, model, cwd))
            return {'content': 'Executed fixture task', 'data': [{'value': 1}], 'checks': ['fixture check']}
        with patch('runtime.coding.run_coding_task', side_effect=fake_task), patch('runtime.coding.check_backend', return_value={'available': True}):
            code, out, err, prompt = self.launch('--interactive', answers=['approve'])
        self.assertEqual(code, 0, out + err)
        self.assertGreaterEqual(len(calls), 3)
        self.assertEqual({(backend, model) for backend, model, _ in calls}, {('codex', 'one-model')})
        self.assertEqual(len({str(cwd) for _, _, cwd in calls}), len(calls))
        self.assertEqual(prompt.call_count, 1, 'Saved backend must not prompt again; only human review should prompt')

    def test_hiding_or_unavailable_dashboard_waits_for_worker_to_complete(self):
        for display_result in ('closed', 'plain', OSError('Terminal unavailable')):
            with self.subTest(display_result=str(display_result)):
                started, release, finished = threading.Event(), threading.Event(), threading.Event()
                state = {'run_id': 'embedded-fixture', 'status': 'completed', 'nodes': {}}
                engine = SimpleNamespace(root=self.root, state_path=self.root / 'logs/run-state.json', state=state, quiet=False)
                worker_ids = []

                def execute():
                    worker_ids.append(threading.get_ident())
                    started.set()
                    if not release.wait(3):
                        raise RuntimeError('The monitor test never released the worker')
                    finished.set()
                    return state

                engine.run = execute

                def watch(snapshot, *, stop_event, embedded, splash):
                    self.assertTrue(embedded)
                    self.assertFalse(splash)
                    self.assertTrue(started.wait(2))
                    self.assertFalse(stop_event.is_set())
                    self.assertFalse(finished.is_set())
                    self.assertTrue(engine.quiet)
                    # The monitor returns while the worker is still doing work.
                    release_timer = threading.Timer(0.05, release.set)
                    release_timer.start()
                    if isinstance(display_result, Exception):
                        raise display_result
                    return display_result

                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()), \
                        patch('sys.stdin.isatty', return_value=True), patch('sys.stdout.isatty', return_value=True), \
                        patch('runtime.monitor.watch', side_effect=watch), patch('runtime.coding.cancel_all') as cancel:
                    result = run.run_engine(engine, 'local', splash=False)
                self.assertIs(result, state)
                self.assertTrue(finished.is_set())
                self.assertEqual(len(worker_ids), 1, 'Closing the dashboard must not restart the workflow')
                self.assertNotEqual(worker_ids[0], threading.get_ident())
                self.assertFalse(engine.quiet)
                cancel.assert_not_called()

    def test_dashboard_finishes_at_review_and_existing_review_stays_unchanged(self):
        engine = Engine(self.workflow, self.root, mode='mock')

        def watch(snapshot, *, stop_event, embedded, splash):
            self.assertTrue(embedded)
            self.assertTrue(splash)
            self.assertTrue(stop_event.wait(5), 'Mock workflow did not reach its review gate')
            self.assertEqual(snapshot()[0]['status'], 'waiting_review')
            return 'finished'

        with contextlib.redirect_stdout(io.StringIO()), patch('sys.stdin.isatty', return_value=True), \
                patch('sys.stdout.isatty', return_value=True), patch('runtime.monitor.watch', side_effect=watch):
            state = run.run_engine(engine, 'mock', tui=True)
        self.assertEqual(state['status'], 'waiting_review')
        self.assertEqual(state['nodes']['review']['status'], 'waiting_review')
        self.assertFalse((self.root / 'results/report.md').exists())
        before = engine.state_path.read_bytes()
        with patch.object(Engine, 'run', side_effect=AssertionError('A saved review must not execute again')), \
                patch('runtime.monitor.watch') as monitor:
            code, out, err, _ = self.launch('--mode', 'mock', '--interactive', '--tui', answers=['later'])
        self.assertEqual(code, 2, out + err)
        monitor.assert_not_called()
        self.assertEqual(engine.state_path.read_bytes(), before)


class LocalConfigTests(unittest.TestCase):
    def test_default_is_unselected_not_mock(self):
        self.assertEqual(validate_execution({}, allow_unselected=True), DEFAULT_EXECUTION)
        with self.assertRaises(ValueError):
            validate_execution({})

    def test_rejects_commands_credentials_paths_and_invalid_timeouts(self):
        base = {'backend': 'codex'}
        invalid = [
            {'command': 'anything'}, {'api_key': 'never-store-credentials'},
            {'backend': 'mock'}, {'backend': []}, {'schema_version': '2'},
            {'model': '--dangerously-bypass-approvals-and-sandbox'},
            {'model': 'C:/Users/person/model'}, {'model': '/tmp/model'},
            {'model': 'models/../secret'}, {'model': 'model\ncommand'},
            {'model': 'two words'}, {'model': 'sk-' + 'x' * 24},
            {'task_timeout_seconds': True}, {'task_timeout_seconds': 0},
            {'task_timeout_seconds': 86401}, {'task_timeout_seconds': 1.5},
        ]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_execution({**base, **value})

    def test_valid_shared_model_and_timeout(self):
        result = validate_execution({'backend': 'claude', 'model': 'provider/model-v1', 'task_timeout_seconds': 3600})
        self.assertEqual(result['schema_version'], '1.0')
        self.assertEqual(result['model'], 'provider/model-v1')
        self.assertEqual(validate_execution({'backend': 'codex'})['model'], '')


if __name__ == '__main__':
    unittest.main()
