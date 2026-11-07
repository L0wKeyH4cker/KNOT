"""Loopback-only KNOT HTTP API and production asset server (stdlib)."""
from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
import os
from pathlib import Path
from urllib.parse import unquote, urlsplit

from backend.bundle import BundleError, build_bundle, reject_secrets
from backend.documents import DocumentError, extract_document
from backend.connections import credential_status, save_credential, test_connection, DEEPSEEK_CONNECTION
from backend.planner import PlanningError, hosted_planners, plan_workflow
from backend.template import load_template
from runtime.validation import validate_workflow
from runtime.security import redact

ROOT = Path(__file__).resolve().parent
MAX_BODY_BYTES = 4 * 1024 * 1024
MAX_DOCUMENT_BODY_BYTES = 8 * 1024 * 1024


def load_environment():
    """Read local developer env files without printing or replacing credentials."""
    for name in (".env.local", ".env"):
        path = ROOT / name
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            if key.replace("_", "").isalnum() and not key[0].isdigit():
                os.environ.setdefault(key, value.strip().strip('"').strip("'"))


def safe_error(message):
    return redact(str(message))[:2000]


class Handler(BaseHTTPRequestHandler):
    server_version = "KNOT/1.0"

    def log_message(self, format, *args):
        # Do not log URLs/bodies/credentials. Only method, status and timing belong in diagnostics.
        return

    def send_bytes(self, status, content, content_type, headers=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store" if self.path.startswith("/api/") else "no-cache")
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(content)

    def send_json(self, status, value):
        self.send_bytes(status, json.dumps(redact(value), ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/api/health":
            hosted = hosted_planners()
            if hosted is None:
                credentials = credential_status(ROOT)
                default = DEEPSEEK_CONNECTION if credentials.get("DEEPSEEK_API_KEY") else None
            else:
                # Public deployment: only report the allow-listed credentials and publish the pinned planner.
                credentials = {e["credential_ref"]: bool(os.environ.get(e["credential_ref"], "").strip()) for e in hosted}
                first = hosted[0] if hosted else None
                default = {"provider": first.get("provider", "openai"), "model": first.get("model", ""),
                           "credential_ref": first["credential_ref"], "base_url": first.get("base_url", "")} if first else None
            self.send_json(200, {"ok": True, "planner_credentials": credentials, "default_planner": default})
        elif path == "/api/template":
            self.send_json(200, load_template())
        elif path.startswith("/api/"):
            self.send_json(404, {"error": "接口不存在。"})
        else:
            self.serve_static(path)

    def serve_static(self, path):
        dist = (ROOT / "dist").resolve()
        target = (dist / unquote(path).lstrip("/")).resolve()
        if not target.is_relative_to(dist):
            self.send_json(403, {"error": "不允许访问项目文件。"})
            return
        if not target.is_file():
            target = dist / "index.html"
        if not target.is_file():
            self.send_json(404, {"error": "前端尚未构建。请运行 npm run dev，或先运行 npm run build。"})
            return
        content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        self.send_bytes(200, target.read_bytes(), content_type)

    def do_POST(self):
        origin = self.headers.get("Origin")
        if origin:
            try:
                parsed = urlsplit(origin)
                local = parsed.scheme == "http" and parsed.hostname in ("127.0.0.1", "localhost") and parsed.port in (5173, getattr(self.server, "server_port", None))
                # Hosted deployments (e.g. Vercel): accept only same-origin requests from the served editor.
                same_origin = parsed.scheme == "https" and parsed.netloc == self.headers.get("Host", "")
                allowed = local or same_origin
            except ValueError:
                allowed = False
            if not allowed:
                self.send_json(403, {"error": "只允许本地 KNOT 编辑器访问。"})
                return
        if self.headers.get("Content-Type", "").split(";", 1)[0].strip() != "application/json":
            self.send_json(415, {"error": "请发送 JSON 请求。"})
            return
        try:
            path = urlsplit(self.path).path
            body_limit = MAX_DOCUMENT_BODY_BYTES if path == "/api/requirements/extract" else MAX_BODY_BYTES
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= body_limit:
                self.send_json(413, {"error": f"请求为空或超过 {body_limit // (1024 * 1024)} MiB 限制。"})
                return
            body = json.loads(self.rfile.read(size).decode("utf-8"))
            if not isinstance(body, dict):
                raise ValueError("请求必须是 JSON 对象。")
            if path == "/api/credentials" and hosted_planners() is not None:
                self.send_json(403, {"error": "This hosted deployment does not accept API keys from the browser. Credentials are configured by the site owner."})
            elif path == "/api/credentials":
                self.send_json(200, {"credentials": save_credential(ROOT, body.get("credential_ref"), body.get("key"))})
            elif path == "/api/connection/test":
                self.send_json(200, test_connection(body.get("connection")))
            elif path in ("/api/validate", "/api/export"):
                workflow = body.get("workflow")
                if not isinstance(workflow, dict):
                    raise ValueError("缺少工作流对象。")
                reject_secrets(workflow)
                if path == "/api/validate":
                    mode = body.get("mode", "mock")
                    if mode not in ("mock", "real"):
                        raise ValueError("运行模式只能是 mock 或 real。")
                    self.send_json(200, {"issues": validate_workflow(workflow, mode=mode)})
                else:
                    self.send_bytes(200, build_bundle(workflow), "application/zip", {"Content-Disposition": 'attachment; filename="knot-workflow.zip"'})
            elif path == "/api/plan":
                workflow = plan_workflow(body.get("project"), body.get("resources", []), body.get("planner"))
                self.send_json(200, {"workflow": workflow})
            elif path == "/api/requirements/extract":
                document = extract_document(body.get("filename"), body.get("content_base64"))
                self.send_json(200, {"document": document})
            elif path == "/api/requirements/analyze":
                from backend.requirements import analyze_requirements
                analysis = analyze_requirements(body.get("document"), body.get("planner"))
                self.send_json(200, {"analysis": analysis})
            else:
                self.send_json(404, {"error": "接口不存在。"})
        except PlanningError as exc:
            self.send_json(exc.status, {"error": safe_error(exc), "issues": exc.issues})
        except DocumentError as exc:
            self.send_json(exc.status, {"error": safe_error(exc)})
        except BundleError as exc:
            self.send_json(400, {"error": safe_error(exc), "issues": exc.issues})
        except (ValueError, TypeError, KeyError, UnicodeError) as exc:
            self.send_json(400, {"error": safe_error(exc)})
        except (OSError, RuntimeError):
            self.send_json(500, {"error": "本地服务无法完成请求，请检查项目文件与运行环境。"})


def main():
    parser = argparse.ArgumentParser(description="KNOT local API and static server")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    load_environment()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"KNOT API: http://127.0.0.1:{args.port}", flush=True)
    print("Real planning uses local environment credentials. No key values are returned to the browser.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
