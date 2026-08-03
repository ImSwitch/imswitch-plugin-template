# ─────────────────────────────────────────────────────────────────────────────
#  Plugin delivery image.
#
#  This image contains ONLY the plugin tree — no Python, no OS, no ImSwitch.
#  The final stage is FROM scratch, so it is a few hundred KB and cannot run
#  anything. It is a *payload*, not a service.
#
#  Two ways to use it:
#
#  (a) Extract a directory to bind-mount (no registry needed):
#        docker build --output type=local,dest=./out .
#        rsync -a ./out/plugin/ pi@microscope:/home/pi/ImSwitchPlugins/example/
#
#  (b) Use it as a versioned volume source in compose, so the plugin is pinned
#      by digest alongside the ImSwitch image:
#        plugin-example:
#          image: ghcr.io/openuc2/imswitch-plugin-example:0.1.0
#          volumes: [ plugins:/out ]
#          command: sh -c "cp -a /plugin /out/example"
#      with the server depending on it via service_completed_successfully.
#      See ImSwitch's docs/plugins/DEPLOYMENT.md for the full compose snippet.
#
#  Use (a) while developing on one machine; use (b) for a fleet, where you want
#  the plugin version recorded in the same file as everything else.
# ─────────────────────────────────────────────────────────────────────────────

# ── Stage 1: build the federated frontend ────────────────────────────────────
FROM node:20-alpine AS ui
WORKDIR /build

# Copy manifests first so this layer caches across source-only changes.
COPY ui-src/package.json ui-src/package-lock.json* ./
RUN npm install --no-audit --no-fund

COPY ui-src/ ./
RUN npm run build


# ── Stage 2: assemble the plugin tree ────────────────────────────────────────
FROM alpine:3.20 AS assemble
WORKDIR /out

# The Python package, minus anything that should never ship.
COPY imswitch_plugin_example/ /out/plugin/imswitch_plugin_example/
RUN find /out -name '__pycache__' -type d -prune -exec rm -rf {} + \
 && find /out -name '*.pyc' -delete \
 && rm -rf /out/plugin/imswitch_plugin_example/ui/dist

# The built bundle, at exactly the path plugin.toml's dist_dir names.
COPY --from=ui /build/dist/ /out/plugin/imswitch_plugin_example/ui/dist/

# Fail the build rather than shipping a plugin with no frontend.
RUN test -f /out/plugin/imswitch_plugin_example/ui/dist/remoteEntry.js \
 || (echo "ERROR: remoteEntry.js missing — the UI build produced nothing" && exit 1)


# ── Stage 3: the payload ─────────────────────────────────────────────────────
FROM scratch
COPY --from=assemble /out/plugin /plugin
