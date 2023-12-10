#!/bin/bash
set -e

echo "Info: Creating venv..."
rm -rf tmp.dev.venv

/usr/bin/python3 -m venv tmp.dev.venv --upgrade-deps

echo "Info: Installing development libs into venv..."
PY=${PWD}/tmp.dev.venv/bin/python
tmp.dev.venv/bin/python -m pip install --quiet \
    pymodbus

set -x
PYTHONPATH=src \${PY} -m prometheus_givenergy "$@"
