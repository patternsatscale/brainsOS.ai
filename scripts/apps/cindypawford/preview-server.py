#!/usr/bin/env python3
"""
Local Preview Server for Cindy Pawford Web Surfaces
Serves:
  - http://localhost:8088/         -> apps/cindypawford/site (Main Atelier with Platform Shell Dock)
  - http://localhost:8088/archive/ -> apps/cindypawford/archive (Digital Museum Archive Portal)
  - http://localhost:8088/info/    -> apps/cindypawford/info (Project Information Portal)
"""

import http.server
import socketserver
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "..", "..", ".."))

SITE_DIR = os.path.join(REPO_ROOT, "apps", "cindypawford", "site")
ARCHIVE_DIR = os.path.join(REPO_ROOT, "apps", "cindypawford", "archive")
INFO_DIR = os.path.join(REPO_ROOT, "apps", "cindypawford", "info")

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8088

class CindyPreviewHandler(http.server.SimpleHTTPRequestHandler):
    def translate_path(self, path):
        # Strip query strings
        path = path.split("?", 1)[0].split("#", 1)[0]

        if path.startswith("/archive"):
            rel = path[len("/archive"):].lstrip("/")
            full = os.path.join(ARCHIVE_DIR, rel)
            if os.path.isdir(full) and not path.endswith("/"):
                # Ensure trailing slash for directory resolution
                return full
            return full

        if path.startswith("/info"):
            rel = path[len("/info"):].lstrip("/")
            full = os.path.join(INFO_DIR, rel)
            return full

        # Default: route to site
        rel = path.lstrip("/")
        return os.path.join(SITE_DIR, rel)

    def end_headers(self):
        # Add CORS and no-cache headers for instant previewing
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        super().end_headers()

if __name__ == "__main__":
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("0.0.0.0", PORT), CindyPreviewHandler) as httpd:
        print(f"=================================================================")
        print(f" Cindy Pawford Local Preview Server Running on Port {PORT}")
        print(f"=================================================================")
        print(f"  • Live Site + Shell Dock: http://localhost:{PORT}/")
        print(f"  • Digital Museum Archive: http://localhost:{PORT}/archive/")
        print(f"  • Project Information:    http://localhost:{PORT}/info/")
        print(f"=================================================================")
        sys.stdout.flush()
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nPreview server stopped.")
