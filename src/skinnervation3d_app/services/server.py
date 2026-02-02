from __future__ import annotations

import http.server
import socket
import socketserver
import threading
from functools import partial
from pathlib import Path
from urllib.parse import urljoin
import logging

logger = logging.getLogger(__name__)


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        # comment out to fully silence
        # logger.debug("Docs server: " + (format % args))
        return

    def log_error(self, format, *args):
        logger.warning("Docs server error: " + (format % args))


class DocsServer:
    """Serve a directory over http://127.0.0.1:<port>/, started lazily."""

    def __init__(self, docs_root: Path):
        self.docs_root = Path(docs_root)
        self.httpd: socketserver.TCPServer | None = None
        self.port: int | None = None
        self.thread: threading.Thread | None = None

    @property
    def is_running(self) -> bool:
        return self.httpd is not None and self.port is not None

    def start(self) -> None:
        if self.is_running:
            return
        if not self.docs_root.exists():
            raise FileNotFoundError(f"Docs root not found: {self.docs_root}")

        # pick a free local port
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            self.port = int(s.getsockname()[1])

        handler = partial(QuietHandler, directory=str(self.docs_root))

        # Threading server so the UI never blocks
        class _ThreadingTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
            daemon_threads = True
            allow_reuse_address = True

        self.httpd = _ThreadingTCPServer(("127.0.0.1", self.port), handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def base_url(self) -> str:
        if not self.is_running:
            raise RuntimeError("Docs server not started")
        return f"http://127.0.0.1:{self.port}"

    def stop(self) -> None:
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()
        self.httpd = None
        self.port = None
        self.thread = None

    def make_url_crossplatform(self, 
        doc_path: str
    ) -> str:
        base = self.base_url.rstrip("/") + "/"
        
        p = Path(doc_path)
        if p.is_absolute():
            try:
                rel = p.relative_to(self.docs_root.resolve()).as_posix()
            except ValueError:
                # doc_roots is not a subdirectory of p
                rel = p.as_posix().lstrip("/")
        else:
            rel = p.as_posix()
        return urljoin(base, rel)