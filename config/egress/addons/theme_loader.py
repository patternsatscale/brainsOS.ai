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
    """Mitmproxy addon responsible for loading runtime config & injecting the brainsOS theme into mitmweb."""

    def load(self, loader) -> None:
        cfg_path = "/run/mitmproxy/config.yaml"
        if os.path.isfile(cfg_path):
            try:
                from mitmproxy import ctx, optmanager

                if "web_password" in ctx.options:
                    optmanager.load_paths(ctx.options, cfg_path)
                    logger.info("[CONFIG-LOAD] Loaded mitmweb runtime configuration from %s", cfg_path)
                else:
                    logger.info(
                        "[CONFIG-LOAD] mitmweb 'web_password' option unsupported in this mitmproxy build; relying on ingress-net/Caddy RBAC."
                    )
            except Exception as exc:
                logger.warning("[CONFIG-WARN] Failed to load %s: %s", cfg_path, exc)

        try:
            import mitmproxy.tools.web

            pkg_dir = os.path.dirname(mitmproxy.tools.web.__file__)
            idx_path = os.path.join(pkg_dir, "index.html")
            dest = os.path.join(pkg_dir, "static", "brainsos-mitmweb.css")

            theme_src = "/theme/brainsos-mitmweb.css"
            if os.path.exists(theme_src):
                shutil.copyfile(theme_src, dest)
                logger.info("[THEME-INJECT] Synced live brainsOS theme into mitmweb static assets.")

            # Ensure theme stylesheet is linked in index.html with current cache buster
            if os.path.exists(idx_path):
                with open(idx_path, "r") as f:
                    content = f.read()
                if "brainsos-mitmweb.css" not in content:
                    with open(idx_path, "w") as f:
                        f.write(
                            content.replace(
                                "</head>",
                                '      <link rel="stylesheet" href="./static/brainsos-mitmweb.css?v=20261023-1">\n    </head>',
                            )
                        )
                    logger.info("[THEME-INJECT] brainsOS obsidian theme injected into mitmweb index.html")
        except Exception as e:
            logger.warning(f"[THEME-WARN] Failed to inject brainsOS theme into mitmweb: {e}")


addons = [ThemeLoaderAddon()]
