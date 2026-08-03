# ImSwitch plugin template — build entry points.
#
#   make build   build the UI and place it inside the Python package
#   make check   run the contract checks (same ones CI runs)
#   make dist    produce dist/<name>/ ready to bind-mount into the container
#   make clean   remove build artefacts
#
# Rename PACKAGE and PLUGIN_NAME when you fork this template. `make check`
# verifies they agree with plugin.toml.

PACKAGE     := imswitch_plugin_example
PLUGIN_NAME := example

PYTHON ?= python
NPM    ?= npm

.PHONY: all build ui check dist clean install-ui

all: build check

install-ui:
	cd ui-src && $(NPM) install

## Build the federated frontend and drop it where the manifest expects it
## ($(PACKAGE)/ui/dist, i.e. [plugin.ui].dist_dir).
build: ui

ui:
	cd ui-src && $(NPM) run build
	rm -rf $(PACKAGE)/ui/dist
	mkdir -p $(PACKAGE)/ui
	cp -r ui-src/dist $(PACKAGE)/ui/dist
	@echo "built bundle -> $(PACKAGE)/ui/dist"

## Everything CI enforces, runnable before you push.
check:
	$(PYTHON) scripts/check_contract.py

## A directory tree ready to bind-mount at $IMSWITCH_PLUGIN_DIR.
##
## Layout matters: the host scans immediate children of the plugin directory
## and imports the Python package it finds inside each one. So the plugin gets
## its own directory, containing the package.
dist: build
	rm -rf dist
	mkdir -p dist/$(PLUGIN_NAME)
	cp -r $(PACKAGE) dist/$(PLUGIN_NAME)/$(PACKAGE)
	find dist -name '__pycache__' -type d -prune -exec rm -rf {} +
	@echo
	@echo "dist/ is ready. Deploy with:"
	@echo "  rsync -a dist/$(PLUGIN_NAME) pi@microscope:/home/pi/ImSwitchPlugins/"
	@echo "  # then add \"$(PLUGIN_NAME)\" to availableWidgets in the setup file"
	@echo "  # and: docker compose restart server"

clean:
	rm -rf dist build ui-src/dist $(PACKAGE)/ui/dist
	find . -name '__pycache__' -type d -prune -exec rm -rf {} +
