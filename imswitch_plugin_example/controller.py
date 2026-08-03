"""
Example plugin controller.

What this file demonstrates:

* Three endpoints — a GET status, a POST that starts work, a GET that returns
  the last result.
* The correct pattern for a long-running operation: hand it to a thread and
  announce completion with an Event. Never block an endpoint on it.
* Hardware reached by role through ``ctx.hardware``, never by device name.

What this file deliberately does NOT do:

* import anything from ``imswitch.imcontrol`` / ``imswitch.imcommon``. The SDK
  is the whole contract. Everything else is host-private and will move.
* import numpy, opencv, pandas, ... Not because you cannot use them — the host
  already provides several — but because adding them to ``dependencies`` breaks
  the bind-mount deployment model. See pyproject.toml.
"""
from __future__ import annotations

import threading
import time
import traceback
from typing import Any, Dict, Optional

from imswitch.plugin_sdk import APIExport, Event, PluginContext, PluginController


class ExampleController(PluginController):
    """One controller per plugin. Instantiated once, at host startup."""

    # ── Declarative events ───────────────────────────────────────────────────
    # Bound by the host to this plugin's Socket.IO namespace ("/plugin/example")
    # when the controller is constructed. Emitting before the socket exists is
    # safe: the event is dropped, not raised.
    sig_job_finished = Event(
        "job_finished",
        schema={"job_id": "str", "duration_s": "float", "value": "float"},
    )

    def __init__(self, ctx: PluginContext) -> None:
        super().__init__(ctx)

        # Optional hardware: the manifest marks the camera optional, so the
        # binding may legitimately be absent. Probe rather than assume.
        self._camera = None
        try:
            self._camera = ctx.hardware.detector("camera")
        except KeyError:
            self.log.info("no camera bound; running without frame access")

        self._lock = threading.Lock()
        self._last_result: Optional[Dict[str, Any]] = None
        self._busy = False

        self.log.info(
            "example plugin ready (camera=%s)",
            self._camera.name if self._camera else "none",
        )

    # ── Endpoints ────────────────────────────────────────────────────────────
    # Mounted at /imswitch/plugin/<name>/api/<function-name>.
    #
    # A note on threading: the host builds these routes with
    # router.add_api_route(path, fn), so a plain `def` handler runs in FastAPI's
    # threadpool rather than on the event loop. That means a slow handler will
    # not stall the whole server — but it does hold one of a small number of
    # worker threads for as long as it runs. Anything longer than about a
    # second belongs in a thread of your own, as start_job() does below.

    @APIExport()
    def status(self) -> Dict[str, Any]:
        """Cheap, always-safe health probe. Good first thing to curl."""
        with self._lock:
            return {
                "plugin": "example",
                "version": "0.1.0",
                "busy": self._busy,
                "camera": self._camera.name if self._camera else None,
                "has_result": self._last_result is not None,
            }

    @APIExport(method="POST")
    def start_job(self, duration_s: float = 2.0) -> Dict[str, Any]:
        """Kick off a long-running job and return IMMEDIATELY.

        This is the pattern to copy. The endpoint's job is to validate, start
        the work, and hand back a handle. The frontend then either polls
        ``get_result`` or — better — listens for ``job_finished`` on the
        plugin's socket namespace.
        """
        with self._lock:
            if self._busy:
                return {"started": False, "reason": "a job is already running"}
            self._busy = True

        job_id = f"job-{int(time.time() * 1000)}"
        thread = threading.Thread(
            target=self._run_job,
            args=(job_id, float(duration_s)),
            name=f"example-plugin-{job_id}",
            daemon=True,  # never block host shutdown on plugin work
        )
        thread.start()
        return {"started": True, "job_id": job_id}

    @APIExport()
    def get_result(self) -> Dict[str, Any]:
        """Return the most recent job result, or nulls if there is none yet."""
        with self._lock:
            return self._last_result or {"job_id": None, "value": None}

    # ── Worker ───────────────────────────────────────────────────────────────
    def _run_job(self, job_id: str, duration_s: float) -> None:
        started = time.time()
        try:
            # Stand-in for real work. If you have a camera bound, this is where
            # you would grab frames:
            #     frame = self._camera.get_latest_frame()
            time.sleep(max(0.0, min(duration_s, 30.0)))
            value = float(duration_s)

            result = {
                "job_id": job_id,
                "duration_s": time.time() - started,
                "value": value,
            }
            with self._lock:
                self._last_result = result

            # Tell the frontend. Emitting is fire-and-forget and never raises.
            self.sig_job_finished.emit(result)

        except Exception:
            # A plugin runs inside the host process. Swallow and log rather than
            # letting an exception escape a thread you own.
            self.log.error("job %s failed:\n%s", job_id, traceback.format_exc())
        finally:
            with self._lock:
                self._busy = False

    # ── Lifecycle ────────────────────────────────────────────────────────────
    def on_shutdown(self) -> None:
        """Called by the host when ImSwitch stops. Release things here."""
        self.log.info("example plugin shutting down")
