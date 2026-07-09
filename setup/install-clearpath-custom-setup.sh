#!/usr/bin/env bash
#
# All-in-One Installer fuer das Clearpath a200-0553 Custom-Setup + OnRobot RG6.
#
# Macht in einem Rutsch:
#   - Boot-Service clearpath-custom-setup: patcht bei JEDEM Boot die generierten
#     Configs (foxglove asset_uri_allowlist, realsense mesh uris)
#   - UDEV-Regeln (/etc/udev/rules.d/99-husky.rules), netplan (/etc/netplan/01-netcfg.yaml),
#     systemd-networkd deaktivieren (NetworkManager)
#   - optional: GRUB-Boot beschleunigen (Menue verstecken, GRUB_TIMEOUT=0)
#   - optional: UR-Kinematik-Kalibrierung (ros-jazzy-ur-calibration -> YAML;
#     robot.yaml-Pfad muss man selbst eintragen)
#   - onrobot-rg6 per git klonen + bauen (colcon)
#   - rg6-bringup.service: startet rg6_control + joint_state_broadcaster + urscript_interface beim Boot
#     (io_and_status_controller wird von Clearpath aus der robot.yaml gespawnt)
#   - optional: ur-dashboard.service: startet den ur_robot_driver dashboard_client
#     (power_on/brake_release/unlock_protective_stop/restart_safety) beim Boot
#   - optional: ur-state-manager.service: klont+baut ur-state-manager und startet
#     den State-Manager (prepare/recover/ensure_ready/power_off) beim Boot
#   - optional: arm-controllers.service: laedt Extra-Controller (--inactive) +
#     ur_controller_mode_manager beim Boot (nutzt den ur-state-manager-Workspace)
#   - optional: manipulators-watchdog.timer: startet clearpath-manipulators.service
#     neu, wenn der Arm erst LANGE nach dem Boot bestromt wird (ros2_control retryt
#     die einmalig gescheiterte HW-Aktivierung nicht -> Treiber bleibt tot). Prueft
#     "Arm pingbar, aber robot_program_running publisht nicht" und startet EINMAL neu.
#   - robot.yaml aus dem Git-Repo (SSOT) nach /etc/clearpath/robot.yaml deployen +
#     robot-yaml-update.service: aktualisiert robot.yaml bei JEDEM Boot aus dem Repo
#     (VOR der Config-Generierung durch clearpath-robot.service). Ohne Netz/bei
#     Download-Fehler bleibt die vorhandene robot.yaml erhalten (Boot laeuft weiter).
#
# Hinweis robot.yaml: Das Repo ist ab jetzt die Single Source of Truth. Aenderungen
#   also im Repo pflegen (platform.extras.urdf, system.ros2.workspaces, Arm-/Sensor-
#   Config etc.) - lokale Aenderungen an /etc/clearpath/robot.yaml werden beim naechsten
#   Boot durch die Repo-Version ueberschrieben.
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
USM_REPO_URL="https://github.com/CLAIRLab-HAW/ur-state-manager.git"   # ur-state-manager (CLAIRLab-HAW)
BIN_DIR="/usr/local/bin"
PY_PATH="${BIN_DIR}/clearpath-custom-setup.py"
UNIT_NAME="clearpath-custom-setup.service"
UNIT_PATH="/etc/systemd/system/${UNIT_NAME}"
FOXGLOVE_YAML="/etc/clearpath/platform/config/foxglove_bridge.yaml"

RG6_WRAPPER="${BIN_DIR}/rg6-bringup.sh"
RG6_UNIT="rg6-bringup.service"
RG6_UNIT_PATH="/etc/systemd/system/${RG6_UNIT}"

# UR dashboard_client: Clearpath startet ihn im headless-Setup NICHT mit, liefert
# aber power_on/brake_release/unlock_protective_stop/restart_safety/get_*_mode.
# Kein Build noetig (kommt aus ros-jazzy-ur-robot-driver). robot_ip = UR-Control-Box.
UR_DASH_WRAPPER="${BIN_DIR}/ur-dashboard.sh"
UR_DASH_UNIT="ur-dashboard.service"
UR_DASH_UNIT_PATH="/etc/systemd/system/${UR_DASH_UNIT}"
UR_DASH_NS="/a200_0553/manipulators"
UR_DASH_ROBOT_IP="192.168.131.40"

# ur-state-manager: prepare/recover/ensure_ready/power_off-Services fuer den Arm.
# Wird (wie onrobot-rg6) geklont+gebaut und per Boot-Service gestartet. Braucht den
# dashboard_client (ur-dashboard.service) -> startet das Launch mit start_dashboard_client:=false.
USM_WRAPPER="${BIN_DIR}/ur-state-manager.sh"
USM_UNIT="ur-state-manager.service"
USM_UNIT_PATH="/etc/systemd/system/${USM_UNIT}"

# arm-controllers: laedt die Extra-Controller (--inactive) + Mode-Manager beim Boot.
# Nutzt denselben ur-state-manager-Workspace (kein eigener Build).
ARM_CTRL_WRAPPER="${BIN_DIR}/arm-controllers.sh"
ARM_CTRL_UNIT="arm-controllers.service"
ARM_CTRL_UNIT_PATH="/etc/systemd/system/${ARM_CTRL_UNIT}"

# joint-states (Phase 2): robot-weiter joint_state_aggregator (/a200_0553/joint_states)
# + Relays der sauberen Arm-/Greifer-Quell-Topics zurueck auf den platform/joint_states-
# Bus (fuer RSP + move_group). Nutzt den onrobot-rg6-Workspace (rg6_control
# joint_states.launch.py), kein eigener Build.
JS_WRAPPER="${BIN_DIR}/joint-states.sh"
JS_UNIT="joint-states.service"
JS_UNIT_PATH="/etc/systemd/system/${JS_UNIT}"

# manipulators-watchdog: deckt die eine Luecke ab, die auf ROS-Ebene NICHT loesbar
# ist. Wird der UR erst LANGE NACH dem Boot bestromt, scheitert die einmalige
# ros2_control-HW-Aktivierung des ur_robot_driver (Arm war stromlos) - und
# ros2_control retryt sie NICHT. Folge: io_and_status_controller publisht
# robot_program_running gar nicht mehr, Dashboard/State-Manager haben keine
# Eingabe, der Arm bleibt "Stopped". Einziger Ausweg = Treiber-Prozess neu starten.
# Dieser Timer erkennt "Arm pingbar, aber robot_program_running publisht nicht" und
# startet clearpath-manipulators.service EINMAL neu (mit Cooldown gegen Schleifen).
WD_WRAPPER="${BIN_DIR}/manipulators-watchdog.sh"
WD_UNIT="manipulators-watchdog.service"
WD_UNIT_PATH="/etc/systemd/system/${WD_UNIT}"
WD_TIMER="manipulators-watchdog.timer"
WD_TIMER_PATH="/etc/systemd/system/${WD_TIMER}"
WD_ROBOT_IP="192.168.131.40"
WD_PROGRAM_TOPIC="/a200_0553/manipulators/io_and_status_controller/robot_program_running"

# robot.yaml: Das Git-Repo ist die Single Source of Truth. Beim Boot wird die
# robot.yaml VOR der Config-Generierung (clearpath-robot.service) aus dem Repo
# nachgezogen. Ohne Netz/bei Fehler bleibt die vorhandene Datei erhalten.
ROBOT_YAML_URL="https://raw.githubusercontent.com/CLAIRLab-HAW/husky-custom-setup/refs/heads/main/robot.yaml"
ROBOT_YAML_PATH="/etc/clearpath/robot.yaml"
ROBOT_YAML_WRAPPER="${BIN_DIR}/robot-yaml-update.sh"
ROBOT_YAML_UNIT="robot-yaml-update.service"
ROBOT_YAML_UNIT_PATH="/etc/systemd/system/${ROBOT_YAML_UNIT}"

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
USM_WS="${USER_HOME}/ur-state-manager"

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
  1. foxglove_bridge 'asset_uri_allowlist' -> korrekt einfach-escapte Regex
     in /etc/clearpath/platform/config/foxglove_bridge.yaml
     (Clearpath generiert hier eine DOPPELT-escapte Regex, die als YAML-Param
      jeden package://-Mesh ablehnt -> URDF ohne Geometrie in Foxglove.
      Gelesen von der foxglove_bridge unter clearpath-platform.service)

  2. Sensor-Mesh-URIs file:// -> package:// (fix_realsense_mesh_uris)

  3. Arm-JSB joint_states -> manipulators/joint_states (move_arm_joint_states,
     Phase 2) in /opt/ros/*/share/clearpath_manipulators/launch/control.launch.py.
     Loest die Arm-Gelenke aus dem platform-Namespace; ein Relay + Aggregator
     (rg6_control joint_states.launch.py, joint-states.service) haelt den
     platform/joint_states-Bus fuer RSP+move_group vollstaendig.

Jeder Edit ist chirurgisch, idempotent, mit .bak-Backup und atomarem Schreiben.
Fehlt eine Datei/ein Key, wird die jeweilige Aenderung uebersprungen (Warnung).

Hinweis: 'update_rate' (125) und 'io_and_status_controller' werden NICHT mehr
hier gepatcht -> beide laufen ueber robot.yaml arm-level 'ros_parameters'
(clearpath_common PR #347).
"""

import os
import re
import shutil
import sys
import tempfile

TAG = "clearpath-custom-setup"

# ---- Konfiguration ---------------------------------------------------------
FOXGLOVE_YAML = "/etc/clearpath/platform/config/foxglove_bridge.yaml"

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


def move_arm_joint_states(label):
    """Phase 2: Arm-JSB-Publisher-Remap von platform/ -> manipulators/joint_states.

    clearpath_manipulators/control.launch.py remappt den joint_states-Output des
    manipulators-ros2_control_node per
        ('joint_states', PathJoinSubstitution(['/', namespace, 'platform', 'joint_states']))
    nach /<ns>/platform/joint_states. Damit advertised der Arm-JSB faelschlich im
    platform-Namespace. Hier die Tokenfolge 'platform','joint_states' ->
    'manipulators','joint_states' -> /<ns>/manipulators/joint_states.

    dynamic_joint_states bleibt bewusst auf platform: die Zeile
    'platform','dynamic_joint_states' wird NICHT getroffen (nach dem Komma steht
    dort 'dynamic_joint_states', nicht 'joint_states'). Trifft die apt-Stock-Datei
    unter /opt/ros/*/share -> idempotent bei jedem Boot (uebersteht apt-Updates).
    Ein Relay (rg6_control joint_states.launch.py) spiegelt manipulators/joint_states
    zurueck auf platform/joint_states fuer RSP/move_group (Live-TF/MoveIt unangetastet).
    """
    import glob
    files = glob.glob(
        "/opt/ros/*/share/clearpath_manipulators/launch/control.launch.py")
    rx = re.compile(r"(['\"])platform\1(\s*,\s*)(['\"])joint_states\3")
    changed = []
    for path in files:
        try:
            with open(path) as f:
                content = f.read()
        except OSError:
            continue
        new_content, n = rx.subn(r"\1manipulators\1\2\3joint_states\3", content)
        if n == 0:
            continue  # schon gepatcht oder Muster nicht (mehr) vorhanden
        backup = path + ".bak"
        if not os.path.exists(backup):
            try:
                shutil.copy2(path, backup)
            except OSError:
                pass
        tmp = path + ".tmp"
        try:
            with open(tmp, "w") as f:
                f.write(new_content)
            os.replace(tmp, path)
            changed.append(f"{os.path.basename(path)} ({n}x)")
        except OSError as e:
            log(f"{label}: kann {path} nicht schreiben: {e}", err=True)
    if changed:
        log(f"{label}: Arm joint_states -> manipulators in: {', '.join(changed)}")
    else:
        log(f"{label}: bereits manipulators (oder Muster nicht gefunden) - keine Aenderung.")
    return bool(changed)


def run_rg6_moveit_patch(label):
    """RG6 in die frisch generierte MoveIt-Config einhaengen.

    Delegiert an das selbst-enthaltene Tool aus dem onrobot-rg6-Repo
    (rg6_moveit_patch: robot.srdf + manipulators/config/moveit.yaml, idempotent).
    Muss NACH clearpath-robot-generate und VOR clearpath-manipulators laufen -
    genau das Fenster dieses Services. Fehlt das Tool (Repo nicht installiert),
    wird nur gewarnt."""
    import glob
    import subprocess
    candidates = (
        glob.glob("/home/*/onrobot-rg6/install/rg6_control/lib/rg6_control/rg6_moveit_patch")
        + glob.glob("/home/*/onrobot-rg6/src/rg6_control/scripts/rg6_moveit_patch")
    )
    if not candidates:
        log(f"{label}: rg6_moveit_patch nicht gefunden (onrobot-rg6 gebaut?) - "
            "MoveIt ohne Greifer.", err=True)
        return False
    tool = sorted(candidates)[0]
    try:
        out = subprocess.run(
            [tool, "--setup-path", "/etc/clearpath"],
            capture_output=True, text=True, timeout=60)
        for line in (out.stdout + out.stderr).splitlines():
            log(f"{label}: {line}")
        if out.returncode != 0:
            log(f"{label}: Exit-Code {out.returncode}.", err=True)
            return False
        return True
    except (OSError, subprocess.TimeoutExpired) as e:
        log(f"{label}: Aufruf fehlgeschlagen: {e}", err=True)
        return False


def main():
    log("Start.")
    # Hinweis: 'update_rate' (125) und 'io_and_status_controller' werden NICHT mehr
    # hier gepatcht -> beide laufen ueber robot.yaml arm-level 'ros_parameters'
    # (clearpath_common PR #347), verifiziert 2026-06.
    # 1) foxglove asset_uri_allowlist
    set_scalar_line(FOXGLOVE_YAML, "asset_uri_allowlist", FOXGLOVE_ALLOWLIST,
                    "foxglove asset_uri_allowlist")
    # 2) Sensor-Meshes file:// -> package:// (foxglove_bridge serviert nur package://)
    fix_realsense_mesh_uris("sensor mesh package://")
    # 3) Phase 2: Arm-JSB joint_states raus aus dem platform-Namespace ->
    #    manipulators/joint_states (Relay + Aggregator via joint-states.service).
    move_arm_joint_states("arm joint_states -> manipulators")
    # 4) RG6 in MoveIt: robot.srdf (Gruppe 'gripper' + EE) und moveit.yaml
    #    (GripperCommand-Controller + joint_limits) patchen (onrobot-rg6-Tool).
    run_rg6_moveit_patch("rg6 moveit")
    log("Fertig.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
PY_EOF
chmod 0755 "$PY_PATH"

echo ">>> Installiere ${UNIT_PATH}"
cat > "$UNIT_PATH" <<'UNIT_EOF'
[Unit]
Description=Custom Clearpath setup: patcht generierte Configs vor dem Start der Sub-Services
# NACH der Generierung: control.yaml & foxglove_bridge.yaml entstehen in
# clearpath-robot.service ExecStartPre (/usr/sbin/clearpath-robot-generate).
After=clearpath-robot.service
Wants=clearpath-robot.service
# Mit-Neustart: clearpath-robot.service generiert in ExecStartPre
# (clearpath-robot-generate) die Configs NEU -> die Patches werden
# ueberschrieben. PartOf sorgt dafuer, dass dieser Service bei JEDEM
# Restart von clearpath-robot.service (nicht nur beim Boot) erneut
# laeuft und die Configs wieder patcht. Propagiert Stop UND Restart.
PartOf=clearpath-robot.service
# VOR den Consumern der gepatchten Dateien:
#   - clearpath-platform.service startet die foxglove_bridge (asset_uri_allowlist +
#     Sensor-Meshes).
#   - clearpath-manipulators.service liest control.launch.py -> der Arm-JSB-
#     joint_states-Patch (move_arm_joint_states, Phase 2) MUSS davor greifen.
Before=clearpath-platform.service clearpath-manipulators.service

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
        "source /etc/clearpath/setup.bash && cd '$RG6_WS' && colcon build --packages-select rg6_description rg6_msgs rg6_control" \
        || echo "    WARN: colcon build fehlgeschlagen - rg6-bringup wird erst nach erfolgreichem Build laufen."
else
    echo ">>> onrobot-rg6: uebersprungen (vorhandener Stand bleibt)."
fi

# --- rg6-bringup Wrapper + Service -----------------------------------------
echo ">>> Installiere ${RG6_WRAPPER} + ${RG6_UNIT}"
cat > "$RG6_WRAPPER" <<EOF
#!/usr/bin/env bash
# Startet rg6_control + joint_state_broadcaster im manipulators-Namespace.
# (io_and_status_controller spawnt Clearpath selbst aus der robot.yaml-ros_parameters.)
source /etc/clearpath/setup.bash
source ${RG6_WS}/install/setup.bash
exec ros2 launch rg6_control rg6_bringup.launch.py
EOF
chmod 0755 "$RG6_WRAPPER"

cat > "$RG6_UNIT_PATH" <<EOF
[Unit]
Description=OnRobot RG6 bringup (rg6_control + joint_state_broadcaster)
After=clearpath-manipulators.service
Wants=clearpath-manipulators.service
# Mit-Neustart: bei einem Restart von clearpath-manipulators wird der
# controller_manager neu gespawnt und der joint_state_broadcaster verworfen ->
# dieser Service muss ihn neu laden. PartOf propagiert Stop UND Restart.
PartOf=clearpath-manipulators.service

[Service]
User=${REAL_USER}
ExecStart=${RG6_WRAPPER}
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
chmod 0644 "$RG6_UNIT_PATH"

# --- UR dashboard_client als Boot-Service (optional) -----------------------
# Liefert die Dashboard-Services (power_on/brake_release/unlock_protective_stop/
# restart_safety/get_robot_mode/get_safety_mode). Eigener Service, kein Build:
# 'ros2 run ur_robot_driver dashboard_client' verbindet sich auf <ip>:29999.
# __node:=dashboard_client wird gepinnt -> Services landen deterministisch unter
# ${UR_DASH_NS}/dashboard_client/* (passt zum ur_state_manager-Default).
DO_DASH=1
if [ -f "$UR_DASH_UNIT_PATH" ]; then
    confirm ">>> ur-dashboard.service ist bereits installiert. Aktualisieren?" || DO_DASH=0
else
    confirm ">>> UR dashboard_client als Boot-Service installieren (power_on/brake_release/unlock/restart_safety)?" || DO_DASH=0
fi
if [ "$DO_DASH" -eq 1 ]; then
    echo ">>> Installiere ${UR_DASH_WRAPPER} + ${UR_DASH_UNIT}"
    cat > "$UR_DASH_WRAPPER" <<EOF
#!/usr/bin/env bash
# Startet den ur_robot_driver dashboard_client im manipulators-Namespace.
# Verbindet sich auf den UR Dashboard-Server (${UR_DASH_ROBOT_IP}:29999) und legt
# die Services ${UR_DASH_NS}/dashboard_client/* an.
source /etc/clearpath/setup.bash
exec ros2 run ur_robot_driver dashboard_client --ros-args \\
    -r __ns:=${UR_DASH_NS} \\
    -r __node:=dashboard_client \\
    -p robot_ip:=${UR_DASH_ROBOT_IP}
EOF
    chmod 0755 "$UR_DASH_WRAPPER"

    cat > "$UR_DASH_UNIT_PATH" <<EOF
[Unit]
Description=UR dashboard_client (power_on/brake_release/unlock_protective_stop/restart_safety)
After=clearpath-manipulators.service
Wants=clearpath-manipulators.service

[Service]
User=${REAL_USER}
ExecStart=${UR_DASH_WRAPPER}
# dashboard_client beendet sich, wenn die Control-Box (29999) noch nicht bereit
# ist -> automatisch erneut versuchen.
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
    chmod 0644 "$UR_DASH_UNIT_PATH"
else
    echo ">>> UR dashboard_client: uebersprungen."
fi

# --- ur-state-manager klonen + bauen + Boot-Service (optional) -------------
# prepare/recover/ensure_ready/power_off-Services fuer den Arm. Wie onrobot-rg6:
# als realer Nutzer klonen+bauen, dann per systemd starten. Braucht den
# dashboard_client (ur-dashboard.service) -> Launch mit start_dashboard_client:=false.
DO_USM=1
if [ -d "${USM_WS}/.git" ]; then
    confirm ">>> ur-state-manager existiert in ${USM_WS}. git pull + neu bauen + Service aktualisieren?" || DO_USM=0
else
    confirm ">>> ur-state-manager installieren (prepare/recover-Services; klont+baut + Boot-Service)?" || DO_USM=0
fi
if [ "$DO_USM" -eq 1 ]; then
    echo ">>> ur-state-manager nach ${USM_WS} (Nutzer ${REAL_USER})"
    if [ -d "${USM_WS}/.git" ]; then
        sudo -u "$REAL_USER" git -C "$USM_WS" pull --ff-only || echo "    WARN: git pull fehlgeschlagen, nutze vorhandenen Stand"
    else
        sudo -u "$REAL_USER" git clone "$USM_REPO_URL" "$USM_WS"
    fi
    echo ">>> Baue Workspace (colcon)"
    sudo -u "$REAL_USER" env HOME="$USER_HOME" bash -lc \
        "source /etc/clearpath/setup.bash && cd '$USM_WS' && colcon build --packages-select ur_state_manager" \
        || echo "    WARN: colcon build fehlgeschlagen - ur-state-manager.service laeuft erst nach erfolgreichem Build."

    echo ">>> Installiere ${USM_WRAPPER} + ${USM_UNIT}"
    cat > "$USM_WRAPPER" <<EOF
#!/usr/bin/env bash
# Startet den ur_state_manager (prepare/recover/ensure_ready/power_off).
# start_dashboard_client:=false -> der dashboard_client laeuft via ur-dashboard.service.
source /etc/clearpath/setup.bash
source ${USM_WS}/install/setup.bash
exec ros2 launch ur_state_manager ur_state_manager.launch.py start_dashboard_client:=false
EOF
    chmod 0755 "$USM_WRAPPER"

    cat > "$USM_UNIT_PATH" <<EOF
[Unit]
Description=UR state manager (prepare/recover/ensure_ready/power_off fuer den UR5)
# Nach dem dashboard_client starten (liefert die Dashboard-Services). Ist
# ur-dashboard.service nicht installiert, ist das After= ein No-op.
After=clearpath-manipulators.service ur-dashboard.service
Wants=clearpath-manipulators.service
# Mit-Neustart: startet clearpath-manipulators (Treiber/controller_manager) neu,
# muss auch dieser Node neu starten - sonst zeigen der robot_state_helper und der
# Adapter auf stale io_and_status_controller-Topics/-Services. PartOf propagiert
# Stop UND Restart der genannten Unit (einseitig).
PartOf=clearpath-manipulators.service

[Service]
User=${REAL_USER}
ExecStart=${USM_WRAPPER}
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
    chmod 0644 "$USM_UNIT_PATH"
else
    echo ">>> ur-state-manager: uebersprungen."
fi

# --- arm-controllers Boot-Service (optional) -------------------------------
# Laedt die Extra-Controller (ft/tcp_pose/speed_scaling aktiv; freedrive/forward/
# passthrough --inactive) in den manipulators-CM und startet den Mode-Manager.
# Braucht den gebauten ur-state-manager-Workspace (siehe oben).
DO_ARM_CTRL=1
if [ -f "$ARM_CTRL_UNIT_PATH" ]; then
    confirm ">>> arm-controllers.service ist bereits installiert. Aktualisieren?" || DO_ARM_CTRL=0
else
    confirm ">>> arm-controllers beim Boot starten (Extra-Controller + Mode-Manager)?" || DO_ARM_CTRL=0
fi
if [ "$DO_ARM_CTRL" -eq 1 ]; then
    echo ">>> Installiere ${ARM_CTRL_WRAPPER} + ${ARM_CTRL_UNIT}"
    cat > "$ARM_CTRL_WRAPPER" <<EOF
#!/usr/bin/env bash
# Laedt Extra-Controller (--inactive) + startet ur_controller_mode_manager.
source /etc/clearpath/setup.bash
source ${USM_WS}/install/setup.bash
exec ros2 launch ur_state_manager arm_controllers.launch.py
EOF
    chmod 0755 "$ARM_CTRL_WRAPPER"

    cat > "$ARM_CTRL_UNIT_PATH" <<EOF
[Unit]
Description=UR arm controllers (extra controllers --inactive + mode manager)
# Nach dem manipulators-controller_manager (Spawner wartet ohnehin mit Timeout).
After=clearpath-manipulators.service
Wants=clearpath-manipulators.service
# Mit-Neustart: bei einem Restart von clearpath-manipulators wird der
# controller_manager neu gespawnt und die Extra-Controller (--inactive) sind weg
# -> dieser Service muss sie neu laden. PartOf propagiert Stop UND Restart.
PartOf=clearpath-manipulators.service

[Service]
User=${REAL_USER}
ExecStart=${ARM_CTRL_WRAPPER}
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
    chmod 0644 "$ARM_CTRL_UNIT_PATH"
else
    echo ">>> arm-controllers: uebersprungen."
fi

# --- manipulators-watchdog: Treiber-Reconnect bei spaetem Einschalten -------
# Siehe Variablen-Kommentar oben. Behebt den Fall "Arm zu lange stromlos ->
# ur_robot_driver einmalig gescheitert -> bleibt tot", den auto_recover
# konstruktionsbedingt NICHT abdecken kann (falsche Ebene: der Watcher braucht die
# tote Treiber-Verbindung fuer seine eigenen Eingaben und kann keinen Prozess neu
# starten). Timer-getrieben; Wrapper laeuft als root (fuer systemctl restart), die
# ROS-Pruefung als ${REAL_USER} (gleicher ROS-Graph).
DO_WD=1
if [ -f "$WD_UNIT_PATH" ]; then
    confirm ">>> manipulators-watchdog ist bereits installiert. Aktualisieren?" || DO_WD=0
else
    confirm ">>> manipulators-watchdog installieren (Treiber-Neustart, wenn der Arm spaet eingeschaltet wird)?" || DO_WD=0
fi
if [ "$DO_WD" -eq 1 ]; then
    echo ">>> Installiere ${WD_WRAPPER} + ${WD_UNIT} + ${WD_TIMER}"
    cat > "$WD_WRAPPER" <<'WD_EOF'
#!/usr/bin/env bash
# Watchdog: erkennt "Arm erreichbar, aber ur_robot_driver NICHT verbunden"
# (robot_program_running publisht nicht -> ros2_control-HW-Interface einmalig beim
# Start gescheitert, weil der Arm da noch stromlos war; ros2_control retryt die
# HW-Aktivierung NICHT). Recovery: Treiber neu starten UND den Arm bestromen
# (power_on + brake_release) + ExternalControl neu starten (resend_robot_program,
# headless). So wird ein spaetes Einschalten vollstaendig automatisch aufgefangen -
# kein manueller Eingriff mehr noetig. Protective-/Safety-Stops (safety_mode !=
# NORMAL) werden NICHT auto-gecleart (bleiben manuell) - nur geloggt.
# Aufruf: manipulators-watchdog.sh <ROBOT_IP> <TOPIC> <RUN_USER> <RUN_HOME>
#   TOPIC = .../io_and_status_controller/robot_program_running (Namespace wird
#   daraus abgeleitet; Dashboard- + Resend-Services unter demselben Namespace).
set -uo pipefail

ROBOT_IP="${1:?ROBOT_IP fehlt}"
TOPIC="${2:?TOPIC fehlt}"
RUN_USER="${3:?RUN_USER fehlt}"
RUN_HOME="${4:?RUN_HOME fehlt}"
SERVICE="clearpath-manipulators.service"
DASH_SVC="ur-dashboard.service"
COOLDOWN="${WD_COOLDOWN:-180}"         # s: nach einer Recovery so lange nicht erneut
ECHO_TIMEOUT="${WD_ECHO_TIMEOUT:-8}"   # s: so lange auf eine Topic-Nachricht warten
POWER_TIMEOUT="${WD_POWER_TIMEOUT:-25}"  # Iterationen: auf power_on/brake_release-Moduswechsel warten
RPR_WAIT="${WD_RPR_WAIT:-15}"           # Iterationen: rpr=true-Bestaetigung nach resend
STATE="/run/manipulators-watchdog.state"
TAG="manipulators-watchdog"
log() { echo "${TAG}: $*"; }

# Namespace aus dem Topic ableiten (.../io_and_status_controller/robot_program_running).
NS="${TOPIC%/io_and_status_controller/*}"
DASH_NS="${NS}/dashboard_client"
RESEND_SVC="${NS}/io_and_status_controller/resend_robot_program"

# ROS-Befehl als RUN_USER im selben Graphen ausfuehren.
ros_cmd() { sudo -u "$RUN_USER" env HOME="$RUN_HOME" bash -lc "source /etc/clearpath/setup.bash && $*"; }

# 1) Arm ueberhaupt erreichbar? Nein -> bewusst nichts tun (Arm noch aus; der
#    Watchdog soll NUR beim spaeten Einschalten anspringen, nicht dauernd).
if ! ping -c1 -W1 "$ROBOT_IP" >/dev/null 2>&1; then
    exit 0
fi

# 2) Publisht robot_program_running? IRGENDEINE Nachricht (true ODER false) = Treiber
#    lebt -> auto_recover/prepare uebernimmt, Watchdog haelt sich raus. KEINE Nachricht
#    = Treiber tot (HW-Interface gescheitert ODER Arm POWER_OFF, ExternalControl nicht
#    laufend) -> Recovery.
if ros_cmd "timeout ${ECHO_TIMEOUT} ros2 topic echo --once '${TOPIC}'" >/dev/null 2>&1; then
    exit 0    # Treiber verbunden -> ok
fi

# 3) Cooldown pruefen (/run wird beim Boot geleert -> pro Boot frisch).
now="$(date +%s)"
if [ -f "$STATE" ]; then
    last="$(cat "$STATE" 2>/dev/null || echo 0)"
    [ -n "$last" ] || last=0
    if [ "$(( now - last ))" -lt "$COOLDOWN" ]; then
        log "Treiber verbindet nicht, aber letzte Recovery < ${COOLDOWN}s her -> warte."
        exit 0
    fi
fi

log "Arm erreichbar (${ROBOT_IP}), aber ${TOPIC} publisht nicht -> Recovery (spaetes Einschalten nach Kaltstart): ${SERVICE} neu starten, dann bestromen + ExternalControl neu starten."
echo "$now" > "$STATE"

# --- Helfer: Modus-/Safety-Abfrage und Trigger-Aufrufe (alle via Dashboard) ---
robot_mode() { ros_cmd "timeout 10 ros2 service call '${DASH_NS}/get_robot_mode' ur_dashboard_msgs/srv/GetRobotMode" 2>&1 | grep -oE 'Robotmode: [A-Z_]+' | head -1; }
safety_mode() { ros_cmd "timeout 10 ros2 service call '${DASH_NS}/get_safety_mode' ur_dashboard_msgs/srv/GetSafetyMode" 2>&1 | grep -oE 'Safetymode: [A-Z_]+' | head -1; }
call_trigger() {  # $1 Service-Pfad, $2 Timeout(s); 0 = success=True
    local svc="$1" t="${2:-12}"
    ros_cmd "timeout ${t} ros2 service call '${svc}' std_srvs/srv/Trigger" 2>&1 | grep -q 'success=True'
}

# 3a) Treiber neu starten (blockierend): der alte ros2_control_node ignoriert SIGTERM
#     und braucht bis zu 90s bis SIGKILL; systemctl restart blockiert diese Zeit, damit
#     ist beim Weitergehen der NEUE Controller-Manager oben (kein Treffer auf den
#     sterbenden alten CM). TimeoutStartSec des watchdog-Service muss das abdecken
#     (siehe Unit, dort =240s).
systemctl restart "$SERVICE" || log "systemctl restart ${SERVICE} lief nicht sauber - versuche Recovery trotzdem weiter."

# 3b) ur-dashboard.service sicherstellen (power_on/brake_release brauchen den
#     Dashboard-Client; unabhaengig von manipulators, bleibt beim Restart oben).
if [ "$(systemctl is-active "$DASH_SVC" 2>/dev/null)" != "active" ]; then
    log "${DASH_SVC} nicht aktiv -> starte es."
    systemctl start "$DASH_SVC" || true
    sleep 3
fi

# 3c) Arm bestromen (power_on). Beides geht ans Dashboard (unabhaengig vom manipulators-CM).
if ! call_trigger "${DASH_NS}/power_on" 15; then
    log "power_on fehlgeschlagen/Timeout - breche Recovery ab (naechster Timer-Lauf)."
    exit 0
fi
for i in $(seq 1 "${POWER_TIMEOUT}"); do
    [ "$(robot_mode)" != "Robotmode: POWER_OFF" ] && break
    sleep 1
done
log "nach power_on: $(robot_mode)."

# 3d) Safety-Check: Safety-Stop wird NICHT auto-gecleart (manuell). Nur loggen + Ende.
sm="$(safety_mode)"
if [ "$sm" != "Safetymode: NORMAL" ]; then
    log "Safety-Modus ist '${sm:-unbekannt}' (kein NORMAL) -> Protective-/Safety-Stop. NICHT auto-gecleart, manuelle Begutachtung noetig. brake_release/resend uebersprungen."
    exit 0
fi

# 3e) Bremsen loesen (brake_release).
if ! call_trigger "${DASH_NS}/brake_release" 15; then
    log "brake_release fehlgeschlagen/Timeout."
    exit 0
fi
for i in $(seq 1 "${POWER_TIMEOUT}"); do
    [ "$(robot_mode)" = "Robotmode: RUNNING" ] && break
    sleep 1
done
log "nach brake_release: $(robot_mode)."

# 3f) ExternalControl direkt neu starten (resend_robot_program) - mit Retries, weil
#     der neue manipulators-CM ein paar Sekunden braucht, bis io_and_status_controller
#     aktiv ist, und Service-Discovery unter rmw_zenoh zaehe sein kann. Direkter Aufruf
#     statt ros2-service-list-Poll (letzterer ist unter rmw_zenoh unzuverlaessig).
#     Laeuft der ur_state_manager mit, resettet dessen auto_recover parallel; ein
#     doppelter resend ist idempotent (Programm laeuft schon -> Erfolg ohne Wirkung).
sent=""
for attempt in 1 2 3 4 5 6; do
    if call_trigger "${RESEND_SVC}" 20; then
        log "resend_robot_program gesendet (Versuch ${attempt})."
        sent=1; break
    fi
    log "resend Versuch ${attempt} fehlgeschlagen; erneut."
    sleep 3
done
if [ -z "$sent" ]; then
    log "resend_robot_program nach 6 Versuchen fehlgeschlagen - ExternalControl nicht neu gestartet. Naechster Timer-Lauf (Cooldown ${COOLDOWN}s)."
    exit 0
fi

# 3g) rpr=true bestaetigen (Topic-Echo, zuverlaessig; kurz - resend hat das Programm
#     gestartet, rpr wird schnell true).
ok=""
for i in $(seq 1 "${RPR_WAIT}"); do
    v="$(ros_cmd "timeout 6 ros2 topic echo --once '${TOPIC}'" 2>&1 | grep -oE 'data: (true|false)' | head -1)"
    [ "$v" = "data: true" ] && { ok=1; break; }
    sleep 1
done
if [ -n "$ok" ]; then
    log "Recovery erfolgreich: ${TOPIC} -> data: true."
else
    log "resend gesendet, aber ${TOPIC} noch kein 'true' (${v:-keine Nachricht}). Naechster Timer-Lauf prueft erneut (Cooldown ${COOLDOWN}s)."
fi
WD_EOF
    chmod 0755 "$WD_WRAPPER"

    cat > "$WD_UNIT_PATH" <<EOF
[Unit]
Description=Watchdog check: restart clearpath-manipulators when the arm is reachable but the UR driver is not connected
# Nur nach dem Treiber pruefen; KEIN Wants/PartOf (rein periodischer Check, darf
# den Treiber nicht mit-starten/-stoppen).
After=clearpath-manipulators.service

[Service]
Type=oneshot
# LAeuft als root (Default) -> darf systemctl restart. Die ROS-Pruefung im Wrapper
# wechselt selbst per 'sudo -u' auf ${REAL_USER}.
ExecStart=${WD_WRAPPER} ${WD_ROBOT_IP} ${WD_PROGRAM_TOPIC} ${REAL_USER} ${USER_HOME}
# Recovery blockiert beim systemctl restart (alter ros2_control_node braucht bis zu 90s
# bis SIGKILL) + Dashboard-Aufrufe + Polls. systemd-Default-Timeout (90s) wuerde den
# oneshot mittendrin killen -> grosszuegig.
TimeoutStartSec=300
# Script-echo-Zeilen unter journalctl -t manipulators-watchdog sammelbar.
SyslogIdentifier=manipulators-watchdog
EOF
    chmod 0644 "$WD_UNIT_PATH"

    cat > "$WD_TIMER_PATH" <<EOF
[Unit]
Description=Periodischer manipulators-watchdog-Check (Treiber-Reconnect bei spaetem Arm-Einschalten)

[Timer]
# Erst nach der normalen Boot-Hochlaufzeit beginnen (Treiber Zeit geben), dann
# regelmaessig. So schlaegt der Watchdog beim gesunden Boot NICHT an.
OnBootSec=90
OnUnitActiveSec=30
AccuracySec=5

[Install]
WantedBy=timers.target
EOF
    chmod 0644 "$WD_TIMER_PATH"
else
    echo ">>> manipulators-watchdog: uebersprungen."
fi

# --- joint-states Aggregation + Legacy-Bus-Relays (Phase 2) ----------------
# Startet rg6_control/joint_states.launch.py: joint_state_aggregator
# (-> /a200_0553/joint_states, vollstaendig, fuer rosbag/Foxglove) + zwei
# topic_tools relays (manipulators/joint_states und manipulators/endeffectors/
# joint_states -> platform/joint_states, damit RSP+move_group unveraendert laufen).
# Voraussetzung: Arm-JSB-Remap ist auf manipulators/joint_states umgestellt
# (Patch move_arm_joint_states im clearpath-custom-setup.py) und der Greifer
# publiziert auf manipulators/endeffectors/joint_states (rg6_bringup js_topic).
echo ">>> Installiere ${JS_WRAPPER} + ${JS_UNIT}"
cat > "$JS_WRAPPER" <<EOF
#!/usr/bin/env bash
# Robot-weite joint_states-Aggregation + Legacy-Bus-Relays (siehe joint_states.launch.py).
source /etc/clearpath/setup.bash
source ${RG6_WS}/install/setup.bash
exec ros2 launch rg6_control joint_states.launch.py
EOF
chmod 0755 "$JS_WRAPPER"

cat > "$JS_UNIT_PATH" <<EOF
[Unit]
Description=Robot-weite joint_states-Aggregation + Legacy-Bus-Relays (Phase 2)
# Braucht die Quell-Topics: Raeder (clearpath-platform) + Arm/Greifer
# (clearpath-manipulators + rg6-bringup). NUR Ordering (After), KEIN PartOf: die
# Subscriptions reconnecten von selbst, wenn eine Quelle spaeter/erneut hochkommt
# -> ein Arm-Neustart soll das Aggregat/den Relay nicht mit-bouncen.
After=clearpath-platform.service clearpath-manipulators.service rg6-bringup.service
Wants=clearpath-platform.service

[Service]
User=${REAL_USER}
ExecStart=${JS_WRAPPER}
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
chmod 0644 "$JS_UNIT_PATH"

# --- robot.yaml aus dem Repo deployen + Boot-Update-Service -----------------
# Das Git-Repo ist die SSOT. Wrapper laedt robot.yaml aus dem Repo, validiert
# (nicht-leer + gueltiges YAML) und installiert sie nur bei Abweichung (Backup).
# robot-yaml-update.service zieht sie bei JEDEM Boot VOR clearpath-robot.service
# nach, sodass die Generierung die Repo-Version nutzt.
echo ">>> Installiere ${ROBOT_YAML_WRAPPER} + ${ROBOT_YAML_UNIT}"
cat > "$ROBOT_YAML_WRAPPER" <<'ROBOT_YAML_EOF'
#!/usr/bin/env bash
# Laedt robot.yaml aus dem Git-Repo (SSOT) und installiert sie nach $2, wenn sie
# sich unterscheidet. Aufruf: robot-yaml-update.sh <URL> <ZIELPFAD>.
# Wird VOR clearpath-robot.service ausgefuehrt -> die Config-Generierung nutzt
# die neue robot.yaml. Bei fehlendem Netz/Download-Fehler bleibt die vorhandene
# robot.yaml unveraendert (Boot wird NICHT blockiert -> exit 0).
set -uo pipefail

URL="${1:?URL fehlt}"
DEST="${2:?Zielpfad fehlt}"
TAG="robot-yaml-update"
log() { echo "${TAG}: $*"; }

tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT

# Download mit Timeout; bei Fehler vorhandene Datei behalten.
if ! curl -fsSL --connect-timeout 5 --max-time 30 "$URL" -o "$tmp"; then
    log "WARN: Download fehlgeschlagen ($URL) - behalte vorhandene ${DEST}."
    exit 0
fi

# Nicht-leer? (curl -f faengt HTTP-Fehler ab, aber sicher ist sicher)
if [ ! -s "$tmp" ]; then
    log "WARN: heruntergeladene robot.yaml ist leer - behalte vorhandene ${DEST}."
    exit 0
fi

# Gueltiges YAML? Verhindert, dass eine kaputte Datei die Generierung bricht.
if command -v python3 >/dev/null 2>&1; then
    if ! python3 -c 'import yaml,sys; yaml.safe_load(open(sys.argv[1]))' "$tmp" 2>/dev/null; then
        log "WARN: heruntergeladene robot.yaml ist kein gueltiges YAML - behalte vorhandene ${DEST}."
        exit 0
    fi
fi

# Unveraendert? -> nichts tun (idempotent).
if [ -f "$DEST" ] && cmp -s "$tmp" "$DEST"; then
    log "robot.yaml bereits aktuell - keine Aenderung."
    exit 0
fi

install -d -m 0755 "$(dirname "$DEST")"
note=""
if [ -f "$DEST" ]; then
    cp -a "$DEST" "${DEST}.bak.$(date +%Y%m%d%H%M%S)"
    note=" (Backup angelegt)"
fi
install -m 0644 "$tmp" "$DEST"
log "robot.yaml aus Repo aktualisiert -> ${DEST}${note}."
ROBOT_YAML_EOF
chmod 0755 "$ROBOT_YAML_WRAPPER"

cat > "$ROBOT_YAML_UNIT_PATH" <<EOF
[Unit]
Description=robot.yaml aus dem Git-Repo nachziehen (Repo = SSOT), vor der Config-Generierung
# Braucht Netz -> nach network-online. Ohne Netz bleibt die vorhandene robot.yaml
# erhalten (Wrapper beendet mit 0), der Boot laeuft normal weiter.
Wants=network-online.target
After=network-online.target
# VOR der Generierung: clearpath-robot.service liest robot.yaml in seinem
# ExecStartPre (clearpath-robot-generate) -> die neue Version wird uebernommen.
Before=clearpath-robot.service

[Service]
Type=oneshot
RemainAfterExit=yes
SyslogIdentifier=robot-yaml-update
StandardOutput=journal
StandardError=journal
ExecStart=${ROBOT_YAML_WRAPPER} '${ROBOT_YAML_URL}' '${ROBOT_YAML_PATH}'

[Install]
WantedBy=multi-user.target
EOF
chmod 0644 "$ROBOT_YAML_UNIT_PATH"

# robot.yaml jetzt einmalig aus dem Repo ziehen (mit Rueckfrage vor erstem
# Ueberschreiben). Danach uebernimmt der Boot-Service das automatisch.
DO_ROBOT_YAML=1
if [ -f "$ROBOT_YAML_PATH" ]; then
    confirm ">>> robot.yaml jetzt aus dem Repo aktualisieren (${ROBOT_YAML_PATH} wird bei Abweichung ueberschrieben; Backup wird angelegt)?" || DO_ROBOT_YAML=0
fi
if [ "$DO_ROBOT_YAML" -eq 1 ]; then
    echo ">>> Ziehe robot.yaml aus dem Repo (${ROBOT_YAML_URL})"
    "$ROBOT_YAML_WRAPPER" "$ROBOT_YAML_URL" "$ROBOT_YAML_PATH" || echo "    WARN: robot.yaml-Update fehlgeschlagen - vorhandene Datei bleibt."
else
    echo ">>> robot.yaml: einmaliges Update uebersprungen (Boot-Service zieht sie beim naechsten Boot)."
fi

# --- aktivieren ------------------------------------------------------------
echo ">>> systemd neu einlesen + Services aktivieren"
systemctl daemon-reload
systemctl enable "$UNIT_NAME" "$RG6_UNIT" "$JS_UNIT" "$ROBOT_YAML_UNIT"
[ -f "$UR_DASH_UNIT_PATH" ] && systemctl enable "$UR_DASH_UNIT"
[ -f "$USM_UNIT_PATH" ] && systemctl enable "$USM_UNIT"
[ -f "$ARM_CTRL_UNIT_PATH" ] && systemctl enable "$ARM_CTRL_UNIT"
# Watchdog: den TIMER aktivieren (die .service ist der oneshot-Check, den er triggert).
[ -f "$WD_TIMER_PATH" ] && systemctl enable "$WD_TIMER"

echo ">>> Unit-Syntax pruefen"
VERIFY_UNITS=("$UNIT_PATH" "$RG6_UNIT_PATH" "$JS_UNIT_PATH" "$ROBOT_YAML_UNIT_PATH")
[ -f "$UR_DASH_UNIT_PATH" ] && VERIFY_UNITS+=("$UR_DASH_UNIT_PATH")
[ -f "$USM_UNIT_PATH" ] && VERIFY_UNITS+=("$USM_UNIT_PATH")
[ -f "$ARM_CTRL_UNIT_PATH" ] && VERIFY_UNITS+=("$ARM_CTRL_UNIT_PATH")
[ -f "$WD_UNIT_PATH" ] && VERIFY_UNITS+=("$WD_UNIT_PATH" "$WD_TIMER_PATH")
systemd-analyze verify "${VERIFY_UNITS[@]}" && echo "    Units OK."

# --- Patches jetzt einmal anwenden -----------------------------------------
if [ -f "$FOXGLOVE_YAML" ]; then
    echo ">>> Wende Config-Patches jetzt einmalig an"
    "$PY_PATH" || true
fi

echo
echo "=============================================================="
echo "Installation abgeschlossen."
echo "  clearpath-custom-setup.service : patcht Configs bei jedem Boot"
echo "  robot-yaml-update.service      : zieht robot.yaml aus dem Repo (SSOT) vor der Generierung"
echo "  rg6-bringup.service            : startet rg6_control + joint_state_broadcaster + urscript_interface"
echo "  joint-states.service           : joint_state_aggregator + Legacy-Bus-Relays (Phase 2)"
[ -f "$UR_DASH_UNIT_PATH" ] && \
echo "  ur-dashboard.service           : startet ur_robot_driver dashboard_client"
[ -f "$USM_UNIT_PATH" ] && \
echo "  ur-state-manager.service       : startet ur_state_manager (prepare/recover)"
[ -f "$ARM_CTRL_UNIT_PATH" ] && \
echo "  arm-controllers.service        : laedt Extra-Controller + Mode-Manager"
[ -f "$WD_TIMER_PATH" ] && \
echo "  manipulators-watchdog.timer    : Treiber-Neustart, wenn der Arm erst spaet eingeschaltet wird"
echo
echo "Damit ALLES greift, einmal neu starten:"
echo "  sudo systemctl restart clearpath-robot.service   # oder reboot"
echo
echo "Logs:"
echo "  journalctl -t clearpath-custom-setup -b"
echo "  journalctl -t robot-yaml-update -b"
echo "  journalctl -u rg6-bringup.service -b"
echo "  journalctl -u joint-states.service -b"
[ -f "$UR_DASH_UNIT_PATH" ] && \
echo "  journalctl -u ur-dashboard.service -b"
[ -f "$USM_UNIT_PATH" ] && \
echo "  journalctl -u ur-state-manager.service -b"
[ -f "$ARM_CTRL_UNIT_PATH" ] && \
echo "  journalctl -u arm-controllers.service -b"
[ -f "$WD_TIMER_PATH" ] && \
echo "  journalctl -t manipulators-watchdog -b   # + 'systemctl list-timers manipulators-watchdog.timer'"
echo
echo "Hinweis: robot.yaml wird ab jetzt aus dem Git-Repo verwaltet (SSOT)."
echo "  Aenderungen (platform.extras.urdf, system.ros2.workspaces, Arm-/Sensor-Config)"
echo "  im Repo pflegen -> robot-yaml-update.service zieht sie beim naechsten Boot."
echo "  Lokale Aenderungen an ${ROBOT_YAML_PATH} werden dann ueberschrieben (Backup .bak.*)."
echo "=============================================================="
