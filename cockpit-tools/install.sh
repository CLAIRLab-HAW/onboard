#!/usr/bin/env bash
# Installs the Cockpit page "Robot tools" into
# /usr/local/share/cockpit/robot-tools.
#
# Why /usr/local and not /usr/share: Cockpit searches in the order
# ~/.local/share/cockpit, /etc/cockpit, /usr/local/share/cockpit,
# /usr/share/cockpit. /usr/local is ours, apt does not touch it -- and the
# removal is an rm -rf of the target directory, not an apt operation.
#
#   sudo ./install.sh              # install/update
#   sudo ./install.sh --uninstall  # remove again
#
# Afterwards a browser reload on http://<robot>:9090 is enough -- Cockpit
# re-reads the packages on every page load, no service restart needed.
set -euo pipefail

PREFIX="${PREFIX:-/usr/local}"
DEST="${PREFIX}/share/cockpit/robot-tools"
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Only these files belong in the package. package.json and test/ are tooling
# for the workstation (node --test) and have no business on the robot.
FILES=(manifest.json index.html index.js status.js style.css theme.js)

if [ "${1:-}" = "--uninstall" ]; then
    rm -rf "$DEST"
    echo "removed: $DEST"
    exit 0
fi

for f in "${FILES[@]}"; do
    [ -f "${SRC}/${f}" ] || { echo "ERROR: ${SRC}/${f} is missing." >&2; exit 1; }
done

if ! command -v cockpit-bridge >/dev/null 2>&1; then
    echo "WARN: cockpit-bridge not found -- the page becomes visible only after"
    echo "      Cockpit is installed."
fi

# Clear out the old contents, so that deleted files do not linger.
rm -rf "$DEST"

# No id test, but the attempt itself: this way the script can also be checked
# against a PREFIX in one's own directory, and the error message comes from
# the place where it really gets stuck.
if ! install -d -m 0755 "$DEST" 2>/dev/null; then
    echo "ERROR: ${DEST} cannot be created -- call this with sudo" >&2
    echo "       (or set PREFIX=~/.local, Cockpit looks there first)." >&2
    exit 1
fi

for f in "${FILES[@]}"; do
    install -m 0644 "${SRC}/${f}" "${DEST}/${f}"
done

# Only as root: otherwise the package would belong to the caller, which is not
# how it should be under /usr/local.
[ "$(id -u)" -eq 0 ] && chown -R root:root "$DEST"

echo "installed: $DEST"
echo "Reload Cockpit in the browser -> menu entry \"Robot tools\"."
