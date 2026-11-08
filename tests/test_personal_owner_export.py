"""Personal ZIPs contain only explicitly saved task-owner fixture keys."""
from copy import deepcopy
from email.message import Message
import http.client
import io
import json
import os
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

from backend.bundle import BundleError, build_bundle
from backend.connections import saved_member_credentials, save_credential
from backend.planner import PlanningError
from backend.template import load_owner_api_template
from server import Handler, ThreadingHTTPServer, credential_export_allowed

REF_A = "KNOT_DEMO_ALICE_API_KEY"
REF_B = "KNOT_DEMO_BOB_API_KEY"
KEY_A = "fixture-personal-alice-value"
KEY_B = "fixture-personal-bob-value"


def configured_workflow():
    workflow = load_owner_api_template()
    for member in workflow["project"]["members"]:
        member["connection"]["model"] = "fixture-" + member["id"]
    workflow["project"]["members"].append({"id": "reviewer", "name": "Reviewer", "skills": "",
        "connection": {"provider": "openai", "model": "fixture-reviewer", "credential_ref": "UNUSED_MEMBER_KEY"}})
    workflow["nodes"].append({"id": "review", "type": "human_review", "label": "Review", "position": {"x": 1100, "y": 400},
                              "config": {"owner_id": "reviewer", "instructions": "Check the result", "join_rule": "all_success"}})
    workflow["edges"] = [edge for edge in workflow["edges"] if edge["id"] != "control-join-output"]
    for source, target, kind in (("alice-join", "review", "control"), ("review", "output", "control"),
                                 ("alice-join", "review", "data")):
        workflow["edges"].append({"id": f"{kind}-{source}-{target}", "source": source, "target": target,
                                  "kind": kind, "source_port": "out" if kind == "control" else "data-out",
                                  "target_port": "in" if kind == "control" else "data-in"})
    return workflow


class PersonalOwnerExportTests(unittest.TestCase):
    def setUp(self):
        scratch = Path(__file__).resolve().parents[1] / ".test-tmp"
        scratch.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="personal-owner-export-", dir=scratch)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        environment = patch.dict(os.environ, {}, clear=True)
        environment.start()
        self.addCleanup(environment.stop)
        self.workflow = configured_workflow()

    def save_fixtures(self):
        for ref, value in ((REF_A, KEY_A), (REF_B, KEY_B), ("UNUSED_MEMBER_KEY", "fixture-unused-member-value"),
                           ("OPENAI_API_KEY", "fixture-agent-value"), ("PLANNER_API_KEY", "fixture-planner-value")):
            save_credential(self.root, ref, value)

    def test_only_saved_task_keys_are_selected_without_environment_fallback(self):
        self.save_fixtures()
        os.environ[REF_A] = "fixture-other-process-value"
        self.assertEqual(saved_member_credentials(self.root, self.workflow), {REF_A: KEY_A, REF_B: KEY_B})
        (self.root / ".env.local").unlink()
        (self.root / ".env").write_text(f"{REF_A}={KEY_A}\n{REF_B}={KEY_B}\n", encoding="utf-8")
        with self.assertRaises(PlanningError) as error:
            saved_member_credentials(self.root, self.workflow)
        self.assertEqual({i["node_id"] for i in error.exception.issues}, {"alice-write", "bob-write", "alice-join"})
        self.assertIn(REF_A, json.dumps(error.exception.issues))
        self.assertNotIn(KEY_A, str(error.exception))

    def test_saved_format_rejects_duplicate_quoted_crlf_or_injected_values(self):
        self.save_fixtures()
        for line in (f'{REF_A}="{KEY_A}"', f"{REF_A}={KEY_A}\r", f"{REF_A}={KEY_A}\n{REF_A}={KEY_A}",
                     f"{REF_A}=bad value", f" {REF_A}={KEY_A}"):
            with self.subTest(kind=line.split("=")[0]):
                (self.root / ".env.local").write_bytes((line + f"\n{REF_B}={KEY_B}\n").encode())
                with self.assertRaises(PlanningError):
                    saved_member_credentials(self.root, self.workflow)

    def test_unsafe_credential_path_is_rejected_without_reading_values(self):
        with patch("backend.connections.safe_path", side_effect=PermissionError("unsafe path")), \
                patch.object(Path, "read_bytes") as read:
            with self.assertRaises(PlanningError):
                saved_member_credentials(self.root, self.workflow)
        read.assert_not_called()

    def test_personal_bundle_contains_only_env_secrets_and_exact_routes(self):
        self.save_fixtures()
        keys = saved_member_credentials(self.root, self.workflow)
        with zipfile.ZipFile(io.BytesIO(build_bundle(self.workflow, {"backend": "opencode"}, member_credentials=keys))) as archive:
            self.assertEqual(json.loads(archive.read("workflow.json")), self.workflow)
            env = archive.read(".env").decode()
            self.assertIn(f"{REF_A}={KEY_A}\n", env)
            self.assertIn(f"{REF_B}={KEY_B}\n", env)
            self.assertNotIn("UNUSED_MEMBER_KEY", env)
            self.assertNotIn("PLANNER_API_KEY", env)
            self.assertNotIn("\nOPENAI_API_KEY=", env)
            self.assertNotIn("UNUSED_MEMBER_KEY", archive.read(".env.example").decode())
            for filename in archive.namelist():
                if filename != ".env":
                    self.assertNotIn(KEY_A.encode(), archive.read(filename), filename)
                    self.assertNotIn(KEY_B.encode(), archive.read(filename), filename)
                self.assertNotIn(b"fixture-planner-value", archive.read(filename), filename)
                self.assertNotIn(b"fixture-unused-member-value", archive.read(filename), filename)
            self.assertIn("no key re-entry is needed", archive.read("START-HERE.md").decode())
            self.assertIn("plaintext API keys", archive.read("README.md").decode())
            self.assertNotIn("Copy `.env.example` to `.env`", archive.read("START-HERE.md").decode())
            ignored = archive.read(".gitignore").decode().splitlines()
            self.assertIn(".env", ignored)
            self.assertIn(".env.*", ignored)
            self.assertIn("credentials.json", ignored)

    def test_public_bundle_still_never_contains_keys(self):
        self.save_fixtures()
        with zipfile.ZipFile(io.BytesIO(build_bundle(self.workflow, {"backend": "opencode"}))) as archive:
            self.assertNotIn(".env", archive.namelist())
            self.assertTrue(all(KEY_A.encode() not in archive.read(name) for name in archive.namelist()))
            self.assertIn("Copy `.env.example` to `.env`", archive.read("START-HERE.md").decode())

    def test_personal_bundle_rejects_extra_missing_malformed_keys_and_wrong_backend(self):
        for keys in ({REF_A: KEY_A}, {REF_A: KEY_A, REF_B: KEY_B, "EXTRA_KEY": "fixture-extra-value"},
                     {REF_A: KEY_A, REF_B: "line\nINJECTED_KEY=value"}, {REF_A: KEY_A, REF_B: 1}, []):
            with self.subTest(kind=type(keys).__name__), self.assertRaises(BundleError):
                build_bundle(self.workflow, {"backend": "opencode"}, member_credentials=keys)
        with self.assertRaises(BundleError):
            build_bundle(self.workflow, {"backend": "codex"}, member_credentials={REF_A: KEY_A, REF_B: KEY_B})
        contaminated = deepcopy(self.workflow)
        contaminated["project"]["goal"] += " fixture-only-supplied-opaque-key"
        with self.assertRaises(BundleError):
            build_bundle(contaminated, {"backend": "opencode"},
                         member_credentials={REF_A: "fixture-only-supplied-opaque-key", REF_B: KEY_B})

    def test_local_boundary_fails_closed_for_external_clients_bindings_and_forwarders(self):
        def request(**changes):
            headers = Message()
            headers["Host"] = "127.0.0.1:5173"
            headers["Origin"] = "http://127.0.0.1:5173"
            value = SimpleNamespace(headers=headers, client_address=("127.0.0.1", 40000),
                                    server=SimpleNamespace(server_address=("127.0.0.1", 8000), server_port=8000))
            for name, item in changes.items():
                setattr(value, name, item)
            return value
        self.assertTrue(credential_export_allowed(request()))
        for changed in (request(client_address=("192.0.2.20", 40000)), request(server=SimpleNamespace()),
                        request(server=SimpleNamespace(server_address=("0.0.0.0", 8000), server_port=8000))):
            self.assertFalse(credential_export_allowed(changed))
        for name, value in (("Host", "public.example"), ("Host", "127.0.0.1:bad"),
                            ("Origin", "https://127.0.0.1:5173"), ("X-Forwarded-For", "192.0.2.1")):
            item = request()
            if item.headers.get(name):
                item.headers.replace_header(name, value)
            else:
                item.headers[name] = value
            self.assertFalse(credential_export_allowed(item), name)
        item = request()
        item.headers["Host"] = "localhost"
        self.assertFalse(credential_export_allowed(item))
        for marker in ("KNOT_HOSTED_PLANNERS", "VERCEL", "RENDER_SERVICE_ID"):
            with patch.dict(os.environ, {marker: "[]" if marker == "KNOT_HOSTED_PLANNERS" else "1"}):
                self.assertFalse(credential_export_allowed(request()))


class PersonalOwnerExportHTTPTests(unittest.TestCase):
    save_fixtures = PersonalOwnerExportTests.save_fixtures

    def setUp(self):
        PersonalOwnerExportTests.setUp(self)
        root_patch = patch("server.ROOT", self.root)
        root_patch.start()
        self.addCleanup(root_patch.stop)
        self.http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_http)
        self.base = f"http://127.0.0.1:{self.http.server_port}"

    def stop_http(self):
        self.http.shutdown()
        self.http.server_close()
        self.thread.join(timeout=3)

    def post(self, body, headers=None):
        return self.request("POST", "/api/export", json.dumps(body).encode(),
                            {"Content-Type": "application/json", **(headers or {})})

    def request(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.http.server_port, timeout=5)
        try:
            connection.request(method, path, body, headers or {})
            response = connection.getresponse()
            return response.status, response.headers, response.read()
        finally:
            connection.close()

    def test_http_personal_export_is_no_store_and_health_reports_local_capability(self):
        self.save_fixtures()
        health = json.loads(self.request("GET", "/api/health")[2])
        self.assertIs(health["credential_export_allowed"], True)
        self.assertNotIn(KEY_A, json.dumps(health))
        status, headers, content = self.post({"workflow": self.workflow, "execution": {"backend": "opencode"},
                                              "include_member_credentials": True}, {"Origin": "http://127.0.0.1:5173", "Host": "127.0.0.1:5173"})
        self.assertEqual(status, 200, content[:300])
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertIn("knot-personal-workspace.zip", headers["Content-Disposition"])
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            self.assertIn(KEY_A.encode(), archive.read(".env"))

    def test_http_default_is_public_and_strict_flag_errors_before_read(self):
        body = {"workflow": self.workflow, "execution": {"backend": "opencode"}}
        with patch("server.saved_member_credentials") as read:
            status, headers, content = self.post(body)
            self.assertEqual(status, 200)
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                self.assertNotIn(".env", archive.namelist())
            for value in ("true", 1, None, [], {}):
                status, _, _ = self.post({**body, "include_member_credentials": value})
                self.assertEqual(status, 400)
            read.assert_not_called()

    def test_http_hosted_external_and_non_opencode_exports_never_read_saved_keys(self):
        body = {"workflow": self.workflow, "execution": {"backend": "opencode"}, "include_member_credentials": True}
        with patch("server.saved_member_credentials") as read:
            for headers in ({"Host": "public.example"}, {"X-Forwarded-Host": "public.example"},
                            {"Origin": "https://public.example", "Host": "public.example"}):
                self.assertEqual(self.post(body, headers)[0], 403)
            for environment in ({"KNOT_HOSTED_PLANNERS": "[]"}, {"VERCEL": "1"}):
                with patch.dict(os.environ, environment):
                    self.assertEqual(self.post(body)[0], 403)
                    health = json.loads(self.request("GET", "/api/health")[2])
                    self.assertIs(health["credential_export_allowed"], False)
            self.assertEqual(self.post({**body, "execution": {"backend": "codex"}})[0], 400)
            read.assert_not_called()


if __name__ == "__main__":
    unittest.main()
