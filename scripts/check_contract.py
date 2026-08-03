#!/usr/bin/env python3
"""Enforce the ImSwitch plugin contract.

Run locally with `make check`; CI runs the same script. Every check here exists
because getting it wrong produces a failure that is hard to diagnose at runtime
— usually in someone else's browser, on someone else's microscope.

Exit code 0 = contract satisfied. Non-zero = one or more violations, listed.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:                       # python 3.10
    import tomli as tomllib                       # type: ignore

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = "imswitch_plugin_example"

failures: list[str] = []
notes: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    if ok:
        print(f"  PASS  {name}")
    else:
        print(f"  FAIL  {name}")
        if detail:
            print("        " + detail.replace("\n", "\n        "))
        failures.append(name)


def load_shared_deps() -> list[str]:
    """Parse SHARED_DEPS out of the vendored shared-deps.js without running node."""
    text = (ROOT / "ui-src" / "shared-deps.js").read_text(encoding="utf-8")
    block = re.search(r"const SHARED_DEPS = \[(.*?)\];", text, re.S)
    if not block:
        return []
    return re.findall(r'"([^"]+)"', block.group(1))


# ─── 1. No runtime dependencies ──────────────────────────────────────────────
def check_no_runtime_dependencies() -> None:
    """A plugin is bind-mounted, not pip-installed. Any runtime dependency is
    either not installed at all, or worse, a second copy of a library the host
    already has loaded in-process."""
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    deps = data.get("project", {}).get("dependencies", [])
    check(
        "pyproject [project].dependencies is empty",
        not deps,
        f"found: {deps}\nThe host provides numpy, scipy, pydantic, fastapi, cv2, "
        f"tifffile, zarr and more. Import them freely, but do not declare them.",
    )


# ─── 2. The package imports with nothing but the stdlib + the SDK ────────────
def check_imports_with_stub_sdk() -> None:
    """Import the plugin with site-packages disabled and only a stub
    imswitch.plugin_sdk on the path. Anything it reaches for beyond the stdlib
    shows up here rather than as a container that will not boot."""
    stub = ROOT / "build" / "_stub"
    (stub / "imswitch" / "plugin_sdk").mkdir(parents=True, exist_ok=True)
    (stub / "imswitch" / "__init__.py").write_text("", encoding="utf-8")
    (stub / "imswitch" / "plugin_sdk" / "__init__.py").write_text(
        '"""Minimal stand-in for the real SDK, for import-time checking only."""\n'
        "from dataclasses import dataclass, field\n"
        "from typing import Any, Callable, Dict, List, Optional\n"
        "\n"
        "SDK_VERSION = '1.0.0'\n"
        "\n"
        "def APIExport(method='GET', path=None):\n"
        "    def deco(fn):\n"
        "        fn.__api_export__ = {'method': method, 'path': path or '/' + fn.__name__}\n"
        "        return fn\n"
        "    return deco\n"
        "\n"
        "class Event:\n"
        "    def __init__(self, name, schema=None):\n"
        "        self.name, self.schema = name, schema or {}\n"
        "    def emit(self, payload): pass\n"
        "\n"
        "class PluginController:\n"
        "    def __init__(self, ctx):\n"
        "        self.ctx = ctx\n"
        "        import logging; self.log = logging.getLogger('stub')\n"
        "    def on_shutdown(self): pass\n"
        "\n"
        "@dataclass\n"
        "class PluginContext:\n"
        "    master: Any = None\n"
        "    setup_info: Any = None\n"
        "    hardware: Any = None\n"
        "    manifest: Any = None\n"
        "\n"
        "@dataclass\n"
        "class PluginRegistration:\n"
        "    manifest: Any\n"
        "    controller_factory: Any\n"
        "    ui_dir: Optional[str] = None\n"
        "\n"
        "def load_manifest(path):\n"
        "    try:\n"
        "        import tomllib\n"
        "    except ModuleNotFoundError:\n"
        "        import tomli as tomllib\n"
        "    with open(str(path), 'rb') as fh:\n"
        "        raw = tomllib.load(fh)\n"
        "    block = raw.get('plugin', {})\n"
        "    class _UI:\n"
        "        def __init__(self, d): self.__dict__.update(d)\n"
        "    class _M:\n"
        "        def __init__(self, d):\n"
        "            self.__dict__.update(d)\n"
        "            self.ui = _UI(d.get('ui', {}))\n"
        "    return _M(block)\n",
        encoding="utf-8",
    )

    # -S drops site-packages, so only the stdlib plus what we put on sys.path
    # is importable. Exactly the situation a bind-mounted plugin is in, minus
    # the host's own libraries.
    code = (
        "import importlib, sys\n"
        f"sys.path.insert(0, r'{stub}')\n"
        f"sys.path.insert(0, r'{ROOT}')\n"
        f"importlib.import_module('{PACKAGE}')\n"
        "print('import-ok')\n"
    )
    proc = subprocess.run(
        [sys.executable, "-S", "-c", code],
        capture_output=True, text=True, cwd=str(ROOT),
    )
    ok = proc.returncode == 0 and "import-ok" in proc.stdout

    detail = ""
    if not ok:
        detail = (proc.stderr or proc.stdout).strip()
        missing = re.search(r"No module named '([^']+)'", detail)
        if missing:
            detail += (
                f"\n\n=> '{missing.group(1)}' is not in the stdlib and not provided "
                f"by the stub SDK. If the host ships it (numpy, cv2, pydantic, ...) "
                f"import it lazily inside a function so this check still passes; "
                f"otherwise vendor it. Do not add it to [project].dependencies."
            )
    check("package imports with only stdlib + plugin_sdk", ok, detail)


# ─── 3. Shared packages are peerDependencies, never dependencies ─────────────
def check_no_shared_in_npm_dependencies() -> None:
    pkg = json.loads((ROOT / "ui-src" / "package.json").read_text(encoding="utf-8"))
    shared = set(load_shared_deps())
    # "react/jsx-runtime" ships inside the react package; it is not installable.
    installable = {name for name in shared if "/" not in name.lstrip("@")}

    deps = set(pkg.get("dependencies", {}))
    offenders = sorted(deps & installable)
    check(
        "no shared package in package.json dependencies",
        not offenders,
        f"{offenders} must move to peerDependencies. A shared package under "
        f"`dependencies` is how a second React reaches the page.",
    )

    peers = set(pkg.get("peerDependencies", {}))
    missing = sorted(installable - peers)
    check(
        "every shared package is declared as a peerDependency",
        not missing,
        f"missing from peerDependencies: {missing}",
    )


# ─── 4. plugin.toml is valid, and agrees with the code ───────────────────────
def check_manifest() -> None:
    manifest_path = ROOT / PACKAGE / "plugin.toml"
    raw = tomllib.loads(manifest_path.read_text(encoding="utf-8"))
    block = raw.get("plugin", {})

    required = ["name", "display_name", "version", "ui"]
    missing = [key for key in required if key not in block]
    check("plugin.toml has the required keys", not missing, f"missing: {missing}")

    ui = block.get("ui", {})
    for key in ("scope", "menu_label"):
        check(f"plugin.toml [plugin.ui].{key} is set", bool(ui.get(key)))

    kinds = {"detector", "positioner", "laser", "recording", "custom"}
    for req in block.get("required_hardware", []):
        check(
            f"required_hardware kind {req.get('kind')!r} is valid",
            req.get("kind") in kinds,
            f"valid kinds: {sorted(kinds)}",
        )

    # If the real SDK is importable, validate against the actual pydantic model
    # rather than this hand-rolled approximation.
    try:
        from imswitch.plugin_sdk import PluginManifest  # noqa: WPS433
        PluginManifest(**block)
        check("plugin.toml validates against the real PluginManifest schema", True)
    except ImportError:
        notes.append(
            "imswitch not installed — validated plugin.toml structurally only. "
            "Install ImSwitch to check it against the real pydantic schema."
        )
    except Exception as exc:
        check("plugin.toml validates against the real PluginManifest schema",
              False, str(exc))

    # The federation scope must match on both sides, or the bundle loads and
    # then registers nothing the shell can find.
    webpack = (ROOT / "ui-src" / "webpack.config.js").read_text(encoding="utf-8")
    scope_in_webpack = re.search(r'const SCOPE = "([^"]+)"', webpack)
    check(
        "plugin.toml scope matches webpack ModuleFederationPlugin name",
        bool(scope_in_webpack) and scope_in_webpack.group(1) == ui.get("scope"),
        f"plugin.toml={ui.get('scope')!r} webpack={scope_in_webpack.group(1) if scope_in_webpack else None!r}",
    )

    exposed_in_webpack = re.search(r'const EXPOSED = "([^"]+)"', webpack)
    check(
        "plugin.toml exposed matches webpack exposes key",
        bool(exposed_in_webpack)
        and exposed_in_webpack.group(1) == ui.get("exposed", "./Widget"),
        f"plugin.toml={ui.get('exposed')!r} webpack={exposed_in_webpack.group(1) if exposed_in_webpack else None!r}",
    )

    # Plugins are discovered by directory scan only. An entry-point declaration
    # would imply a pip-install path the host does not support, and would give a
    # false sense that `pip install` is a deployment option.
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    entry_points = pyproject.get("project", {}).get("entry-points", {})
    check(
        "no imswitch entry-point declaration",
        "imswitch.plugins" not in entry_points
        and "imswitch.implugins" not in entry_points,
        "ImSwitch discovers plugins by scanning the plugin directory. Remove the "
        "entry-point table; deploy with `make dist` instead.",
    )


# ─── 5. The built bundle contains no second React ────────────────────────────
def check_bundle_has_no_react() -> None:
    dist = ROOT / "ui-src" / "dist"
    if not dist.is_dir():
        notes.append("ui-src/dist not built — skipping bundle check. Run `make build`.")
        return

    # Markers that only appear inside React's own source, not in code that
    # merely imports it.
    markers = (
        "react.production.min",
        "__SECRET_INTERNALS_DO_NOT_USE",
        "ReactCurrentDispatcher",
        "createElementWithValidation",
        "react-dom.production.min",
    )
    offenders = []
    for js in sorted(dist.glob("*.js")):
        text = js.read_text(encoding="utf-8", errors="ignore")
        hits = [m for m in markers if m in text]
        if hits:
            offenders.append(f"{js.name}: {hits}")

    check(
        "no React runtime in the emitted bundle",
        not offenders,
        "\n".join(offenders)
        + "\n\n=> React is being bundled instead of shared. Check that "
          "webpack.config.js uses makeShared({ eager: false, fallback: false }) "
          "and that react is not in package.json dependencies.",
    )


# ─── 6. The vendored shared-deps.js has not drifted from the host's ──────────
def check_shared_deps_not_drifted() -> None:
    """The vendored copy must stay byte-identical to ImSwitch's canonical file.

    Checked against a local ImSwitch checkout when one is present (CI clones it);
    otherwise this reports as a note rather than failing, so the template still
    builds standalone.
    """
    vendored = ROOT / "ui-src" / "shared-deps.js"
    candidates = [
        ROOT.parent / "ImSwitch" / "frontend" / "shared-deps.js",
        ROOT / "build" / "imswitch" / "frontend" / "shared-deps.js",
    ]
    host_copy = next((p for p in candidates if p.is_file()), None)

    if host_copy is None:
        notes.append(
            "no ImSwitch checkout found next to this repo — could not diff "
            "ui-src/shared-deps.js against the canonical copy. CI does this."
        )
        return

    check(
        "ui-src/shared-deps.js is identical to ImSwitch's canonical copy",
        vendored.read_bytes() == host_copy.read_bytes(),
        f"drifted from {host_copy}. Re-copy it:\n  cp {host_copy} {vendored}",
    )


# ─── main ────────────────────────────────────────────────────────────────────
def main() -> int:
    print("ImSwitch plugin contract checks\n")
    check_no_runtime_dependencies()
    check_imports_with_stub_sdk()
    check_no_shared_in_npm_dependencies()
    check_manifest()
    check_bundle_has_no_react()
    check_shared_deps_not_drifted()

    if notes:
        print("\nnotes:")
        for note in notes:
            print(f"  - {note}")

    if failures:
        print(f"\n{len(failures)} check(s) failed:")
        for name in failures:
            print(f"  - {name}")
        return 1

    print("\nall contract checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
