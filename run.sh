#!/usr/bin/env bash
# Script to launch the POTA Prop GUI

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

# Check for virtual environment
if [ -f "$DIR/.venv/bin/python3" ]; then
    PYTHON_BIN="$DIR/.venv/bin/python3"
elif [ -f "$DIR/venv/bin/python3" ]; then
    PYTHON_BIN="$DIR/venv/bin/python3"
elif [ -f "$HOME/py_env/bin/python3" ]; then
    PYTHON_BIN="$HOME/py_env/bin/python3"
else
    PYTHON_BIN="$(which python3)"
fi

exec "$PYTHON_BIN" "$DIR/pota_prop.py" "$@"
