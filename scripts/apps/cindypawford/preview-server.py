#!/usr/bin/env python3
"""
Local Preview Server for Cindy Pawford Web Surfaces
Serves:
  - http://localhost:8088/         -> apps/cindypawford/site (Main Atelier with Platform Shell Dock)
  - http://localhost:8088/archive/ -> apps/cindypawford/archive (Digital Museum Archive Portal)
  - http://localhost:8088/info/    -> apps/cindypawford/info (Project Information Portal)
"""

import argparse
import http.server
import os
import posixpath
import re
import socketserver
import sys
import urllib.parse

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "..", "..", ".."))
DATA_DIR = os.environ.get("BRAINSOS_DATA_DIR", os.path.join(REPO_ROOT, "data"))


def resolve_app_dir():
    candidates = [
        os.path.join(DATA_DIR, "agents", "bawtford", "apps", "cindypawford"),
        os.path.join(REPO_ROOT, "data", "agents", "bawtford", "apps", "cindypawford"),
        os.path.join(DATA_DIR, "agent_apps", "cindypawford"),
        os.path.join(REPO_ROOT, "data", "agent_apps", "cindypawford"),
        os.path.join(REPO_ROOT, "config", "default_agents", "bawtford", "apps", "cindypawford"),
    ]
    for c in candidates:
        if os.path.isdir(c):
            return c
    return candidates[0]


APP_DIR = resolve_app_dir()
SITE_DIR = os.path.join(APP_DIR, "site")
ARCHIVE_DIR = os.path.join(APP_DIR, "archive")
INFO_DIR = os.path.join(APP_DIR, "info")

DEFAULT_PORT = 8088
PORT = DEFAULT_PORT


class CindyPreviewHandler(http.server.SimpleHTTPRequestHandler):
    directory = SITE_DIR

    def translate_path(self, path):
        raw_path = path.split("?", 1)[0].split("#", 1)[0]
        trailing_slash = raw_path.rstrip().endswith("/")
        try:
            decoded = urllib.parse.unquote(raw_path, errors="surrogatepass")
        except UnicodeDecodeError:
            decoded = urllib.parse.unquote(raw_path)
        decoded = decoded.replace("\\", "/")
        decoded = re.sub(r"^/+", "/", decoded)
        normalized = posixpath.normpath(decoded)
        if not normalized.startswith("/"):
            normalized = "/" + normalized
        normalized = re.sub(r"^/+", "/", normalized)

        if normalized == "/archive" or normalized.startswith("/archive/"):
            root = ARCHIVE_DIR
            rel_subpath = normalized[len("/archive"):] or "/"
        elif normalized == "/info" or normalized.startswith("/info/"):
            root = INFO_DIR
            rel_subpath = normalized[len("/info"):] or "/"
        else:
            root = SITE_DIR
            rel_subpath = normalized

        if trailing_slash and not rel_subpath.endswith("/"):
            rel_subpath += "/"

        real_root = os.path.realpath(root)
        if "\x00" in decoded or "\x00" in rel_subpath:
            return os.path.join(real_root, "__forbidden__")
        has_dir = "directory" in getattr(self, "__dict__", {})
        prev_dir = self.__dict__.get("directory") if has_dir else None
        self.directory = real_root
        try:
            translated = super().translate_path(rel_subpath)
        finally:
            if has_dir:
                self.directory = prev_dir
            elif "directory" in self.__dict__:
                del self.__dict__["directory"]

        try:
            if "\x00" in translated:
                return os.path.join(real_root, "__forbidden__")
            real_translated = os.path.realpath(translated)
            if os.path.commonpath([real_root, real_translated]) != real_root:
                return os.path.join(real_root, "__forbidden__")
        except ValueError:
            return os.path.join(real_root, "__forbidden__")
        return translated

    def end_headers(self):
        # Add CORS and no-cache headers for instant previewing
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        super().end_headers()


def main(argv=None):
    parser = argparse.ArgumentParser(description="Local Preview Server for Cindy Pawford Web Surfaces")
    parser.add_argument("port", nargs="?", type=int, default=DEFAULT_PORT, help="Loopback port to listen on")
    args = parser.parse_args(argv)
    port = args.port

    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("127.0.0.1", port), CindyPreviewHandler) as httpd:
        print("=================================================================")
        print(f" Cindy Pawford Local Preview Server Running on Port {port}")
        print("=================================================================")
        print(f"  • Live Site + Shell Dock: http://127.0.0.1:{port}/")
        print(f"  • Digital Museum Archive: http://127.0.0.1:{port}/archive/")
        print(f"  • Project Information:    http://127.0.0.1:{port}/info/")
        print("=================================================================")
        sys.stdout.flush()
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nPreview server stopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
