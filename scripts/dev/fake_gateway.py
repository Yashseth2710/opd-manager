"""A stand-in for Razorpay, for the browser suite.

The browser tests drive the real application: the real order call, the real
signature checks, the real webhook handler. What they cannot drive is a
payment gateway, which needs an account, a network and a human tapping a UPI
prompt on a phone.

So this answers the two calls the application makes. Point RAZORPAY_API_URL at
it and everything above stays exactly as it ships. It is a test fixture and
nothing else: it keeps its orders in a dictionary, it authenticates nobody,
and it must never be reachable from anywhere that matters.

    python scripts/dev/fake_gateway.py --port 8081

Beyond the two the application calls, it answers one of its own: POST /pay
marks an order paid, which is how a test says "the patient paid" without a
phone in the room.
"""

from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

ORDERS: dict[str, dict[str, Any]] = {}
PAYMENTS: dict[str, dict[str, Any]] = {}


class Handler(BaseHTTPRequestHandler):
    def _send(self, status: int, body: dict[str, Any]) -> None:
        encoded = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _read(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        payload = json.loads(self.rfile.read(length))
        return payload if isinstance(payload, dict) else {}

    def do_POST(self) -> None:  # noqa: N802
        if self.path == "/orders":
            body = self._read()
            order = {
                "id": f"order_fake{len(ORDERS) + 1:06d}",
                "amount": int(body.get("amount") or 0),
                "currency": body.get("currency") or "INR",
                "status": "created",
            }
            ORDERS[order["id"]] = order
            self._send(200, order)
            return

        # The test paying on the patient's behalf.
        if self.path == "/pay":
            body = self._read()
            order = ORDERS.get(str(body.get("order_id")))
            if order is None:
                self._send(404, {"error": "no such order"})
                return
            payment = {
                "id": f"pay_fake{len(PAYMENTS) + 1:06d}",
                "order_id": order["id"],
                "status": body.get("status") or "captured",
                "amount": int(body.get("amount") or order["amount"]),
                "method": body.get("method") or "upi",
                "captured": body.get("status", "captured") == "captured",
            }
            PAYMENTS[payment["id"]] = payment
            self._send(200, payment)
            return

        if self.path.startswith("/payments/") and self.path.endswith("/capture"):
            payment_id = self.path.split("/")[2]
            payment = PAYMENTS.get(payment_id)
            if payment is None:
                self._send(404, {"error": "no such payment"})
                return
            payment["status"] = "captured"
            payment["captured"] = True
            self._send(200, payment)
            return

        self._send(404, {"error": "not here"})

    def do_GET(self) -> None:  # noqa: N802
        if self.path.startswith("/payments/"):
            payment = PAYMENTS.get(self.path.split("/")[2])
            if payment is None:
                self._send(404, {"error": "no such payment"})
                return
            self._send(200, payment)
            return
        self._send(404, {"error": "not here"})

    def log_message(self, *_: Any) -> None:
        """Quiet. The suite's own output is what anyone reads."""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8081)
    port = parser.parse_args().port
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
