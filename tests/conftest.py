from __future__ import annotations

import http.server
import json
import threading
from collections.abc import Iterator
from typing import Any, cast

import pytest
from legal_rag_verifier.judge import PRESETS as LIBRARY_PRESETS


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class JudgeStub:
    def __init__(self) -> None:
        self.models = [
            LIBRARY_PRESETS["qwen27-ar4"].model,
            "google/gemma-4-E4B-it",
            "Qwen/Qwen3.8-27B-FP8",
            "custom-model",
        ]
        self.script: list[str | int] = []
        self.requests: list[dict[str, Any]] = []
        self._lock = threading.Lock()
        self._server = _JudgeStubServer(("127.0.0.1", 0), _JudgeStubHandler)
        self._server.stub = self
        self.url = f"http://127.0.0.1:{self._server.server_port}"
        self._thread = threading.Thread(
            target=self._server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True
        )
        self._thread.start()

    def record(self, method: str, path: str, headers: dict[str, str], body: Any) -> str | int:
        with self._lock:
            self.requests.append({"method": method, "path": path, "headers": headers, "json": body})
            if method == "POST":
                return self.script.pop(0) if self.script else "supported"
            return "supported"

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join()


class _JudgeStubServer(http.server.ThreadingHTTPServer):
    stub: JudgeStub

    def handle_error(self, request: Any, client_address: Any) -> None:
        return


class _JudgeStubHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        stub = cast(_JudgeStubServer, self.server).stub
        headers = {name.lower(): value for name, value in self.headers.items()}
        stub.record("GET", self.path, headers, {})
        if self.path == "/v1/models":
            body = {
                "object": "list",
                "data": [{"id": model, "object": "model"} for model in stub.models],
            }
            self._json(200, body)
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self) -> None:
        stub = cast(_JudgeStubServer, self.server).stub
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw)
        except json.JSONDecodeError:
            body = None
        headers = {name.lower(): value for name, value in self.headers.items()}
        step = stub.record("POST", self.path, headers, body)
        if isinstance(step, int):
            self._json(step, {"error": {"message": "stub error"}})
            return
        content = json.dumps({"label": step, "passage": 1, "reason": "stub"})
        self._json(
            200,
            {
                "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
                "usage": {"completion_tokens": 1},
            },
        )

    def _json(self, status: int, body: Any) -> None:
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        return


@pytest.fixture
def judge_stub() -> Iterator[JudgeStub]:
    stub = JudgeStub()
    try:
        yield stub
    finally:
        stub.close()
