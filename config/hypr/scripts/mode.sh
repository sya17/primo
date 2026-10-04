#!/usr/bin/env bash
# Entry point for modes: mode.sh [menu | start ID [FOLDER] | end | status | list]
exec python3 "$(cd "$(dirname "$0")" && pwd)/modes.py" "$@"
