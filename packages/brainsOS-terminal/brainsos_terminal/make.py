"""brainsOS: Smart Make Interceptor & Delegation Handler."""

from __future__ import annotations

import os
import subprocess
import sys


def find_system_make() -> str:
    """Find the real underlying make binary, skipping the wrapper itself."""
    current_exe = os.path.realpath(sys.argv[0])
    # Common system locations
    for standard_path in ("/usr/bin/make", "/bin/make", "/opt/homebrew/bin/make"):
        if os.path.isfile(standard_path) and os.access(standard_path, os.X_OK):
            try:
                if os.path.realpath(standard_path) != current_exe:
                    return standard_path
            except OSError:
                continue

    # Search PATH
    path_dirs = os.environ.get("PATH", "").split(os.pathsep)
    for p in path_dirs:
        candidate = os.path.join(p, "make")
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            try:
                if os.path.realpath(candidate) != current_exe:
                    return candidate
            except OSError:
                continue

    return "/usr/bin/make"


def resolve_system_mk() -> str | None:
    """Resolve the platform system.mk file path."""
    for path in (
        os.environ.get("BRAINSOS_SYSTEM_MK", ""),
        "/etc/brainsos/editor/system.mk",
        "/etc/brainsos/system.mk",
    ):
        if path and os.path.isfile(path):
            return path
    return None


def execute_make(real_make: str, args: list[str]) -> None:
    """Execute make with given arguments, replacing the current process."""
    cmd = [real_make, *args]
    try:
        os.execv(real_make, cmd)
    except OSError:
        res = subprocess.run(cmd)
        sys.exit(res.returncode)


def main() -> None:
    """Main entrypoint for the brainsOS smart make wrapper."""
    real_make = find_system_make()
    system_mk = resolve_system_mk()
    args = sys.argv[1:]

    has_local_makefile = any(
        os.path.isfile(name) for name in ("Makefile", "makefile", "GNUmakefile")
    )

    # 1. No arguments provided and no local Makefile: show system help
    if not args and not has_local_makefile:
        if system_mk:
            execute_make(real_make, ["-f", system_mk, "help"])
            return
        execute_make(real_make, args)
        return

    # 2. Local Makefile exists in current working directory
    if has_local_makefile:
        # If target can be run by local Makefile, let it run
        dry_run = subprocess.run(
            [real_make, "-q", *args],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if dry_run.returncode == 0:
            execute_make(real_make, args)
            return

        # If local Makefile does not handle target (or dry-run fails), check system.mk
        if system_mk:
            sys_dry_run = subprocess.run(
                [real_make, "-f", system_mk, "-q", *args],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            if sys_dry_run.returncode == 0:
                execute_make(real_make, ["-f", system_mk, *args])
                return

        # Fallback to local make to show normal error output
        execute_make(real_make, args)
        return

    # 3. No local Makefile: delegate to system.mk if available
    if system_mk:
        execute_make(real_make, ["-f", system_mk, *args])
        return

    # 4. Ultimate fallback to standard make
    execute_make(real_make, args)


if __name__ == "__main__":
    main()
