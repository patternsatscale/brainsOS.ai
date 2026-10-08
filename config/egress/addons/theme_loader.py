# ==============================================================================
# brainsOS: mitmweb Cybernetic Obsidian Dark Theme Loader Addon
# Injects bespoke brainsos-mitmweb.css into mitmweb web console on startup.
# Separation of concerns: Isolated from network authorization and flow proxying.
# ==============================================================================

import logging
import os
import shutil

logger = logging.getLogger("brainsos-egress-theme-loader")


class ThemeLoaderAddon:
    """Mitmproxy addon responsible for injecting the brainsOS theme into mitmweb."""

    def load(self, loader) -> None:
        try:
            import mitmproxy.tools.web

            pkg_dir = os.path.dirname(mitmproxy.tools.web.__file__)
            idx_path = os.path.join(pkg_dir, "index.html")
            dest = os.path.join(pkg_dir, "static", "brainsos-mitmweb.css")

            # Check if theme is already baked into index.html
            if os.path.exists(idx_path):
                with open(idx_path, "r") as f:
                    if "brainsos-mitmweb.css" in f.read():
                        logger.info("[THEME-INJECT] brainsOS obsidian theme verified in mitmweb static assets.")
                        return

            theme_src = "/theme/brainsos-mitmweb.css"
            if os.path.exists(theme_src):
                shutil.copy(theme_src, dest)
                with open(idx_path, "r+") as f:
                    content = f.read()
                    if "brainsos-mitmweb.css" not in content:
                        f.seek(0)
                        f.write(
                            content.replace(
                                "</head>",
                                '      <link rel="stylesheet" href="./static/brainsos-mitmweb.css?v=20261007-1">\n    </head>',
                            )
                        )
                        f.truncate()
                        logger.info("[THEME-INJECT] brainsOS obsidian theme injected into mitmweb index.html")
        except Exception as e:
            logger.warning(f"[THEME-WARN] Failed to inject brainsOS theme into mitmweb: {e}")


addons = [ThemeLoaderAddon()]
