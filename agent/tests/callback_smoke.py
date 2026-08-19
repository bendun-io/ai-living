from __future__ import annotations

import http.server
import json
import os
import socket
import subprocess
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any


class CallbackCaptureHandler(http.server.BaseHTTPRequestHandler):
    received_payload: dict[str, Any] | None = None
    received_event = threading.Event()

    def do_POST(self) -> None:  # noqa: N802
        content_length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(content_length)
        payload = json.loads(raw_body.decode("utf-8"))
        type(self).received_payload = payload
        type(self).received_event.set()
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        return


def allocate_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def wait_for_http_json(url: str, timeout_seconds: float = 60.0) -> dict[str, Any]:
    deadline = time.time() + timeout_seconds
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=5) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            time.sleep(1)
    raise RuntimeError(f"Timed out waiting for {url}") from last_error


def post_json(url: str, payload: dict[str, Any], timeout_seconds: float = 10.0) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        return json.loads(response.read().decode("utf-8"))


def run_compose(project_dir: Path, env: dict[str, str], *args: str) -> None:
    command = ["docker", "compose", "-f", "docker-compose.yml", *args]
    subprocess.run(command, cwd=project_dir, env=env, check=True)


def main() -> int:
    project_dir = Path(__file__).resolve().parents[1]
    callback_port = allocate_port()
    callback_url = f"http://host.docker.internal:{callback_port}/callback"

    server = http.server.ThreadingHTTPServer(("127.0.0.1", callback_port), CallbackCaptureHandler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    env = os.environ.copy()
    env["CALLBACK_URL"] = callback_url
    env["ENABLE_MCP"] = "false"
    env.pop("OPENAI_API_KEY", None)
    env.setdefault("OPENAI_MODEL", "gpt-4.1-mini")

    try:
        run_compose(project_dir, env, "up", "-d", "--build")
        health = wait_for_http_json("http://127.0.0.1:8000/health")
        if health.get("status") != "ok":
            raise AssertionError(f"Unexpected health payload: {health}")

        response = post_json(
            "http://127.0.0.1:8000/agent/run",
            {
                "conversationId": "smoke-test-1",
                "user": "tester",
                "message": "echo hello",
                "attachments": [],
                "metadata": {"tenant": "local", "language": "en", "extra": {}},
            },
        )

        if response.get("conversationId") != "smoke-test-1":
            raise AssertionError(f"Unexpected agent response: {response}")

        if not CallbackCaptureHandler.received_event.wait(timeout=60):
            raise AssertionError("Timed out waiting for callback payload")

        payload = CallbackCaptureHandler.received_payload
        if not isinstance(payload, dict):
            raise AssertionError("Callback payload was not captured")

        expected_keys = {"conversationId", "result", "toolLog", "debug", "metadata"}
        missing_keys = expected_keys - set(payload)
        if missing_keys:
            raise AssertionError(f"Missing callback keys: {sorted(missing_keys)} in {payload}")

        if payload["conversationId"] != "smoke-test-1":
            raise AssertionError(f"Unexpected callback conversationId: {payload}")

        if not isinstance(payload["toolLog"], list):
            raise AssertionError(f"toolLog is not a list: {payload}")

        if not isinstance(payload["debug"], dict):
            raise AssertionError(f"debug is not a dict: {payload}")

        if not isinstance(payload["debug"].get("skillsRead", []), list):
            raise AssertionError(f"debug.skillsRead is not a list: {payload}")

        if not isinstance(payload["debug"].get("toolsUsed", []), list):
            raise AssertionError(f"debug.toolsUsed is not a list: {payload}")

        if not isinstance(payload["metadata"], dict):
            raise AssertionError(f"metadata is not a dict: {payload}")

        print(json.dumps({"agent": response, "callback": payload}, indent=2))
        return 0
    finally:
        run_compose(project_dir, env, "down", "--remove-orphans")
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    raise SystemExit(main())
