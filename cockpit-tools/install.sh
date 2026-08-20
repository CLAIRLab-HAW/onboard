#!/usr/bin/env bash
# Installiert die Cockpit-Seite "Roboter-Werkzeuge" nach
# /usr/local/share/cockpit/robot-tools.
#
# Warum /usr/local und nicht /usr/share: Cockpit sucht in der Reihenfolge
# ~/.local/share/cockpit, /etc/cockpit, /usr/local/share/cockpit,
# /usr/share/cockpit. /usr/local gehoert uns, apt fasst es nicht an -- und der
# Rueckbau ist ein rm -rf des Zielverzeichnisses, kein apt-Vorgang.
#
#   sudo ./install.sh              # installieren/aktualisieren
#   sudo ./install.sh --uninstall  # wieder entfernen
#
# Danach genuegt ein Browser-Reload auf http://<robot>:9090 -- Cockpit liest
# die Pakete bei jedem Seitenaufbau neu ein, kein Dienst-Neustart noetig.
set -euo pipefail

PREFIX="${PREFIX:-/usr/local}"
DEST="${PREFIX}/share/cockpit/robot-tools"
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Nur diese Dateien gehoeren ins Paket. package.json und test/ sind
# Werkzeug fuer den Arbeitsplatz (node --test) und haben auf dem Roboter
# nichts verloren.
FILES=(manifest.json index.html index.js status.js style.css)

if [ "${1:-}" = "--uninstall" ]; then
    rm -rf "$DEST"
    echo "entfernt: $DEST"
    exit 0
fi

for f in "${FILES[@]}"; do
    [ -f "${SRC}/${f}" ] || { echo "FEHLER: ${SRC}/${f} fehlt." >&2; exit 1; }
done

if ! command -v cockpit-bridge >/dev/null 2>&1; then
    echo "WARN: cockpit-bridge nicht gefunden -- die Seite wird erst nach der"
    echo "      Cockpit-Installation sichtbar."
fi

# Altbestand weg, damit geloeschte Dateien nicht liegenbleiben.
rm -rf "$DEST"

# Kein id-Test, sondern der Versuch selbst: so laesst sich das Skript auch
# gegen ein PREFIX im eigenen Verzeichnis pruefen, und die Fehlermeldung
# kommt von der Stelle, an der es wirklich klemmt.
if ! install -d -m 0755 "$DEST" 2>/dev/null; then
    echo "FEHLER: ${DEST} laesst sich nicht anlegen -- mit sudo aufrufen" >&2
    echo "        (oder PREFIX=~/.local setzen, Cockpit sucht dort zuerst)." >&2
    exit 1
fi

for f in "${FILES[@]}"; do
    install -m 0644 "${SRC}/${f}" "${DEST}/${f}"
done

# Nur als root: sonst gehoerte das Paket dem Aufrufer, was unter /usr/local
# nicht sein soll.
[ "$(id -u)" -eq 0 ] && chown -R root:root "$DEST"

echo "installiert: $DEST"
echo "Cockpit im Browser neu laden -> Menuepunkt \"Roboter-Werkzeuge\"."
