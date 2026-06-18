#!/usr/bin/env bash
#
# All-in-One Installer fuer das Clearpath a200-0553 Custom-Setup + OnRobot RG6.
#
# Macht in einem Rutsch:
#   - Boot-Service clearpath-custom-setup: patcht bei JEDEM Boot die generierten
#     Configs (update_rate=125, foxglove asset_uri_allowlist, io_and_status_controller)
#   - UDEV-Regeln (/etc/udev/rules.d/99-husky.rules), netplan (/etc/netplan/01-netcfg.yaml),
#     systemd-networkd deaktivieren (NetworkManager)
#   - optional: GRUB-Boot beschleunigen (Menue verstecken, GRUB_TIMEOUT=0)
#   - optional: UR-Kinematik-Kalibrierung (ros-jazzy-ur-calibration -> YAML;
#     robot.yaml-Pfad muss man selbst eintragen)
#   - onrobot-rg6 per git klonen + bauen (colcon)
#   - rg6-bringup.service: spawnt io_and_status_controller + rg6_control beim Boot
#
# NICHT enthalten (bewusst): robot.yaml wird NICHT angefasst (handgepflegt).
#   Fuer das Greifer-3D-Modell muss robot.yaml weiterhin platform.extras.urdf +
#   system.ros2.workspaces enthalten - das pflegst du selbst.
#
# Aufruf (sudo wird bei Bedarf geholt):
#   1) unten RG6_REPO_URL setzen
#   2) bash install-clearpath-custom-setup.sh         # interaktiv (fragt bei bereits
#                                                       aktiven/abweichenden Aenderungen)
#      bash install-clearpath-custom-setup.sh -y      # alle Rueckfragen mit "ja"
#
# Idempotent: beliebig oft ausfuehrbar.

set -euo pipefail

# ---- Konfiguration ---------------------------------------------------------
RG6_REPO_URL="https://github.com/CLAIRLab-HAW/onrobot-rg6.git"   # onrobot-rg6 (CLAIRLab-HAW)
UPDATE_RATE_VALUE=125
BIN_DIR="/usr/local/bin"
PY_PATH="${BIN_DIR}/clearpath-custom-setup.py"
UNIT_NAME="clearpath-custom-setup.service"
UNIT_PATH="/etc/systemd/system/${UNIT_NAME}"
CONTROL_YAML="/etc/clearpath/manipulators/config/control.yaml"
FOXGLOVE_YAML="/etc/clearpath/platform/config/foxglove_bridge.yaml"

RG6_WRAPPER="${BIN_DIR}/rg6-bringup.sh"
RG6_UNIT="rg6-bringup.service"
RG6_UNIT_PATH="/etc/systemd/system/${RG6_UNIT}"

OLD_UNIT="clearpath-set-update-rate.service"
OLD_FILES=("${BIN_DIR}/set-update-rate.py" "${BIN_DIR}/wait-for-clearpath.sh")
# ---------------------------------------------------------------------------

if [ "$(id -u)" -ne 0 ]; then
    echo "Benoetige root-Rechte - starte via sudo neu ..."
    exec sudo -- bash "$0" "$@"
fi

# --- Interaktiv: -y/--yes beantwortet alle Rueckfragen mit "ja" ------------
ASSUME_YES=0
for _a in "$@"; do
    case "$_a" in
        -y|--yes) ASSUME_YES=1 ;;
    esac
done

# confirm "Frage" -> 0 (ja) / 1 (nein).
#   -y           -> immer ja
#   keine Konsole -> nein (nicht-interaktiv, nichts ueberschreiben) -> haengt NICHT
#   Timeout 60 s -> nein (verhindert Endlos-Warten)
# Prompt geht bewusst direkt auf /dev/tty (sichtbar!), nicht nach stderr.
confirm() {
    local _ans
    [ "$ASSUME_YES" -eq 1 ] && return 0
    # /dev/tty wirklich oeffenbar? (oeffnen testen, nicht nur Permissions)
    if ! { true < /dev/tty; } 2>/dev/null; then
        echo "    (keine interaktive Konsole -> uebersprungen; mit -y erzwingen)"
        return 1
    fi
    printf '%s [j/N] ' "$1" > /dev/tty
    if ! read -r -t 60 _ans < /dev/tty; then
        printf '\n    (keine Eingabe/Timeout -> uebersprungen)\n' > /dev/tty
        return 1
    fi
    case "$_ans" in [jJyY]*) return 0 ;; *) return 1 ;; esac
}

# Realer Nutzer (fuer den Workspace-Build), nicht root:
REAL_USER="${SUDO_USER:-robot}"
USER_HOME="$(getent passwd "$REAL_USER" | cut -d: -f6)"
RG6_WS="${USER_HOME}/onrobot-rg6"

if [ "$RG6_REPO_URL" = "REPLACE_WITH_GIT_URL" ]; then
    echo "FEHLER: Bitte oben im Skript RG6_REPO_URL auf die Git-URL von onrobot-rg6 setzen."
    exit 1
fi

# --- Vorgaenger-Service abloesen -------------------------------------------
if systemctl list-unit-files | grep -q "^${OLD_UNIT}"; then
    echo ">>> Entferne Vorgaenger ${OLD_UNIT}"
    systemctl disable --now "${OLD_UNIT}" 2>/dev/null || true
    rm -f "/etc/systemd/system/${OLD_UNIT}"
fi
for f in "${OLD_FILES[@]}"; do
    [ -e "$f" ] && { echo ">>> Entferne alte Datei $f"; rm -f "$f"; }
done

DO_BOOT=1
if systemctl list-unit-files | grep -q "^${UNIT_NAME}" && [ -f "$PY_PATH" ]; then
    confirm ">>> clearpath-custom-setup ist bereits installiert. Aktualisieren?" || DO_BOOT=0
fi
if [ "$DO_BOOT" -eq 1 ]; then
echo ">>> Installiere ${PY_PATH}"
install -d -m 0755 "$BIN_DIR"
cat > "$PY_PATH" <<'PY_EOF'
#!/usr/bin/env python3
"""Custom Clearpath setup: patcht generierte Config-Dateien nach der Generierung,
bevor die Sub-Services sie einlesen.

Patches:
  1. controller_manager 'update_rate' -> 125
     in /etc/clearpath/manipulators/config/control.yaml
     (gegen 500-Hz-Overruns; gelesen von clearpath-manipulators.service)

  2. foxglove_bridge 'asset_uri_allowlist' -> korrekt einfach-escapte Regex
     in /etc/clearpath/platform/config/foxglove_bridge.yaml
     (Clearpath generiert hier eine DOPPELT-escapte Regex, die als YAML-Param
      jeden package://-Mesh ablehnt -> URDF ohne Geometrie in Foxglove.
      Gelesen von der foxglove_bridge unter clearpath-platform.service)

Jeder Edit ist chirurgisch (nur die Zielzeile), idempotent, mit .bak-Backup und
atomarem Schreiben. Fehlt eine Datei/ein Key, wird die jeweilige Aenderung
uebersprungen (Warnung), die andere aber trotzdem ausgefuehrt.
"""

import os
import re
import shutil
import sys
import tempfile

TAG = "clearpath-custom-setup"

# ---- Konfiguration ---------------------------------------------------------
CONTROL_YAML = "/etc/clearpath/manipulators/config/control.yaml"
FOXGLOVE_YAML = "/etc/clearpath/platform/config/foxglove_bridge.yaml"

UPDATE_RATE_VALUE = 125

# Korrekte, EINFACH-escapte Regex (wie im funktionierenden Template
# clearpath_diagnostics/config/foxglove_bridge.yaml). In YAML-Single-Quotes
# bleibt '\w' ein Wortzeichen-Match; '\\w' waere ein literaler Backslash.
# Nur package:// (file:// serviert die foxglove_bridge ohnehin nicht; Sensor-
# Meshes werden per fix_realsense_mesh_uris auf package:// umgestellt).
FOXGLOVE_ALLOWLIST = (
    r"['^package://(?:[-\w%]+/)*[-\w%]+\.(?:dae|fbx|glb|gltf|jpeg|jpg|mtl|obj|"
    r"png|stl|tif|tiff|urdf|webp|xacro)$']"
)
# ---------------------------------------------------------------------------


def log(msg, err=False):
    """Logzeile (stdout/stderr); von journald via SyslogIdentifier erfasst."""
    print(f"{TAG}: {msg}", file=(sys.stderr if err else sys.stdout), flush=True)


def set_scalar_line(path, key, new_value_str, label):
    """Ersetzt chirurgisch den Wert einer eindeutigen `key: ...`-Zeile.

    Nur die Einrueckung wird erhalten; der bisherige Wert wird durch
    new_value_str ersetzt. Idempotent. Gibt True zurueck, wenn geaendert.
    """
    if not os.path.isfile(path):
        log(f"WARN: {label}: Datei nicht gefunden, uebersprungen: {path}", err=True)
        return False

    with open(path, "r") as f:
        lines = f.readlines()

    # <indent><key>: <wert>   (Wert muss vorhanden sein -> \S nach dem Doppelpunkt)
    rx = re.compile(
        r"^(?P<indent>[^\S\n]*)" + re.escape(key) + r"[^\S\n]*:[^\S\n]*\S.*$"
    )
    idx = [i for i, ln in enumerate(lines) if rx.match(ln.rstrip("\n"))]

    if not idx:
        log(f"WARN: {label}: '{key}' nicht in {path} gefunden, uebersprungen.", err=True)
        return False
    if len(idx) > 1:
        nums = ", ".join(str(i + 1) for i in idx)
        log(f"WARN: {label}: '{key}' mehrfach in {path} (Zeilen {nums}), "
            f"uebersprungen.", err=True)
        return False

    i = idx[0]
    m = rx.match(lines[i].rstrip("\n"))
    newline = "\n" if lines[i].endswith("\n") else ""
    new_line = f"{m.group('indent')}{key}: {new_value_str}{newline}"

    if lines[i] == new_line:
        log(f"{label}: bereits korrekt (Zeile {i + 1}), keine Aenderung.")
        return False

    backup = path + ".bak"
    if not os.path.exists(backup):
        shutil.copy2(path, backup)
        log(f"{label}: Backup erstellt: {backup}")

    lines[i] = new_line

    dir_name = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.writelines(lines)
        shutil.copymode(path, tmp)
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise

    log(f"{label}: gesetzt (Zeile {i + 1}).")
    return True


def _atomic_write(path, lines):
    """Schreibt lines atomar nach path (temp + os.replace, Mode erhalten)."""
    dir_name = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.writelines(lines)
        shutil.copymode(path, tmp)
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def ensure_io_and_status_controller(path, label):
    """Fuegt den UR GPIOController 'io_and_status_controller' in die control.yaml ein.

    - Typ unter controller_manager -> ros__parameters (Einrueckung = update_rate-Zeile)
    - Params-Block (tf_prefix) als Sibling unter dem Top-Level-Key (Einrueckung =
      controller_manager-Zeile), am Dateiende angehaengt.
    Idempotent: ist 'io_and_status_controller' schon drin, passiert nichts.
    """
    if not os.path.isfile(path):
        log(f"WARN: {label}: Datei nicht gefunden, uebersprungen: {path}", err=True)
        return False

    with open(path, "r") as f:
        lines = f.readlines()

    if any("io_and_status_controller" in ln for ln in lines):
        log(f"{label}: bereits vorhanden, keine Aenderung.")
        return False

    # Einrueckungen aus vorhandenen Ankern ableiten
    cm_indent = "  "
    rate_indent = "      "
    for ln in lines:
        m = re.match(r"^(?P<ind>[^\S\n]*)controller_manager[^\S\n]*:", ln)
        if m:
            cm_indent = m.group("ind")
        m = re.match(r"^(?P<ind>[^\S\n]*)update_rate[^\S\n]*:", ln)
        if m:
            rate_indent = m.group("ind")

    # 1) Typ-Eintrag direkt nach der update_rate-Zeile (gleiche Einrueckung)
    out = []
    inserted_type = False
    for ln in lines:
        out.append(ln)
        if not inserted_type and re.match(
                r"^[^\S\n]*update_rate[^\S\n]*:", ln):
            out.append(f"{rate_indent}io_and_status_controller:\n")
            out.append(f"{rate_indent}  type: 'ur_controllers/GPIOController'\n")
            inserted_type = True

    if not inserted_type:
        log(f"WARN: {label}: 'update_rate'-Anker nicht gefunden, Typ nicht "
            f"eingefuegt, uebersprungen.", err=True)
        return False

    # 2) Params-Block als Sibling unter dem Top-Level-Key (am Dateiende)
    if out and not out[-1].endswith("\n"):
        out[-1] += "\n"
    out.append(f"{cm_indent}io_and_status_controller:\n")
    out.append(f"{cm_indent}  ros__parameters:\n")
    out.append(f"{cm_indent}    tf_prefix: 'arm_0_'\n")

    backup = path + ".bak"
    if not os.path.exists(backup):
        shutil.copy2(path, backup)
        log(f"{label}: Backup erstellt: {backup}")

    _atomic_write(path, out)
    log(f"{label}: io_and_status_controller eingefuegt.")
    return True


def fix_realsense_mesh_uris(label):
    """Clearpaths Sensor-Xacros referenzieren Meshes als
    'file://$(find realsense2_description)/...'. Die foxglove_bridge serviert aber
    NUR package:// -> in Foxglove 'Failed to load' (RViz mit lokaler Datei ok).
    Hier auf 'package://realsense2_description' umstellen. Trifft apt-installierte
    Dateien unter /opt/ros/*/share/clearpath_sensors_description -> bei jedem Boot
    idempotent re-applied (uebersteht auch apt-Updates)."""
    import glob
    OLD = "file://$(find realsense2_description)"
    NEW = "package://realsense2_description"
    files = glob.glob(
        "/opt/ros/*/share/clearpath_sensors_description/urdf/**/*.urdf.xacro",
        recursive=True)
    changed = []
    for path in files:
        try:
            with open(path) as f:
                content = f.read()
        except OSError:
            continue
        if OLD not in content:
            continue
        backup = path + ".bak"
        if not os.path.exists(backup):
            try:
                shutil.copy2(path, backup)
            except OSError:
                pass
        tmp = path + ".tmp"
        try:
            with open(tmp, "w") as f:
                f.write(content.replace(OLD, NEW))
            os.replace(tmp, path)
            changed.append(os.path.basename(path))
        except OSError as e:
            log(f"{label}: kann {path} nicht schreiben: {e}", err=True)
    if changed:
        log(f"{label}: package:// gesetzt in: {', '.join(sorted(changed))}")
    else:
        log(f"{label}: bereits package:// (oder nichts gefunden) - keine Aenderung.")
    return bool(changed)


def main():
    log("Start.")
    # 1) update_rate
    set_scalar_line(CONTROL_YAML, "update_rate", str(UPDATE_RATE_VALUE),
                    "update_rate")
    # 2) foxglove asset_uri_allowlist
    set_scalar_line(FOXGLOVE_YAML, "asset_uri_allowlist", FOXGLOVE_ALLOWLIST,
                    "foxglove asset_uri_allowlist")
    # 3) io_and_status_controller in die control.yaml (Typ + tf_prefix)
    ensure_io_and_status_controller(CONTROL_YAML, "io_and_status_controller")
    # 4) Sensor-Meshes file:// -> package:// (foxglove_bridge serviert nur package://)
    fix_realsense_mesh_uris("sensor mesh package://")
    log("Fertig.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
PY_EOF
sed -i "s/^UPDATE_RATE_VALUE = .*/UPDATE_RATE_VALUE = ${UPDATE_RATE_VALUE}/" "$PY_PATH"
chmod 0755 "$PY_PATH"

echo ">>> Installiere ${UNIT_PATH}"
cat > "$UNIT_PATH" <<'UNIT_EOF'
[Unit]
Description=Custom Clearpath setup: patcht generierte Configs vor dem Start der Sub-Services
# NACH der Generierung: control.yaml & foxglove_bridge.yaml entstehen in
# clearpath-robot.service ExecStartPre (/usr/sbin/clearpath-robot-generate).
After=clearpath-robot.service
Wants=clearpath-robot.service
# VOR den Consumern, die die gepatchten Dateien einlesen:
#   - clearpath-manipulators.service liest control.yaml (update_rate)
#   - clearpath-platform.service startet die foxglove_bridge (asset_uri_allowlist)
Before=clearpath-manipulators.service
Before=clearpath-platform.service

[Service]
Type=oneshot
RemainAfterExit=yes
# Saubere Journal-Kennung:  journalctl -t clearpath-custom-setup -b
SyslogIdentifier=clearpath-custom-setup
StandardOutput=journal
StandardError=journal
ExecStart=/usr/local/bin/clearpath-custom-setup.py

[Install]
WantedBy=multi-user.target
UNIT_EOF
chmod 0644 "$UNIT_PATH"
else
    echo ">>> clearpath-custom-setup: uebersprungen (vorhandene Installation bleibt)."
fi

# --- UDEV-Regeln (managed block) -------------------------------------------
UDEV_FILE="/etc/udev/rules.d/99-husky.rules"
UDEV_BEGIN="# >>> clearpath-custom-setup (managed) >>>"
UDEV_END="# <<< clearpath-custom-setup (managed) <<<"

# Gewuenschten managed-Block (inkl. Marker) in temp-Datei erzeugen
udev_block="$(mktemp)"
cat > "$udev_block" <<'UDEV_EOF'
# >>> clearpath-custom-setup (managed) >>>
# Custom rule for CH340/CH341 Serial-to-USB adapter
SUBSYSTEM=="tty", ATTRS{idVendor}=="1a86", ATTRS{idProduct}=="7523", SYMLINK+="clearpath/prolific clearpath/prolific_$attr{devpath}", MODE="0666"

# Custom rule for FTDI Serial-to-USB adapter (Platform)
SUBSYSTEM=="tty", ATTRS{idVendor}=="0403", ATTRS{idProduct}=="6001", ATTRS{serial}=="A994H1DB", SYMLINK+="clearpath/prolific clearpath/prolific_$attr{devpath}", MODE="0666"

# Custom rule for FTDI Serial-to-USB adapter (UM7)
SUBSYSTEM=="tty", ATTRS{idVendor}=="0403", ATTRS{idProduct}=="6001", ATTRS{serial}=="A908RWEO", SYMLINK+="clearpath/um7}", MODE="0666"

# Joystick mapping to prevent adding too many devices
KERNEL=="js*", SUBSYSTEM=="input", ATTRS{idVendor}=="045e", ATTRS{idProduct}=="0719", SYMLINK+="input/js0", MODE="0666"
# <<< clearpath-custom-setup (managed) <<<
UDEV_EOF

DO_UDEV=1
if [ -f "$UDEV_FILE" ] && grep -qF "$UDEV_BEGIN" "$UDEV_FILE"; then
    existing_udev="$(mktemp)"
    awk -v b="$UDEV_BEGIN" -v e="$UDEV_END" '$0==b{p=1} p{print} $0==e{p=0}' \
        "$UDEV_FILE" > "$existing_udev"
    if cmp -s "$existing_udev" "$udev_block"; then
        confirm ">>> UDEV-Regeln sind bereits identisch aktiv. Trotzdem neu schreiben?" || DO_UDEV=0
    else
        confirm ">>> UDEV-Regeln (managed block) weichen ab. Ueberschreiben?" || DO_UDEV=0
    fi
    rm -f "$existing_udev"
fi

if [ "$DO_UDEV" -eq 1 ]; then
    echo ">>> Schreibe UDEV-Regeln nach ${UDEV_FILE}"
    install -d -m 0755 /etc/udev/rules.d
    touch "$UDEV_FILE"
    tmp_udev="$(mktemp)"
    awk -v b="$UDEV_BEGIN" -v e="$UDEV_END" '
      $0==b {skip=1; next}
      $0==e {skip=0; next}
      !skip {print}
    ' "$UDEV_FILE" > "$tmp_udev"
    cat "$udev_block" >> "$tmp_udev"
    install -m 0644 "$tmp_udev" "$UDEV_FILE"
    rm -f "$tmp_udev"
    udevadm control --reload-rules
    udevadm trigger --subsystem-match=tty
    echo "    UDEV-Regeln gesetzt und neu geladen."
else
    echo ">>> UDEV-Regeln: uebersprungen."
fi
rm -f "$udev_block"

# --- netplan ---------------------------------------------------------------
NETPLAN_FILE="/etc/netplan/01-netcfg.yaml"
echo ">>> Schreibe netplan ${NETPLAN_FILE}"
install -d -m 0755 /etc/netplan
tmp_np="$(mktemp)"
cat > "$tmp_np" <<'NETPLAN_EOF'
network:
  version: 2
  renderer: NetworkManager
  ethernets:
    enp6s0:
      optional: true
      dhcp4: false
      dhcp6: false
      addresses:
        - 192.168.131.10/24
      link-local: [ ]
NETPLAN_EOF
DO_NETPLAN=1
if [ -f "$NETPLAN_FILE" ] && cmp -s "$tmp_np" "$NETPLAN_FILE"; then
    echo "    netplan bereits aktuell - keine Aenderung."
    DO_NETPLAN=0
elif [ -f "$NETPLAN_FILE" ]; then
    confirm ">>> netplan ${NETPLAN_FILE} weicht ab. Ueberschreiben (Backup wird angelegt)?" || DO_NETPLAN=0
fi
if [ "$DO_NETPLAN" -eq 1 ]; then
    [ -f "$NETPLAN_FILE" ] && cp -a "$NETPLAN_FILE" "${NETPLAN_FILE}.$(date +%Y%m%d-%H%M%S).bak"
    install -m 0600 "$tmp_np" "$NETPLAN_FILE"
    command -v netplan >/dev/null 2>&1 && { netplan generate || echo "    WARN: netplan generate Problem"; }
    echo "    netplan geschrieben (Mode 0600). 'sudo netplan apply' NICHT automatisch."
else
    echo "    netplan: uebersprungen."
fi
rm -f "$tmp_np"

# --- systemd-networkd deaktivieren -----------------------------------------
# Nur fragen, wenn networkd ueberhaupt aktiv/enabled ist.
networkd_on=0
systemctl is-enabled systemd-networkd.service >/dev/null 2>&1 && networkd_on=1
systemctl is-active  systemd-networkd.service >/dev/null 2>&1 && networkd_on=1
DO_NETWORKD=1
if [ "$networkd_on" -eq 0 ]; then
    echo ">>> systemd-networkd ist bereits inaktiv - keine Aenderung."
    DO_NETWORKD=0
else
    confirm ">>> systemd-networkd deaktivieren (zugunsten NetworkManager)?" || DO_NETWORKD=0
fi
if [ "$DO_NETWORKD" -eq 1 ]; then
    echo ">>> Deaktiviere systemd-networkd zugunsten von NetworkManager"
    if systemctl list-unit-files | grep -q '^NetworkManager\.service'; then
        systemctl enable NetworkManager.service 2>/dev/null || true
    fi
    for u in systemd-networkd.service systemd-networkd.socket systemd-networkd-wait-online.service; do
        if systemctl list-unit-files | grep -q "^${u}"; then
            systemctl disable "$u" 2>/dev/null || true
            echo "    deaktiviert: $u"
        fi
    done
else
    echo ">>> systemd-networkd: uebersprungen."
fi

# --- GRUB: schneller Boot (Menue verstecken, direkter Boot der 1. Option) ---
# Optional + per Default AUS: ein verstecktes Menue erschwert Recovery (kommt
# aber mit gehaltener SHIFT/ESC-Taste beim Boot weiterhin). GRUB_TIMEOUT_STYLE=
# hidden + GRUB_TIMEOUT=0 => sofortiger Boot der Default-Option.
GRUB_FILE="/etc/default/grub"
if [ ! -f "$GRUB_FILE" ]; then
    echo ">>> GRUB: ${GRUB_FILE} nicht vorhanden - uebersprungen."
elif grep -qE '^GRUB_TIMEOUT_STYLE=hidden$' "$GRUB_FILE" && grep -qE '^GRUB_TIMEOUT=0$' "$GRUB_FILE"; then
    echo ">>> GRUB: bereits auf schnellen Boot gestellt - keine Aenderung."
elif confirm ">>> GRUB-Boot beschleunigen (GRUB_TIMEOUT_STYLE=hidden, GRUB_TIMEOUT=0)?"; then
    cp -a "$GRUB_FILE" "${GRUB_FILE}.bak.$(date +%Y%m%d%H%M%S)"
    # GRUB_TIMEOUT_STYLE setzen (vorhandene/auskommentierte Zeile ersetzen, sonst anhaengen)
    if grep -qE '^[#[:space:]]*GRUB_TIMEOUT_STYLE=' "$GRUB_FILE"; then
        sed -i -E 's|^[#[:space:]]*GRUB_TIMEOUT_STYLE=.*|GRUB_TIMEOUT_STYLE=hidden|' "$GRUB_FILE"
    else
        printf 'GRUB_TIMEOUT_STYLE=hidden\n' >> "$GRUB_FILE"
    fi
    # GRUB_TIMEOUT=0 (direkter Boot); matcht NICHT GRUB_TIMEOUT_STYLE=
    if grep -qE '^[#[:space:]]*GRUB_TIMEOUT=' "$GRUB_FILE"; then
        sed -i -E 's|^[#[:space:]]*GRUB_TIMEOUT=.*|GRUB_TIMEOUT=0|' "$GRUB_FILE"
    else
        printf 'GRUB_TIMEOUT=0\n' >> "$GRUB_FILE"
    fi
    echo "    ${GRUB_FILE} gepatcht (Backup angelegt). Aktualisiere GRUB..."
    if command -v update-grub >/dev/null 2>&1; then
        update-grub || echo "    WARN: update-grub fehlgeschlagen"
    elif command -v grub-mkconfig >/dev/null 2>&1; then
        grub-mkconfig -o /boot/grub/grub.cfg || echo "    WARN: grub-mkconfig fehlgeschlagen"
    else
        echo "    WARN: weder update-grub noch grub-mkconfig gefunden - bitte manuell ausfuehren."
    fi
    echo "    GRUB: schneller Boot aktiv (Menue weiterhin per gehaltener SHIFT/ESC erreichbar)."
else
    echo ">>> GRUB: uebersprungen (Boot-Menue unveraendert)."
fi

# --- UR-Kinematik-Kalibrierung (optional, einmalig) ------------------------
# Holt die individuelle Werks-Kalibrierung des UR-Arms (DH-Offsets). Ohne sie
# rechnet das Modell mit Nominal-Werten -> TCP real bis ~1cm daneben.
# Voraussetzung: Arm an + ueber UR_ROBOT_IP erreichbar. robot.yaml wird NICHT
# angefasst (handgepflegt) -> Pfad danach selbst als kinematics_parameters_file
# eintragen. Per Env ueberschreibbar: UR_ROBOT_IP=, UR_CALIB_FILE=.
UR_ROBOT_IP="${UR_ROBOT_IP:-192.168.131.40}"
UR_CALIB_FILE="${UR_CALIB_FILE:-${USER_HOME}/ur5_a200_0553_calibration.yaml}"

DO_CALIB=0
if [ -f "$UR_CALIB_FILE" ]; then
    confirm ">>> UR-Kalibrierdatei existiert bereits (${UR_CALIB_FILE}). NEU kalibrieren (ueberschreibt; Arm an + ${UR_ROBOT_IP} erreichbar)?" \
        && DO_CALIB=1
else
    confirm ">>> UR-Kinematik jetzt kalibrieren? (einmalig; installiert ros-jazzy-ur-calibration; Arm muss an + ${UR_ROBOT_IP} erreichbar sein)" \
        && DO_CALIB=1
fi

if [ "$DO_CALIB" -eq 1 ]; then
    # ur-calibration braucht ein zur ur-client-library passendes ABI. Clearpath
    # installiert evtl. einen aelteren UR-Stack (driver/urcl) -> die neueste
    # ur-calibration passt dann nicht (undefined symbol ...urcl...SafetyModeMessage,
    # und 3.7.0 ist nicht mehr im Repo). Loesung: den GANZEN UR-Stack KONSISTENT
    # (zusammen) installieren/aktualisieren -> alle aus demselben Release.
    # Hinweis: kann ur-robot-driver hochziehen (z.B. 3.7.0 -> 3.8.0). Im Test
    # entfernte das KEIN clearpath-Paket; danach Manipulator kurz testen.
    echo ">>> Installiere/aktualisiere UR-Stack konsistent (client-library + driver + calibration)"
    apt-get update || true
    apt-get install -y \
        ros-jazzy-ur-client-library ros-jazzy-ur-robot-driver ros-jazzy-ur-calibration \
        || echo "    WARN: UR-Stack-Installation fehlgeschlagen."
    if ! dpkg -s ros-jazzy-ur-calibration >/dev/null 2>&1; then
        echo ">>> ur_calibration nicht verfuegbar - Kalibrierung uebersprungen."
    elif ! ping -c1 -W2 "$UR_ROBOT_IP" >/dev/null 2>&1; then
        echo ">>> UR-Arm ${UR_ROBOT_IP} nicht erreichbar (ping) - Kalibrierung uebersprungen."
    else
        [ -f "$UR_CALIB_FILE" ] && cp -a "$UR_CALIB_FILE" "${UR_CALIB_FILE}.bak.$(date +%Y%m%d%H%M%S)"
        echo ">>> Kalibriere UR-Arm (${UR_ROBOT_IP}) -> ${UR_CALIB_FILE}"
        echo "    Hinweis: bei 'Could not connect' belegt evtl. der Treiber die Schnittstelle ->"
        echo "             'sudo systemctl stop clearpath-manipulators.service', dann erneut."
        if sudo -u "$REAL_USER" env HOME="$USER_HOME" bash -lc \
              "source /opt/ros/jazzy/setup.bash && ros2 launch ur_calibration calibration_correction.launch.py robot_ip:=${UR_ROBOT_IP} target_filename:='${UR_CALIB_FILE}'"; then
            chown "$REAL_USER":"$REAL_USER" "$UR_CALIB_FILE" 2>/dev/null || true
            echo "    Kalibrierung gespeichert: ${UR_CALIB_FILE}"
            echo "    -> In robot.yaml beim Arm eintragen und neu generieren (reboot):"
            echo "         kinematics_parameters_file: \"${UR_CALIB_FILE}\""
        else
            echo "    WARN: Kalibrierung fehlgeschlagen (Arm an/erreichbar? Schnittstelle frei?)."
        fi
    fi
else
    echo ">>> UR-Kalibrierung: uebersprungen."
fi

# --- onrobot-rg6 klonen + bauen (als realer Nutzer, nicht root) ------------
DO_RG6=1
if [ -d "${RG6_WS}/.git" ]; then
    confirm ">>> onrobot-rg6 existiert in ${RG6_WS}. git pull + neu bauen?" || DO_RG6=0
fi
if [ "$DO_RG6" -eq 1 ]; then
    echo ">>> onrobot-rg6 nach ${RG6_WS} (Nutzer ${REAL_USER})"
    if [ -d "${RG6_WS}/.git" ]; then
        sudo -u "$REAL_USER" git -C "$RG6_WS" pull --ff-only || echo "    WARN: git pull fehlgeschlagen, nutze vorhandenen Stand"
    else
        sudo -u "$REAL_USER" git clone "$RG6_REPO_URL" "$RG6_WS"
    fi
    echo ">>> Baue Workspace (colcon)"
    # rg6_description = Greifermodell + Meshes + clearpath_extras (Glue);
    # rg6_control = Treiber/Broadcaster. (onrobot_rg6_visualization wurde in
    # rg6_description gemergt.)
    sudo -u "$REAL_USER" env HOME="$USER_HOME" bash -lc \
        "source /etc/clearpath/setup.bash && cd '$RG6_WS' && colcon build --packages-select rg6_description rg6_control" \
        || echo "    WARN: colcon build fehlgeschlagen - rg6-bringup wird erst nach erfolgreichem Build laufen."
else
    echo ">>> onrobot-rg6: uebersprungen (vorhandener Stand bleibt)."
fi

# --- rg6-bringup Wrapper + Service -----------------------------------------
echo ">>> Installiere ${RG6_WRAPPER} + ${RG6_UNIT}"
cat > "$RG6_WRAPPER" <<EOF
#!/usr/bin/env bash
# Startet io_and_status_controller (Spawner) + rg6_control im manipulators-Namespace.
source /etc/clearpath/setup.bash
source ${RG6_WS}/install/setup.bash
exec ros2 launch rg6_control rg6_bringup.launch.py
EOF
chmod 0755 "$RG6_WRAPPER"

cat > "$RG6_UNIT_PATH" <<EOF
[Unit]
Description=OnRobot RG6 bringup (io_and_status_controller + rg6_control)
After=clearpath-manipulators.service
Wants=clearpath-manipulators.service

[Service]
User=${REAL_USER}
ExecStart=${RG6_WRAPPER}
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
chmod 0644 "$RG6_UNIT_PATH"

# --- aktivieren ------------------------------------------------------------
echo ">>> systemd neu einlesen + Services aktivieren"
systemctl daemon-reload
systemctl enable "$UNIT_NAME" "$RG6_UNIT"

echo ">>> Unit-Syntax pruefen"
systemd-analyze verify "$UNIT_PATH" "$RG6_UNIT_PATH" && echo "    Units OK."

# --- Patches jetzt einmal anwenden -----------------------------------------
if [ -f "$CONTROL_YAML" ] || [ -f "$FOXGLOVE_YAML" ]; then
    echo ">>> Wende Config-Patches jetzt einmalig an"
    "$PY_PATH" || true
fi

echo
echo "=============================================================="
echo "Installation abgeschlossen."
echo "  clearpath-custom-setup.service : patcht Configs bei jedem Boot"
echo "  rg6-bringup.service            : startet io_and_status_controller + rg6_control"
echo
echo "Damit ALLES greift, einmal neu starten:"
echo "  sudo systemctl restart clearpath-robot.service   # oder reboot"
echo
echo "Logs:"
echo "  journalctl -t clearpath-custom-setup -b"
echo "  journalctl -u rg6-bringup.service -b"
echo
echo "Hinweis: robot.yaml wird NICHT angefasst. Fuer das Greifer-3D-Modell dort"
echo "  weiterhin platform.extras.urdf + system.ros2.workspaces pflegen."
echo "=============================================================="
