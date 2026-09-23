#!/usr/bin/env python3
"""Project Titan: Signal Gateway Multiplexing Reverse Proxy.

Multiplexes incoming HTTP connections on port 8080:
- Routes /api/v1/* to 127.0.0.1:8082 (native signal-cli daemon in HTTP mode:
  provides /api/v1/check, /api/v1/events SSE stream, and /api/v1/rpc JSON-RPC).
- Routes all other traffic (/v1/*, /v2/*) to 127.0.0.1:8084 (signal-cli-rest-api:
  provides /v1/about, /v1/accounts, /v1/qrcodelink, /v1/register, etc.).
"""

import asyncio
import logging
import os
import signal
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [signal-proxy] %(message)s",
)
logger = logging.getLogger("signal-proxy")

NATIVE_HTTP_PORT = int(os.getenv("SIGNAL_NATIVE_HTTP_PORT", "8082"))
REST_API_PORT = int(os.getenv("SIGNAL_REST_API_PORT", "8084"))
LISTEN_PORT = int(os.getenv("PORT", "8080"))


async def _pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while True:
            chunk = await reader.read(8192)
            if not chunk:
                break
            writer.write(chunk)
            await writer.drain()
    except Exception:
        pass
    finally:
        try:
            writer.close()
        except Exception:
            pass


async def handle_client(client_reader: asyncio.StreamReader, client_writer: asyncio.StreamWriter) -> None:
    try:
        header_bytes = b""
        while b"\r\n\r\n" not in header_bytes:
            chunk = await client_reader.read(4096)
            if not chunk:
                client_writer.close()
                return
            header_bytes += chunk
            if len(header_bytes) > 65536:
                client_writer.close()
                return

        headers_part, body_part = header_bytes.split(b"\r\n\r\n", 1)
        lines = headers_part.split(b"\r\n")
        first_line = lines[0].decode("latin1", errors="replace")
        parts = first_line.split(" ")
        path = parts[1] if len(parts) > 1 else "/"

        # Route determination
        if path.startswith("/api/v1"):
            target_port = NATIVE_HTTP_PORT
            target_host = f"127.0.0.1:{NATIVE_HTTP_PORT}".encode("latin1")
        else:
            target_port = REST_API_PORT
            target_host = f"127.0.0.1:{REST_API_PORT}".encode("latin1")

        # Parse Content-Length if present
        content_length = 0
        new_lines = []
        for line in lines:
            if line.lower().startswith(b"host:"):
                new_lines.append(b"Host: " + target_host)
            else:
                new_lines.append(line)
            if line.lower().startswith(b"content-length:"):
                try:
                    content_length = int(line.split(b":", 1)[1].strip())
                except Exception:
                    pass

        # Read any remaining body bytes up to content_length
        remaining_body = content_length - len(body_part)
        while remaining_body > 0:
            chunk = await client_reader.read(min(remaining_body, 8192))
            if not chunk:
                break
            body_part += chunk
            remaining_body -= len(chunk)

        new_request = b"\r\n".join(new_lines) + b"\r\n\r\n" + body_part

        # Connect to chosen backend
        backend_reader, backend_writer = await asyncio.open_connection("127.0.0.1", target_port)
        backend_writer.write(new_request)
        await backend_writer.drain()

        # Pipe remaining traffic bidirectionally (handles SSE streams & large responses)
        await asyncio.gather(
            _pipe(client_reader, backend_writer),
            _pipe(backend_reader, client_writer),
        )
    except Exception as exc:
        logger.debug("Proxy error: %s", exc)
    finally:
        try:
            client_writer.close()
        except Exception:
            pass


async def main() -> None:
    server = await asyncio.start_server(handle_client, "0.0.0.0", LISTEN_PORT)
    logger.info(
        "Signal Gateway Proxy listening on :%d (routing /api/v1 -> :%d, other -> :%d)",
        LISTEN_PORT,
        NATIVE_HTTP_PORT,
        REST_API_PORT,
    )

    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def _shutdown() -> None:
        logger.info("Shutdown signal received, closing proxy...")
        stop_event.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _shutdown)
        except NotImplementedError:
            pass

    async with server:
        server_task = asyncio.create_task(server.serve_forever())
        await stop_event.wait()
        server_task.cancel()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
