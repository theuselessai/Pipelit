#!/usr/bin/env python3
"""Mock Anthropic Messages API server for E2E smoke tests.

Returns a canned text response for POST /v1/messages.
No tool use, no streaming — just validates the pipeline plumbing.

Usage:
    python mock_llm_server.py [--port PORT]
    # Default port: 9999
"""

import json
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler

PORT = int(sys.argv[sys.argv.index("--port") + 1]) if "--port" in sys.argv else 9999

CANNED_RESPONSE = json.dumps({
    "id": "msg_mock_e2e_test_response",
    "type": "message",
    "role": "assistant",
    "content": [
        {
            "type": "text",
            "text": "E2E_MOCK_RESPONSE_OK"
        }
    ],
    "model": "mock-model",
    "stop_reason": "end_turn",
    "stop_sequence": None,
    "usage": {
        "input_tokens": 10,
        "output_tokens": 5
    }
}).encode()


class MockAnthropicHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path == "/v1/messages":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(CANNED_RESPONSE)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):  # noqa: A002
        print(f"[mock-llm] {format % args}", flush=True)


if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", PORT), MockAnthropicHandler)
    print(f"[mock-llm] Listening on 0.0.0.0:{PORT}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
