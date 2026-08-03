# ImSwitch plugin template

A working ImSwitch v2 plugin: one Python controller, one React widget, no extra
dependencies. Clone it, rename it, and you have a plugin that drops into a
running ImSwitch container without rebuilding or reinstalling anything.

```bash
git clone https://github.com/openUC2/imswitch-plugin-template my-plugin
cd my-plugin
make install-ui
make build check
```

> No `make` (e.g. stock Windows)? Every target is two or three commands —
> the bash and PowerShell equivalents are in
> [DEPLOYMENT.md §9](https://github.com/openuc2/ImSwitch/blob/master/docs/plugins/DEPLOYMENT.md#9-building-a-plugin-without-make).
> To develop against ImSwitch running natively rather than in Docker, see
> [§8](https://github.com/openuc2/ImSwitch/blob/master/docs/plugins/DEPLOYMENT.md#8-running-without-docker-native-development).

## What you get

Your plugin's backend appears at `/imswitch/plugin/<name>/api/…`, its widget in
the ImSwitch sidebar, and that widget renders inside the host's React tree — so
it uses the host's MUI theme, the host's Redux store and the host's socket
connection, with no props and no bridge object.

## The five-minute version

1. **Rename.** `imswitch_plugin_example/` → `imswitch_plugin_<you>/`, then update
   `name`/`scope` in `plugin.toml`, `PACKAGE`/`PLUGIN_NAME` in the `Makefile`,
   `SCOPE` in `ui-src/webpack.config.js`, and the package name and entry point in
   `pyproject.toml`. `make check` tells you if you missed one.
2. **Write the backend.** `imswitch_plugin_<you>/controller.py`. Endpoints are
   methods with `@APIExport()`.
3. **Write the frontend.** `ui-src/src/Widget.jsx`.
4. **Ship it.**
   ```bash
   make dist
   rsync -a dist/<name> pi@microscope:/home/pi/ImSwitchPlugins/
   ```
   Add `"<name>"` to `availableWidgets` in the instrument's setup file, then
   `docker compose restart server`.

Full walkthrough: [docs/WRITING_A_PLUGIN.md](docs/WRITING_A_PLUGIN.md).

## Layout

```
imswitch_plugin_example/     the Python package the host imports
  __init__.py                register(ctx) — the single entry point
  controller.py              your endpoints and events
  plugin.toml                the manifest; read before any of your code runs
  ui/dist/                   built bundle lands here (gitignored)
ui-src/                      frontend sources
  src/Widget.jsx             your widget
  src/index.js               async boundary — leave it alone
  webpack.config.js          Module Federation config
  shared-deps.js             VERBATIM copy of ImSwitch's; do not edit
scripts/check_contract.py    what `make check` and CI run
Dockerfile                   plugin-as-a-payload image (FROM scratch)
```

## The three rules

Everything in `make check` reduces to these. Each one exists because breaking it
produces a failure that is genuinely hard to diagnose later.

1. **Import only `imswitch.plugin_sdk`.** Everything else in ImSwitch is
   host-private and will move without notice.

2. **Declare no runtime dependencies.** `[project].dependencies` stays empty. A
   plugin is bind-mounted and imported from `sys.path`; nothing gets installed.
   The host already provides numpy, scipy, pydantic, fastapi, cv2, tifffile,
   zarr and more — import them, just do not declare them. A second NumPy in one
   process gives wrong answers rather than a clean crash.

3. **Shared frontend packages are `peerDependencies`, never `dependencies`.**
   React, MUI, Redux and friends come from the host at runtime. Bundling your
   own copy of React produces an "invalid hook call" error that says nothing
   about Module Federation, and costs an afternoon.

## Troubleshooting

| Symptom | First thing to check |
|---|---|
| Plugin absent from `/imswitch/api/plugins` | Is the directory mounted? `docker compose exec server ls /opt/imswitch/plugins` |
| Present, `status: "disabled"` | Its `name` is not in `availableWidgets` in the setup file |
| In the list but not in the sidebar | It has no `remote_entry` — the UI was never built into `<package>/ui/dist` |
| Sidebar entry shows an error card | Read the message; it names the URL and the reason |
| "did not register federation scope" | `[plugin.ui].scope` ≠ `SCOPE` in `webpack.config.js` |
| Invalid hook call on mount | You bundled React. `make check` catches this |
| Theme looks wrong | `@mui/material` is not being shared — check `package.json` |

More detail, including the exact command for each row:
[docs/WRITING_A_PLUGIN.md](docs/WRITING_A_PLUGIN.md#troubleshooting).

## License

MIT.
