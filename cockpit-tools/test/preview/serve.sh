#!/usr/bin/env bash
# Startet die Seite ohne Roboter: baut einen Baum, in dem die echte
# index.html neben einer cockpit.js-Attrappe liegt, und liefert ihn aus.
#
#   test/preview/serve.sh [PORT]
#   -> http://localhost:8099/robot-tools/index.html?state=exited
set -euo pipefail

PORT="${1:-8099}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PKG="$(cd "${HERE}/../.." && pwd)"
ROOT="$(mktemp -d)"

mkdir -p "${ROOT}/base1"
cp "${HERE}/base1/cockpit.js" "${ROOT}/base1/cockpit.js"
ln -s "$PKG" "${ROOT}/robot-tools"

echo "Vorschau: http://localhost:${PORT}/robot-tools/index.html"
echo "Szenarien: ?state=running|exited|paused|restarting|dead|missing|error"
trap 'rm -rf "$ROOT"' EXIT
cd "$ROOT"
exec python3 -m http.server "$PORT"
