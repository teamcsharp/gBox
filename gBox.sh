#!/usr/bin/env bash
# gBox setup / deploy / troubleshoot wizard. Linux, or Windows via Git Bash.
#   ./gBox.sh                 open the wizard in your browser (http://127.0.0.1:8770)
#   ./gBox.sh --no-browser    print the URL instead
# First run: finds Python 3.11+, creates a per-OS virtualenv under system/, installs gBox into it.
set -euo pipefail
cd "$(dirname "$0")/system"

py=""
for c in python3.12 python3.11 python3 python py; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null; then py="$c"; break; fi
done
if [ -z "$py" ]; then
  echo "gBox needs Python 3.11 or newer."
  case "$(uname -s)" in
    Linux*) echo "  Debian/Ubuntu: sudo apt install python3 python3-venv" ;;
    MINGW*|MSYS*|CYGWIN*) echo "  Windows: winget install Python.Python.3.12" ;;
  esac
  exit 1
fi

case "$(uname -s)" in
  MINGW*|MSYS*|CYGWIN*)   # Windows can't build a venv on a network share: keep it on the local disk (shared with the desktop app)
    venv="$(cygpath -u "${LOCALAPPDATA:-$HOME/AppData/Local}")/gbox/venv"; vpy="$venv/Scripts/python.exe" ;;
  *) venv=".venv-linux-$(uname -m)"; vpy="$venv/bin/python" ;;
esac
if [ ! -x "$vpy" ]; then
  echo "Creating $venv ..."
  "$py" -m venv "$venv"
fi
if ! "$vpy" -c 'import gbox, fastapi' >/dev/null 2>&1; then
  echo "Installing gBox into $venv ..."
  "$vpy" -m pip install --quiet --upgrade pip
  "$vpy" -m pip install --quiet -e .
fi
[ -f gbox.toml ] || "$vpy" -m gbox init
exec "$vpy" -m gbox --config gbox.toml wizard "$@"
