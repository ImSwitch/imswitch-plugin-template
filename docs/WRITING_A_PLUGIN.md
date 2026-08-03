# Writing an ImSwitch plugin

Everything here assumes you cloned
[imswitch-plugin-template](https://github.com/openUC2/imswitch-plugin-template).

---

## 1. Quickstart

```bash
git clone https://github.com/openUC2/imswitch-plugin-template my-plugin
cd my-plugin
make install-ui        # npm install for the frontend
make build             # builds the widget into the Python package
make check             # the contract checks CI also runs
make dist              # dist/<name>/ — ready to bind-mount
```

Then, on the microscope:

```bash
rsync -a dist/example pi@microscope:/home/pi/ImSwitchPlugins/
```

Add the plugin's `name` to `availableWidgets` in the instrument's setup file,
restart (`docker compose restart server`), and confirm:

```bash
curl http://microscope:8001/imswitch/api/plugins
```

### Renaming

Five names must agree. `make check` verifies four of them, so run it after you
rename:

| What | Where |
|---|---|
| package directory | `imswitch_plugin_example/` |
| `[plugin].name` | `plugin.toml` — becomes the URL segment `/imswitch/plugin/<name>/` |
| `[plugin.ui].scope` | `plugin.toml`, must equal `SCOPE` in `ui-src/webpack.config.js` |
| `PACKAGE`, `PLUGIN_NAME` | `Makefile` |
| package + entry point | `pyproject.toml` |

---

## 2. The hardware role model

A plugin never names a device. It declares a **role** and the host binds a
concrete device to it before your controller is constructed:

```toml
[[plugin.required_hardware]]
kind     = "detector"
role     = "camera"
optional = true
```

```python
camera = ctx.hardware.detector("camera")
frame  = camera.get_latest_frame()
```

`kind` is one of `detector`, `positioner`, `laser`, `recording`, `custom`.

The host resolves each role in this order:

1. `plugin_bindings["<kind>:<role>"]` in the setup file — explicit, and what you
   should use in production.
2. `setupInfo.<plugin-name>.<role>` — a legacy alias.
3. **The first available device of that kind.** Convenient while developing,
   surprising on a multi-camera instrument. Do not rely on it in production; it
   may end up behind a host flag.

`optional = true` means the plugin still loads when the role cannot be filled —
`ctx.hardware.detector(...)` then raises `KeyError`, so probe for it:

```python
try:
    self._camera = ctx.hardware.detector("camera")
except KeyError:
    self._camera = None
```

With `optional = false` an unfillable role is reported as a load **error** in
`/imswitch/api/plugins` and the controller is never constructed. That is the
right setting once your plugin genuinely cannot function without the device.

---

## 3. Endpoints and the event model

### Endpoints

```python
@APIExport()                 # GET  /imswitch/plugin/<name>/api/status
def status(self): ...

@APIExport(method="POST")    # POST /imswitch/plugin/<name>/api/start_job
def start_job(self, duration_s: float = 2.0): ...
```

Handlers are plain `def`, so FastAPI runs them in its threadpool rather than on
the event loop. A slow handler will not stall the server — but it does occupy
one of a small number of worker threads for as long as it runs. **Anything
longer than about a second belongs in your own thread.**

### Events

Long work should not be polled. Declare an event, emit it on completion:

```python
class MyController(PluginController):
    sig_job_finished = Event("job_finished", schema={"value": "float"})

    def _worker(self):
        ...
        self.sig_job_finished.emit({"value": 42.0})
```

The host binds the event to your plugin's Socket.IO namespace
(`/plugin/<name>`) when the controller is constructed. Emitting when no socket
exists is a no-op, never an exception — so an event in a background thread can
never take the controller down.

### The rule for long-running work

```python
@APIExport(method="POST")
def start_job(self):
    if self._busy:
        return {"started": False, "reason": "already running"}
    self._busy = True
    threading.Thread(target=self._worker, daemon=True).start()
    return {"started": True, "job_id": job_id}   # returns immediately
```

`daemon=True` matters: a non-daemon thread blocks host shutdown, and the
microscope stops responding to `docker compose restart`.

---

## 4. The dependency contract, and why it exists

**`[project].dependencies` must stay empty.**

A plugin is delivered as a directory bind-mounted into the ImSwitch container
and imported from `sys.path`. There is no `pip install` step, so anything you
declare is not installed anyway. Worse: if someone *does* pip-install your
plugin, each declared dependency risks resolving to a **second copy** of a
library the host already has loaded. Two NumPys in one process do not crash —
they silently disagree, and you get wrong numbers off a microscope.

The host already provides, and you may import freely:

> numpy, scipy, pydantic, fastapi, starlette, uvicorn, opencv (`cv2`),
> tifffile, zarr, h5py, Pillow, requests, python-socketio, imswitch

Need something else?

1. Vendor it (small, pure-Python only), or
2. Open an issue against ImSwitch to add it to the host image.

Adding it to `dependencies` is not an option; `make check` fails the build.

### The frontend half of the same rule

React, MUI, Redux, Emotion, socket.io-client and notistack come from the host at
runtime through the Module Federation share scope. In `ui-src/package.json` they
are **`peerDependencies`**, never `dependencies`.

Two settings in `webpack.config.js` enforce it structurally:

- `eager: false` — the host is the eager provider. `eager: true` in a remote
  pulls a second React into your bundle.
- `fallback: false` (webpack's `import: false`) — without this, webpack also
  emits a *local copy* of each shared package "just in case". That copy is the
  duplicate-React bug, merely deferred to runtime. With it off, your plugin
  fails loudly at load if the host is missing something, and the shell shows
  that error.

`ui-src/shared-deps.js` is a verbatim copy of ImSwitch's
`frontend/shared-deps.js`. Do not edit it; CI diffs the two.

---

## 5. What the widget gets for free

Because those packages are singletons shared with the host, your widget renders
*inside* the host's `<Provider>` and `<ThemeProvider>`:

```jsx
const theme      = useTheme();                                  // host's theme
const connection = useSelector((s) => s.connectionSettingsState); // host's store
const dispatch   = useDispatch();
```

No props. No bridge object. No import from the host.

The one thing you should take from props is the **backend URL**:

```jsx
export default function Widget({ apiBase }) {
  fetch(`${apiBase}/status`);
}
```

`apiBase` comes from your own manifest entry and already carries the host's
`root_path` (`/imswitch`). Do not rebuild it from `hostIP`/`hostPort` — those
props are deprecated, and a hand-built URL misses the prefix and 404s silently.

### Owning Redux state

```jsx
import store from "host_app/store";

store.injectReducer("myPluginState", myReducer);
```

First registration of a key wins; a second returns `false`. **Injected slices
are not persisted across reloads** — that is a deliberate host limitation, not
an oversight. Keep durable state on your backend.

### Host contexts

```jsx
import { useWebSocket } from "host_app/contexts";
```

Gives you the host's already-connected Socket.IO client. Never open your own.

---

## 6. Developing against a running ImSwitch

### Running ImSwitch natively (no Docker)

The tightest loop is to run ImSwitch from a Python environment on your own
machine and point it at your checkout, so there is no container, no image
rebuild and no copying.

Two things to know before you start:

1. The plugin directory defaults to `/opt/imswitch/plugins` — a **container**
   path that does not exist on Windows or macOS. You must set
   `IMSWITCH_PLUGIN_DIR`.
2. Your package must sit **one level below** the plugin directory
   (`<plugin-dir>/<package>/__init__.py` or `<plugin-dir>/src/<package>/...`),
   not directly in it.

```bash
export IMSWITCH_PLUGIN_DIR=~/ImSwitchPlugins           # macOS / Linux
ln -s ~/code/my-plugin ~/ImSwitchPlugins/my-plugin     # edit in place
```
```powershell
$env:IMSWITCH_PLUGIN_DIR = "$env:USERPROFILE\ImSwitchPlugins"   # Windows
New-Item -ItemType Junction `
  -Path "$env:USERPROFILE\ImSwitchPlugins\my-plugin" `
  -Target "$env:USERPROFILE\code\my-plugin"
```

Then run ImSwitch (`uv run python main.py --headless --http-port 8001`) and
check `curl http://localhost:8001/imswitch/api/plugins`.

Full per-OS instructions, including persistent environment variables, the
layouts that do and do not work, and how to get the frontend served natively on
Windows: **[ImSwitch docs/plugins/DEPLOYMENT.md §8](https://github.com/openuc2/ImSwitch/blob/master/docs/plugins/DEPLOYMENT.md#8-running-without-docker-native-development)**.

Python does not hot-reload: restart ImSwitch after a backend change.

### Frontend-only iteration

The fast loop is to point a webpack dev server at a real backend.

```bash
cd ui-src && npm run dev     # serves on :3102
```

Then in `webpack.config.js`, temporarily point the host remote at the machine
running ImSwitch:

```js
remotes: { host_app: "host_app@http://microscope:8001/imswitch/ui/remoteEntry.js" }
```

The slower but more faithful loop — and the one to use before you ship — is to
mount the plugin into the container and let the real shell load it:

```bash
make dist
rsync -a dist/example pi@microscope:/home/pi/ImSwitchPlugins/
ssh pi@microscope docker compose restart server
```

Watching the load happen:

```bash
docker compose logs -f server | grep -i plugin
```

The startup summary prints one line per plugin with its status and source path,
which is the fastest way to tell a bad mount from a bad manifest.

---

## 7. Troubleshooting

| Symptom | Diagnose with | Usual cause |
|---|---|---|
| Not in `/imswitch/api/plugins` at all | `docker compose exec server ls -la /opt/imswitch/plugins` | Directory not mounted, or the plugin dir does not contain a Python package |
| Listed with `status: "disabled"` | read the entry's `reason` field | Its `name` is not in `availableWidgets` in the setup file |
| Listed in `errors` | read the `error` string | Manifest parse failure, unmet non-optional hardware, or a duplicate plugin name |
| Loaded, but not in the sidebar | check `remote_entry` is not `null` | The UI was never built into `<package>/ui/dist`. Run `make build` |
| Sidebar entry hangs | it should not — you would see an error card after 10s | If it really hangs, the shell is older than WP4 |
| "script could not be fetched (network/404)" | `curl http://host:8001<remote_entry>` | `dist_dir` in the manifest does not match where the bundle actually is |
| "did not register federation scope X" | compare `plugin.toml` and `webpack.config.js` | `[plugin.ui].scope` ≠ `SCOPE`. `make check` catches this |
| "does not expose ./Widget" | check `exposes` in `webpack.config.js` | `[plugin.ui].exposed` ≠ the key in `exposes` |
| Invalid hook call / "Rendered more hooks than…" | `make check` | You bundled React. Check `package.json` `dependencies` and `eager`/`fallback` |
| `useSelector` throws "could not find store" | as above | `react-redux` is not being shared |
| Theme is wrong (light in a dark app) | `useTheme().palette.mode` in the widget | `@mui/material` is not being shared |
| Endpoints 404 but the widget loads | `curl <api_base>/status` | You built the URL by hand and dropped the `/imswitch` prefix — use the `apiBase` prop |

### The one-command health check

```bash
curl -s http://microscope:8001/imswitch/api/plugins | python -m json.tool
```

Every diagnosis above starts here. `status`, `reason`, `remote_entry` and
`api_base` between them explain almost every failure.
