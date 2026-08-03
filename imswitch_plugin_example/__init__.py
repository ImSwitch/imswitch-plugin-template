"""
imswitch_plugin_example
=======================

Template for an ImSwitch v2 plugin. Rename this package to
``imswitch_plugin_<yours>`` and work outwards from :func:`register`.

The host only ever calls one thing in here: ``register(ctx)``. Everything else
is yours.
"""
from importlib.resources import files

from imswitch.plugin_sdk import (
    PluginContext,
    PluginRegistration,
    load_manifest,
)

from .controller import ExampleController

__version__ = "0.1.0"


def register(ctx: PluginContext) -> PluginRegistration:
    """Entry point the host's PluginManager calls once at startup.

    Keep this cheap and deterministic, and do NOT touch hardware here. The host
    calls ``register()`` before it has checked whether your ``required_hardware``
    can be satisfied; hardware access belongs in the controller's ``__init__``,
    which only runs once the host has confirmed the manifest and resolved every
    role.
    """
    manifest = load_manifest(files(__package__).joinpath("plugin.toml"))

    # Resolve the built frontend bundle. importlib.resources is the right answer
    # for an installed wheel, but it behaves differently for a package imported
    # from a path (which is what a bind-mounted plugin is). Rather than special-
    # casing that here, hand the host None when it does not resolve: it falls
    # back to <package dir>/<manifest.ui.dist_dir>, so the same code works
    # whether the plugin was pip-installed or dropped into a mounted directory.
    ui_dir = files(__package__).joinpath(manifest.ui.dist_dir)
    try:
        resolved_ui = str(ui_dir) if ui_dir.is_dir() else None
    except Exception:
        resolved_ui = None

    return PluginRegistration(
        manifest=manifest,
        controller_factory=ExampleController,
        ui_dir=resolved_ui,
    )
