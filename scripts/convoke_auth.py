#!/usr/bin/env python3
import asyncio
import os
import queue
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from backend.integrations.convoke import (  # noqa: E402
    DEFAULT_REDIRECT_URI,
    JsonOAuthStorage,
    build_oauth_provider,
)


class CallbackServer:
    def __init__(self, redirect_uri: str) -> None:
        parsed = urlparse(redirect_uri)
        if parsed.hostname not in {"127.0.0.1", "localhost"}:
            raise ValueError("redirect URI must point to localhost")
        if parsed.port is None:
            raise ValueError("redirect URI must include a port")

        self.path = parsed.path or "/callback"
        self.events: queue.Queue[dict[str, str | None]] = queue.Queue(maxsize=1)
        self.httpd = HTTPServer((parsed.hostname, parsed.port), self._handler_class())
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)

    async def wait_for_callback(self, timeout: float) -> tuple[str, str | None]:
        try:
            event = await asyncio.to_thread(self.events.get, True, timeout)
        except queue.Empty as exc:
            raise TimeoutError("timed out waiting for OAuth callback") from exc

        error = event.get("error")
        if error:
            description = event.get("error_description")
            message = f"OAuth callback error: {error}"
            if description:
                message += f" - {description}"
            raise RuntimeError(message)

        code = event.get("code")
        if not code:
            raise RuntimeError("OAuth callback did not include an authorization code")
        return code, event.get("state")

    def _handler_class(self) -> type[BaseHTTPRequestHandler]:
        parent = self

        class OAuthCallbackHandler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                parsed = urlparse(self.path)
                if parsed.path != parent.path:
                    self.send_response(404)
                    self.end_headers()
                    return

                params = parse_qs(parsed.query)
                event = {
                    "code": _first(params, "code"),
                    "state": _first(params, "state"),
                    "error": _first(params, "error"),
                    "error_description": _first(params, "error_description"),
                }
                try:
                    parent.events.put_nowait(event)
                except queue.Full:
                    pass

                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(
                    b"<html><body><h1>Convoke authorization complete.</h1>"
                    b"<p>You can close this browser window and return to the terminal.</p>"
                    b"</body></html>"
                )

            def log_message(self, _format: str, *args: object) -> None:
                return

        return OAuthCallbackHandler


def _first(params: dict[str, list[str]], key: str) -> str | None:
    values = params.get(key)
    return values[0] if values else None


async def run_auth_flow() -> None:
    load_dotenv(PROJECT_ROOT / ".env")

    mcp_url = os.getenv("CONVOKE_MCP_URL")
    if not mcp_url:
        raise RuntimeError("CONVOKE_MCP_URL is required in .env")

    redirect_uri = os.getenv("CONVOKE_OAUTH_REDIRECT_URI", DEFAULT_REDIRECT_URI)
    callback_server = CallbackServer(redirect_uri)
    callback_server.start()

    async def redirect_handler(auth_url: str) -> None:
        print("Opening browser for Convoke authorization...")
        opened = webbrowser.open(auth_url, new=1, autoraise=True)
        if not opened:
            print(f"Browser did not open automatically. Visit this URL:\n{auth_url}")

    async def callback_handler() -> tuple[str, str | None]:
        return await callback_server.wait_for_callback(timeout=300)

    try:
        from mcp import ClientSession
        from mcp.client.streamable_http import streamablehttp_client

        provider = build_oauth_provider(
            storage=JsonOAuthStorage(),
            redirect_handler=redirect_handler,
            callback_handler=callback_handler,
            timeout=300,
        )

        print(f"Connecting to Convoke MCP: {mcp_url}")
        async with streamablehttp_client(url=mcp_url, auth=provider) as (
            read_stream,
            write_stream,
            _get_session_id,
        ):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                tools = (await session.list_tools()).tools
                print(
                    "Convoke OAuth complete. Stored credentials in .convoke/. "
                    f"Discovered {len(tools)} tools."
                )
    finally:
        callback_server.stop()


def main() -> int:
    try:
        asyncio.run(run_auth_flow())
        return 0
    except Exception as exc:
        print(f"Convoke OAuth failed: {exc.__class__.__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
