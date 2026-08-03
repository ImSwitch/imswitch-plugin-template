/**
 * Widget.jsx — the plugin's UI.
 *
 * This file is the point of the whole shared-runtime arrangement. Note what it
 * does NOT do:
 *
 *   * It does not take the backend URL from a prop it then string-concatenates.
 *   * It does not take `theme` as a prop.
 *   * It does not import React from its own bundle — there is only one React on
 *     the page, the host's.
 *   * It does not open its own socket.
 *
 * Everything arrives through context, because react-redux and @mui/material are
 * Module Federation singletons shared with the host. See ../shared-deps.js.
 */
import React, { useCallback, useEffect, useState } from "react";
import { useDispatch, useSelector } from "react-redux";
import { createSlice } from "@reduxjs/toolkit";
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Paper,
  Stack,
  Typography,
  useTheme,
} from "@mui/material";

// The host exposes its store so a plugin can own a slice of application state.
// This import resolves through the `host_app` remote declared in
// webpack.config.js — it is the host's real store, not a copy.
import store from "host_app/store";

// ─────────────────────────────────────────────────────────────────────────────
//  A plugin-owned Redux slice.
//
//  injectReducer returns false if the key is already taken (first registration
//  wins). Injected slices are NOT persisted across page reloads — that is a
//  deliberate limitation of the host, not an oversight. Keep durable state on
//  your backend.
// ─────────────────────────────────────────────────────────────────────────────
const exampleSlice = createSlice({
  name: "examplePluginState",
  initialState: { runCount: 0 },
  reducers: {
    jobStarted: (state) => {
      state.runCount += 1;
    },
  },
});
const { jobStarted } = exampleSlice.actions;

store.injectReducer("examplePluginState", exampleSlice.reducer);

// ─────────────────────────────────────────────────────────────────────────────
export default function Widget(props) {
  // The shell passes `apiBase` from this plugin's own manifest entry. Use it
  // as given. Do not rebuild it from hostIP/hostPort: the real URL carries the
  // host's root_path ("/imswitch"), which the plugin cannot know, and guessing
  // wrong produces a silent 404.
  const { apiBase } = props;

  // The host's MUI theme, including the user's light/dark choice. If this ever
  // returns the default MUI palette instead, @mui/material is not actually
  // being shared — check the `shared` block before debugging anything else.
  const theme = useTheme();

  // The host's Redux store. No props, no bridge object.
  const connection = useSelector((s) => s.connectionSettingsState);
  const runCount = useSelector((s) => s.examplePluginState?.runCount ?? 0);
  const dispatch = useDispatch();

  const [status, setStatus] = useState(null);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  const call = useCallback(
    async (path, { method = "GET", body } = {}) => {
      const res = await fetch(`${apiBase}${path}`, {
        method,
        headers: body ? { "Content-Type": "application/json" } : undefined,
        body: body ? JSON.stringify(body) : undefined,
      });
      if (!res.ok) throw new Error(`${method} ${path} → ${res.status}`);
      return res.json();
    },
    [apiBase],
  );

  const refresh = useCallback(async () => {
    try {
      setStatus(await call("/status"));
      setError(null);
    } catch (e) {
      setError(e.message);
    }
  }, [call]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const startJob = async () => {
    setBusy(true);
    setError(null);
    try {
      dispatch(jobStarted());
      await call("/start_job?duration_s=2", { method: "POST" });
      // The endpoint returns immediately; the work runs in a thread on the
      // backend. A production plugin should listen for the `job_finished`
      // event on its socket namespace instead of polling like this.
      setTimeout(async () => {
        try {
          setResult(await call("/get_result"));
        } catch (e) {
          setError(e.message);
        } finally {
          setBusy(false);
          refresh();
        }
      }, 2500);
    } catch (e) {
      setError(e.message);
      setBusy(false);
    }
  };

  return (
    <Box sx={{ p: 3 }}>
      <Typography variant="h5" gutterBottom>
        Example Plugin
      </Typography>

      {error && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {error}
        </Alert>
      )}

      <Paper sx={{ p: 2, mb: 2 }}>
        <Typography variant="subtitle2" gutterBottom>
          Proof the host runtime is shared
        </Typography>
        <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
          <Chip label={`theme: ${theme.palette.mode}`} />
          <Chip label={`backend: ${connection?.ip ?? "unknown"}`} />
          <Chip label={`plugin slice runCount: ${runCount}`} />
        </Stack>
        <Typography variant="caption" color="text.secondary" sx={{ mt: 1, display: "block" }}>
          The theme comes from the host's ThemeProvider, the backend URL from the
          host's Redux store, and runCount from a slice this plugin injected —
          none of them passed as props.
        </Typography>
      </Paper>

      <Paper sx={{ p: 2 }}>
        <Typography variant="subtitle2" gutterBottom>
          Backend
        </Typography>
        <Typography variant="body2" component="pre" sx={{ whiteSpace: "pre-wrap" }}>
          {JSON.stringify(status, null, 2)}
        </Typography>

        <Stack direction="row" spacing={1} sx={{ mt: 2 }} alignItems="center">
          <Button variant="contained" onClick={startJob} disabled={busy}>
            Start 2s job
          </Button>
          <Button onClick={refresh} disabled={busy}>
            Refresh
          </Button>
          {busy && <CircularProgress size={20} />}
        </Stack>

        {result && (
          <Typography variant="body2" component="pre" sx={{ mt: 2, whiteSpace: "pre-wrap" }}>
            {JSON.stringify(result, null, 2)}
          </Typography>
        )}
      </Paper>
    </Box>
  );
}
