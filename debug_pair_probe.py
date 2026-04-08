#!/usr/bin/env python3
"""
Minimal OpenClaw 3.31+ handshake probe.

Stage 1 only validates:
1. WebSocket opens
2. Gateway sends connect.challenge
3. Client replies with one canonical connect request
4. Script prints raw frames and final handshake result

Later stages can build pairing/reconnect/chat.send on top of this probe.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import platform as py_platform
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING
from typing import Any
from urllib.parse import urlparse

if TYPE_CHECKING:
    import websocket


PROBE_VERSION = "0.1.0"
DEFAULT_IDENTITY_FILE = os.path.expanduser("~/.openclaw/identity/probe-device-ed25519.json")

try:
    import config  # type: ignore
except Exception:
    config = SimpleNamespace(
        OPENCLAW_BASE_URL=os.environ.get("OPENCLAW_BASE_URL", "http://127.0.0.1:18789"),
        OPENCLAW_TOKEN=os.environ.get("OPENCLAW_TOKEN", ""),
        OPENCLAW_PASSWORD=os.environ.get("OPENCLAW_PASSWORD", ""),
        OPENCLAW_PROTOCOL_VERSION=int(os.environ.get("OPENCLAW_PROTOCOL_VERSION", "3")),
        OPENCLAW_CLIENT_ID=os.environ.get("OPENCLAW_CLIENT_ID", "cli"),
        OPENCLAW_CLIENT_MODE=os.environ.get("OPENCLAW_CLIENT_MODE", "cli"),
        OPENCLAW_ROLE=os.environ.get("OPENCLAW_ROLE", "operator"),
        OPENCLAW_SCOPES=os.environ.get("OPENCLAW_SCOPES", "operator.read,operator.write"),
        OPENCLAW_LOCALE=os.environ.get("OPENCLAW_LOCALE", "zh-CN"),
    )


@dataclass
class ProbeIdentity:
    device_id: str
    public_key_raw: bytes
    public_key_pem: str
    private_key_pem: str

    @classmethod
    def load_or_create(cls, path: str) -> "ProbeIdentity":
        serialization, ed25519 = load_crypto_modules()
        identity_path = Path(path).expanduser()
        if identity_path.exists():
            data = json.loads(identity_path.read_text(encoding="utf-8"))
            return cls(
                device_id=data["deviceId"],
                public_key_raw=base64.b64decode(data["publicKeyRawBase64"]),
                public_key_pem=data["publicKeyPem"],
                private_key_pem=data["privateKeyPem"],
            )

        identity_path.parent.mkdir(parents=True, exist_ok=True)
        private_key = ed25519.Ed25519PrivateKey.generate()
        public_key = private_key.public_key()
        public_key_raw = public_key.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        device_id = hashlib.sha256(public_key_raw).hexdigest()
        private_key_pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode("utf-8")
        public_key_pem = public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode("utf-8")
        payload = {
            "deviceId": device_id,
            "publicKeyRawBase64": base64.b64encode(public_key_raw).decode("utf-8"),
            "publicKeyPem": public_key_pem,
            "privateKeyPem": private_key_pem,
            "createdAt": int(time.time() * 1000),
            "algorithm": "Ed25519",
        }
        identity_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        return cls(
            device_id=device_id,
            public_key_raw=public_key_raw,
            public_key_pem=public_key_pem,
            private_key_pem=private_key_pem,
        )

    def sign_v3(
        self,
        *,
        client_id: str,
        client_mode: str,
        role: str,
        scopes: list[str],
        signed_at_ms: int,
        token: str | None,
        nonce: str,
        platform: str,
        device_family: str | None,
    ) -> tuple[str, str]:
        serialization, ed25519 = load_crypto_modules()
        payload = build_device_auth_payload_v3(
            device_id=self.device_id,
            client_id=client_id,
            client_mode=client_mode,
            role=role,
            scopes=scopes,
            signed_at_ms=signed_at_ms,
            token=token,
            nonce=nonce,
            platform=platform,
            device_family=device_family,
        )
        private_key = serialization.load_pem_private_key(
            self.private_key_pem.encode("utf-8"),
            password=None,
        )
        if not isinstance(private_key, ed25519.Ed25519PrivateKey):
            raise RuntimeError("Identity file does not contain an Ed25519 private key")
        signature = private_key.sign(payload.encode("utf-8"))
        return payload, base64.b64encode(signature).decode("utf-8")


def normalize_metadata_field(value: str | None) -> str:
    return (value or "").strip()


def build_device_auth_payload_v3(
    *,
    device_id: str,
    client_id: str,
    client_mode: str,
    role: str,
    scopes: list[str],
    signed_at_ms: int,
    token: str | None,
    nonce: str,
    platform: str,
    device_family: str | None,
) -> str:
    return "|".join(
        [
            "v3",
            device_id,
            client_id,
            client_mode,
            role,
            ",".join(scopes),
            str(signed_at_ms),
            token or "",
            nonce,
            normalize_metadata_field(platform),
            normalize_metadata_field(device_family),
        ]
    )


def parse_scopes(raw_scopes: str) -> list[str]:
    return [item.strip() for item in raw_scopes.split(",") if item.strip()]


def default_ws_url() -> str:
    base_url = config.OPENCLAW_BASE_URL.rstrip("/")
    if base_url.startswith("http://"):
        return "ws://" + base_url[7:]
    if base_url.startswith("https://"):
        return "wss://" + base_url[8:]
    if base_url.startswith("ws://") or base_url.startswith("wss://"):
        return base_url
    return f"ws://{base_url}"


def default_origin(ws_url: str) -> str | None:
    parsed = urlparse(ws_url)
    if not parsed.scheme or not parsed.netloc:
        return None
    http_scheme = "https" if parsed.scheme == "wss" else "http"
    return f"{http_scheme}://{parsed.netloc}"


def pretty_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)


def redact_secret(value: str) -> str:
    if not value:
        return value
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}...{value[-4:]}"


def redact_payload(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            if key in {"token", "password", "deviceToken", "signature"} and isinstance(item, str):
                redacted[key] = redact_secret(item)
            else:
                redacted[key] = redact_payload(item)
        return redacted
    if isinstance(value, list):
        return [redact_payload(item) for item in value]
    return value


def redact_signed_payload(payload: str, token: str | None) -> str:
    if not token:
        return payload
    marker = f"|{token}|"
    if marker not in payload:
        return payload
    return payload.replace(marker, f"|{redact_secret(token)}|", 1)


def recv_json(ws: websocket.WebSocket) -> dict[str, Any]:
    raw = ws.recv()
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    print("RECV", raw)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Received non-JSON frame: {raw!r}") from exc
    return data


def send_json(ws: websocket.WebSocket, payload: dict[str, Any]) -> None:
    text = json.dumps(payload, ensure_ascii=False)
    print("SEND", pretty_json(redact_payload(payload)))
    ws.send(text)


def build_auth_payload(args: argparse.Namespace) -> dict[str, str]:
    auth: dict[str, str] = {}
    if args.token:
        auth["token"] = args.token
    if args.password:
        auth["password"] = args.password
    if args.device_token:
        auth["deviceToken"] = args.device_token
    return auth


def build_connect_params(args: argparse.Namespace, challenge: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
    include_auth = args.profile in ("auth-only", "auth+device")
    include_device = args.profile in ("device-only", "auth+device")

    auth = build_auth_payload(args) if include_auth else {}
    auth_token_for_signature = auth.get("token") or auth.get("deviceToken")

    client_descriptor: dict[str, Any] = {
        "id": args.client_id,
        "mode": args.client_mode,
        "version": args.client_version,
        "platform": args.platform,
        "deviceFamily": args.device_family,
    }

    params: dict[str, Any] = {
        "minProtocol": args.protocol,
        "maxProtocol": args.protocol,
        "client": client_descriptor,
        "role": args.role,
        "scopes": args.scopes,
        "caps": [],
        "commands": [],
        "permissions": {},
        "locale": args.locale,
        "userAgent": args.user_agent,
    }

    if include_auth and auth:
        params["auth"] = auth

    signed_payload: str | None = None
    if include_device:
        identity = ProbeIdentity.load_or_create(args.identity_file)
        signed_at_ms = int(challenge["ts"])
        signed_payload, signature = identity.sign_v3(
            client_id=args.client_id,
            client_mode=args.client_mode,
            role=args.role,
            scopes=args.scopes,
            signed_at_ms=signed_at_ms,
            token=auth_token_for_signature,
            nonce=challenge["nonce"],
            platform=args.platform,
            device_family=args.device_family,
        )
        params["device"] = {
            "id": identity.device_id,
            "publicKey": identity.public_key_pem,
            "signature": signature,
            "signedAt": signed_at_ms,
            "nonce": challenge["nonce"],
        }

    return params, signed_payload


def run_probe(args: argparse.Namespace) -> int:
    websocket_module = load_websocket_module()
    headers: list[str] = []
    if args.legacy_bearer_header and args.token:
        headers.append(f"Authorization: Bearer {args.token}")

    connect_id = str(uuid.uuid4())
    origin = args.origin or default_origin(args.url)

    print(f"Probe version: {PROBE_VERSION}")
    print(f"Gateway URL: {args.url}")
    print(f"Origin: {origin or '<none>'}")
    print(f"Profile: {args.profile}")
    print(f"Client: id={args.client_id} mode={args.client_mode} platform={args.platform}")
    print(f"Role/scopes: {args.role} {args.scopes}")
    print(f"Identity file: {Path(args.identity_file).expanduser()}")

    ws = websocket_module.create_connection(
        args.url,
        timeout=args.timeout,
        header=headers,
        http_origin=origin,
    )
    try:
        first_frame = recv_json(ws)
        if first_frame.get("type") != "event" or first_frame.get("event") != "connect.challenge":
            raise RuntimeError(
                "Expected initial connect.challenge event, "
                f"got: {pretty_json(first_frame)}"
            )
        challenge = first_frame.get("payload", {})
        nonce = challenge.get("nonce")
        ts = challenge.get("ts")
        if not nonce or ts is None:
            raise RuntimeError(f"Challenge missing nonce/ts: {pretty_json(challenge)}")

        params, signed_payload = build_connect_params(args, challenge)
        if signed_payload:
            auth = params.get("auth", {})
            auth_token = auth.get("token") or auth.get("deviceToken")
            print("SIGNED_PAYLOAD", redact_signed_payload(signed_payload, auth_token))

        connect_request = {
            "type": "req",
            "id": connect_id,
            "method": "connect",
            "params": params,
        }
        send_json(ws, connect_request)

        while True:
            frame = recv_json(ws)
            if frame.get("type") == "res" and frame.get("id") == connect_id:
                if frame.get("ok") is True:
                    payload = frame.get("payload", {})
                    print("HANDSHAKE_OK", pretty_json(payload))
                    auth_payload = payload.get("auth")
                    if auth_payload is not None:
                        print("HANDSHAKE_AUTH", pretty_json(redact_payload(auth_payload)))
                    else:
                        print("HANDSHAKE_AUTH <none>")
                    if args.rpc_method:
                        return run_rpc(
                            ws,
                            args.rpc_method,
                            parse_rpc_params(args.rpc_params_json),
                            listen_seconds=args.listen_seconds,
                        )
                    return 0
                print("HANDSHAKE_ERROR", pretty_json(frame.get("error", {})))
                return 2

            # Keep printing unrelated events because later pairing steps will need them.
            if frame.get("type") == "event":
                continue

            if frame.get("error"):
                print("FRAME_ERROR", pretty_json(frame["error"]))
                return 3
    finally:
        ws.close()


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Minimal OpenClaw 3.31+ handshake probe",
    )
    parser.add_argument(
        "--url",
        default=default_ws_url(),
        help="Gateway WebSocket URL",
    )
    parser.add_argument(
        "--origin",
        default=None,
        help="Optional Origin header. Defaults to the HTTP(S) equivalent of --url.",
    )
    parser.add_argument(
        "--profile",
        choices=("auth-only", "device-only", "auth+device"),
        default="auth+device",
        help="Which connect payload variant to send",
    )
    parser.add_argument(
        "--token",
        default=config.OPENCLAW_TOKEN,
        help="Shared gateway token",
    )
    parser.add_argument(
        "--password",
        default=config.OPENCLAW_PASSWORD,
        help="Shared gateway password",
    )
    parser.add_argument(
        "--device-token",
        default="",
        help="Optional deviceToken to send in params.auth",
    )
    parser.add_argument(
        "--protocol",
        type=int,
        default=config.OPENCLAW_PROTOCOL_VERSION,
        help="Gateway protocol version to request",
    )
    parser.add_argument(
        "--client-id",
        default=config.OPENCLAW_CLIENT_ID,
        help="connect.params.client.id",
    )
    parser.add_argument(
        "--client-mode",
        default=config.OPENCLAW_CLIENT_MODE,
        help="connect.params.client.mode",
    )
    parser.add_argument(
        "--client-version",
        default=PROBE_VERSION,
        help="connect.params.client.version",
    )
    parser.add_argument(
        "--role",
        default=config.OPENCLAW_ROLE,
        help="Gateway role claim",
    )
    parser.add_argument(
        "--scopes",
        type=parse_scopes,
        default=parse_scopes(config.OPENCLAW_SCOPES),
        help="Comma-separated scopes",
    )
    parser.add_argument(
        "--locale",
        default=config.OPENCLAW_LOCALE,
        help="connect.params.locale",
    )
    parser.add_argument(
        "--user-agent",
        default=f"debug-pair-probe/{PROBE_VERSION}",
        help="connect.params.userAgent",
    )
    parser.add_argument(
        "--platform",
        default=py_platform.system().lower() or "linux",
        help="connect.params.client.platform",
    )
    parser.add_argument(
        "--device-family",
        default="raspberry-pi-zero-2w",
        help="connect.params.client.deviceFamily",
    )
    parser.add_argument(
        "--identity-file",
        default=DEFAULT_IDENTITY_FILE,
        help="Path to a persistent Ed25519 probe identity",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=15,
        help="Socket timeout in seconds",
    )
    parser.add_argument(
        "--legacy-bearer-header",
        action="store_true",
        help="Also send Authorization: Bearer for compatibility experiments",
    )
    parser.add_argument(
        "--rpc-method",
        default="",
        help="Optional RPC method to call after hello-ok",
    )
    parser.add_argument(
        "--rpc-params-json",
        default="{}",
        help="JSON object for --rpc-method params",
    )
    parser.add_argument(
        "--listen-seconds",
        type=float,
        default=0.0,
        help="After RPC_OK, keep listening for events for this many seconds",
    )
    return parser


def load_websocket_module():
    try:
        import websocket as websocket_module
    except ImportError as exc:  # pragma: no cover - runtime dependency guard
        raise RuntimeError(
            "Missing dependency for probe. Run `pip3 install websocket-client`."
        ) from exc
    return websocket_module


def load_crypto_modules():
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import ed25519
    except ImportError as exc:  # pragma: no cover - runtime dependency guard
        raise RuntimeError(
            "Missing dependency for probe. Run `pip3 install cryptography`."
        ) from exc
    return serialization, ed25519


def main() -> int:
    parser = build_arg_parser()
    args = parser.parse_args()
    try:
        return run_probe(args)
    except KeyboardInterrupt:
        print("Interrupted", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"PROBE_FAILED {exc}", file=sys.stderr)
        return 1


def parse_rpc_params(raw_json: str) -> dict[str, Any]:
    try:
        value = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid --rpc-params-json: {raw_json}") from exc
    if not isinstance(value, dict):
        raise ValueError("--rpc-params-json must decode to a JSON object")
    return value


def run_rpc(
    ws: "websocket.WebSocket",
    method: str,
    params: dict[str, Any],
    *,
    listen_seconds: float = 0.0,
) -> int:
    rpc_id = str(uuid.uuid4())
    request = {
        "type": "req",
        "id": rpc_id,
        "method": method,
        "params": params,
    }
    send_json(ws, request)
    while True:
        frame = recv_json(ws)
        if frame.get("type") == "res" and frame.get("id") == rpc_id:
            if frame.get("ok") is True:
                print("RPC_OK", pretty_json(frame.get("payload", {})))
                if listen_seconds > 0:
                    return collect_events(ws, listen_seconds)
                return 0
            print("RPC_ERROR", pretty_json(frame.get("error", {})))
            return 4
        if frame.get("type") == "event":
            continue
        if frame.get("error"):
            print("FRAME_ERROR", pretty_json(frame["error"]))
            return 5


def collect_events(ws: "websocket.WebSocket", listen_seconds: float) -> int:
    deadline = time.time() + listen_seconds
    while time.time() < deadline:
        remaining = max(0.1, deadline - time.time())
        ws.settimeout(remaining)
        try:
            frame = recv_json(ws)
        except Exception as exc:
            message = str(exc).lower()
            if "timed out" in message or "timeout" in message:
                print("EVENT_LISTEN_TIMEOUT")
                return 0
            raise
        event_name = frame.get("event") if isinstance(frame, dict) else None
        print("EVENT_FRAME_TYPE", frame.get("type"), event_name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
