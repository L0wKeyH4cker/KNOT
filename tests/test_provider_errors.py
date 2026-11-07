"""Provider diagnostics use local fixtures only; no account key or external API."""
from __future__ import annotations

import io
import json
import os
import socket
import ssl
import threading
import time
import unittest
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import Mock, patch

from backend.planner import PlanningError, plan_workflow
from backend.template import load_template
from runtime.providers import ProviderError, _post


class ProviderDiagnosticTests(unittest.TestCase):
    def http_failure(self, status, payload):
        raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        failure = urllib.error.HTTPError("https://fixture.invalid/v1/chat/completions", status, "private reason", {}, io.BytesIO(raw))
        opener = Mock()
        opener.open.side_effect = failure
        with patch("runtime.providers.urllib.request.build_opener", return_value=opener):
            with self.assertRaises(ProviderError) as raised:
                _post("https://fixture.invalid/v1/chat/completions", {}, {}, 2)
        return raised.exception

    def test_429_quota_and_rate_limit_are_distinct(self):
        quota = self.http_failure(429, {"error": {"code": "insufficient_quota", "message": "PRIVATE BODY"}})
        rate = self.http_failure(429, {"error": {"code": "rate_limit_exceeded"}})
        self.assertEqual(quota.category, "quota")
        self.assertEqual(rate.category, "rate_limit")
        self.assertIn("quota", quota.user_message())
        self.assertIn("rate", rate.user_message())
        self.assertIn("HTTP 429", quota.user_message())
        self.assertNotIn("PRIVATE BODY", str(quota) + quota.user_message())

    def test_auth_model_and_permissions_have_actionable_status(self):
        for status, code, category in ((401, "invalid_api_key", "authentication"), (403, "permission_denied", "permission"), (404, "model_not_found", "model"), (500, "server_error", "server")):
            with self.subTest(status=status):
                error = self.http_failure(status, {"error": {"code": code}})
                self.assertEqual(error.http_status, status)
                self.assertEqual(error.error_code, code)
                self.assertEqual(error.category, category)
                self.assertIn(f"HTTP {status}", error.user_message())
        self.assertIn("API model ID", self.http_failure(404, {}).user_message())

    def test_anthropic_error_type_is_allowlisted(self):
        error = self.http_failure(429, {"type": "error", "error": {"type": "rate_limit_error", "message": "private"}})
        self.assertEqual(error.error_type, "rate_limit_error")
        self.assertEqual(error.category, "rate_limit")

    def test_arbitrary_codes_and_secret_bodies_are_never_exposed(self):
        secret = "user-secret-value-without-standard-prefix"
        error = self.http_failure(400, {"error": {"code": secret, "type": "sk-proj-TESTONLY00000000000000000000", "message": secret, "param": secret}})
        self.assertIsNone(error.error_code)
        self.assertIsNone(error.error_type)
        self.assertNotIn(secret, str(error) + error.user_message())
        self.assertNotIn("sk-proj-", str(error) + error.user_message())

    def test_malformed_or_large_error_body_keeps_status_without_guessing_429(self):
        for body in (b"<html>private error</html>", b"X" * 70_000, {"error": {"code": [], "type": {}}}):
            with self.subTest(body_type=type(body).__name__):
                error = self.http_failure(429, body)
                self.assertEqual(error.http_status, 429)
                self.assertEqual(error.category, "unknown_rate_limit")
                self.assertIsNone(error.error_code)

    def test_transport_failures_are_distinct_from_api_rejections(self):
        cases = ((socket.gaierror(-2, "private hostname"), "dns"), (ssl.SSLCertVerificationError("private hostname"), "tls"), (TimeoutError("private request"), "timeout"), (ConnectionResetError("private connection"), "network"))
        for reason, category in cases:
            with self.subTest(category=category):
                opener = Mock()
                opener.open.side_effect = urllib.error.URLError(reason)
                with patch("runtime.providers.urllib.request.build_opener", return_value=opener), self.assertRaises(ProviderError) as raised:
                    _post("https://fixture.invalid/v1/chat/completions", {}, {}, 2)
                error = raised.exception
                self.assertEqual(error.category, category)
                self.assertIsNone(error.http_status)
                self.assertNotIn("private", str(error) + error.user_message())

    def test_planner_preserves_safe_reason_and_never_retries_provider_failure(self):
        workflow = load_template()
        provider_error = ProviderError("untrusted private exception body", http_status=404, error_code="model_not_found")
        call = Mock(side_effect=provider_error)
        with patch.dict(os.environ, {"KNOT_DIAGNOSTIC_KEY": "fixture-key-no-live-request"}):
            with self.assertRaises(PlanningError) as raised:
                plan_workflow(workflow["project"], workflow["resources"], {"provider": "openai", "model": "user-entered-model", "credential_ref": "KNOT_DIAGNOSTIC_KEY"}, model_call=call)
        message = str(raised.exception)
        self.assertIn("HTTP 404", message)
        self.assertIn("model_not_found", message)
        self.assertIn("API model ID", message)
        self.assertIn("没有退回 mock", message)
        self.assertNotIn("untrusted private", message)
        self.assertEqual(call.call_count, 1)
        self.assertEqual(raised.exception.status, 502)

    def test_unstructured_provider_exception_never_reveals_message(self):
        workflow = load_template()
        with patch.dict(os.environ, {"KNOT_DIAGNOSTIC_KEY": "fixture-key-no-live-request"}), self.assertRaises(PlanningError) as raised:
            plan_workflow(workflow["project"], [], {"provider": "openai", "model": "fixture", "credential_ref": "KNOT_DIAGNOSTIC_KEY"}, model_call=Mock(side_effect=RuntimeError("private provider response")))
        self.assertNotIn("private provider response", str(raised.exception))


class ErrorBodyDeadlineTests(unittest.TestCase):
    def test_slow_http_error_body_cannot_extend_request_deadline(self):
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_POST(self):
                self.rfile.read(int(self.headers["Content-Length"]))
                self.send_response(429)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                try:
                    for _ in range(30):
                        self.wfile.write(b" ")
                        self.wfile.flush()
                        time.sleep(0.08)
                except (ConnectionError, OSError):
                    pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            started = time.monotonic()
            with self.assertRaises(ProviderError) as raised:
                _post(f"http://127.0.0.1:{server.server_port}/v1/chat/completions", {}, {}, 0.3)
            self.assertLess(time.monotonic() - started, 1.5)
            self.assertEqual(raised.exception.http_status, 429)
            self.assertEqual(raised.exception.category, "unknown_rate_limit")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
