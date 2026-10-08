# ==============================================================================
# brainsOS: Tool Egress Gateway & Inspection Proxy (mitmproxy / mitmweb)
# Pre-injects brainsOS Obsidian Cybernetic Theme into mitmweb static assets
# ==============================================================================

FROM mitmproxy/mitmproxy:latest

# Copy theme file and inject into mitmweb static assets at build time
COPY config/egress/theme/brainsos-mitmweb.css /tmp/brainsos-mitmweb.css
RUN python3 - << 'EOF'
import mitmproxy.tools.web, os, shutil
pkg_dir = os.path.dirname(mitmproxy.tools.web.__file__)
dest = os.path.join(pkg_dir, "static", "brainsos-mitmweb.css")
shutil.copy("/tmp/brainsos-mitmweb.css", dest)
idx_path = os.path.join(pkg_dir, "index.html")
if os.path.exists(idx_path):
    with open(idx_path, "r+") as f:
        content = f.read()
        if "brainsos-mitmweb.css" not in content:
            f.seek(0)
            f.write(content.replace("</head>", "      <link rel=\"stylesheet\" href=\"./static/brainsos-mitmweb.css?v=20261007-1\">\n    </head>"))
            f.truncate()
EOF
RUN rm -f /tmp/brainsos-mitmweb.css
