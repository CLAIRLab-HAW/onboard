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
#   - clearpath-custom-rg6-bringup.service: startet rg6_control + joint_state_broadcaster + urscript_interface beim Boot
#     (io_and_status_controller wird von Clearpath aus der robot.yaml gespawnt)
#   - optional: clearpath-custom-ur-dashboard.service: startet den ur_robot_driver dashboard_client
#     (power_on/brake_release/unlock_protective_stop/restart_safety) beim Boot
#   - optional: clearpath-custom-ur-state-manager.service: klont+baut ur-state-manager und startet
#     den State-Manager (prepare/recover/ensure_ready/power_off) beim Boot
#     (inkl. Extra-Controller --inactive + ur_controller_mode_manager -- seit 2026-07-29
#     Teil desselben Launch, keine eigene arm-controllers-Unit mehr)
#   - optional: clearpath-custom-manipulators-watchdog.timer: startet clearpath-manipulators.service
#     neu, wenn der Arm erst LANGE nach dem Boot bestromt wird (ros2_control retryt
#     die einmalig gescheiterte HW-Aktivierung nicht -> Treiber bleibt tot). Prueft
#     "Arm pingbar, aber robot_program_running publisht nicht" und startet EINMAL neu.
#   - robot.yaml: Repo klonen und /etc/clearpath/robot.yaml als SYMLINK darauf setzen
#     (offizieller Clearpath-Weg). Seit 2026-07-29 statt des Boot-Downloads: keine
#     Netzabhaengigkeit im Bootpfad, reproduzierbar, und ein 'git pull' wirkt sofort
#     (clearpath-robot-check md5summt die Datei im Sekundentakt).
#
# Hinweis robot.yaml: Das Repo ist die Single Source of Truth, /etc/clearpath/robot.yaml
#   ist ein SYMLINK darauf. Aenderungen also im Repo-Klon pflegen - sie wirken sofort
#   (clearpath-robot-check startet den Stack bei Inhaltsaenderung neu).
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
# UR-Control-Box + manipulators-Namespace: EINE Quelle fuer Dashboard, Watchdog
# und Kalibrierung (Sektions-Variablen unten leiten sich hieraus ab).
ARM_ROBOT_IP="192.168.131.40"
MANIP_NS="/a200_0553/manipulators"
BIN_DIR="/usr/local/bin"
PY_PATH="${BIN_DIR}/clearpath-custom-setup.py"
UNIT_NAME="clearpath-custom-setup.service"
UNIT_PATH="/etc/systemd/system/${UNIT_NAME}"
FOXGLOVE_YAML="/etc/clearpath/platform/config/foxglove_bridge.yaml"

RG6_WRAPPER="${BIN_DIR}/rg6-bringup.sh"
RG6_UNIT="clearpath-custom-rg6-bringup.service"
RG6_UNIT_PATH="/etc/systemd/system/${RG6_UNIT}"
# Root-eigene Kopie des rg6_moveit_patch-Tools (siehe Kopier-Schritt nach dem
# rg6-Build). Der Boot-Service clearpath-custom-setup (root) ruft NUR diese
# Kopie auf - nie direkt den user-schreibbaren Workspace.
RG6_MOVEIT_PATCH_BIN="${BIN_DIR}/rg6-moveit-patch"

# Octomap-Feed (Schritt 2 der HRL-Hindernis-Architektur): gedrosselte
# Depth->PointCloud2-Quelle fuer MoveIts Occupancy Map Monitor, damit
# move_group auch UNGETRACKTEN Hindernissen ausweicht (dichte Voxel-Schicht;
# die objekt-basierten Boxen von der Workstation bleiben fuer Task-Objekte + Twin).
# Kanonische Quelle im Repo (scripts/octomap_feed.py, SSOT wie robot.yaml);
# root-eigene Kopie unter /usr/local/bin, gestartet vom Boot-Service. Die
# move_group-Sensorparameter setzt der Boot-Patcher (Schritt 5) NUR, wenn
# die Unit-Datei existiert.
OCTO_FEED_URL="https://raw.githubusercontent.com/CLAIRLab-HAW/husky-custom-setup/refs/heads/main/scripts/octomap_feed.py"
OCTO_FEED_BIN="${BIN_DIR}/octomap-feed"
OCTO_WRAPPER="${BIN_DIR}/octomap-feed.sh"
OCTO_UNIT="clearpath-custom-octomap-feed.service"
OCTO_UNIT_PATH="/etc/systemd/system/${OCTO_UNIT}"

# Manipulator-Diagnose: uebersetzt UR-Mode/Safety/ExternalControl und den
# RG6-Zustand in diagnostic_msgs und publiziert sie auf dem /diagnostics-Topic,
# das der Clearpath-diagnostic_aggregator abonniert. Erst damit taucht der
# Manipulator ueberhaupt in diagnostics_agg auf -- also in Cockpit,
# rqt_robot_monitor und im Diagnose-Capture. Den passenden Analyzer-Block
# traegt der Boot-Patcher (Schritt 6) ein, NUR wenn diese Unit existiert.
MD_FEED_URL="https://raw.githubusercontent.com/CLAIRLab-HAW/husky-custom-setup/refs/heads/main/scripts/manipulator_diagnostics.py"
MD_BIN="${BIN_DIR}/manipulator-diagnostics"
MD_WRAPPER="${BIN_DIR}/manipulator-diagnostics.sh"
MD_UNIT="clearpath-custom-manipulator-diagnostics.service"
MD_UNIT_PATH="/etc/systemd/system/${MD_UNIT}"

# Cockpit-Plugin (Fork von clearpathrobotics/cockpit-ros2-diagnostics mit dem
# Manipulator-Panel). Cockpit sucht Pakete in dieser Reihenfolge:
# ~/.local/share/cockpit, /etc/cockpit, /usr/local/share/cockpit,
# /usr/share/cockpit -- der Fork unter /usr/local ueberdeckt also das
# apt-Paket unter /usr/share, ohne es anzufassen. Deinstallation =
# Verzeichnis loeschen, dann ist das Original wieder aktiv (kein apt noetig).
# Der Verzeichnisname MUSS 'ros2-diagnostics' sein (package.json "name"), sonst
# ueberdeckt er nicht, sondern erscheint als zweiter Menuepunkt.
CKPT_REPO_URL="https://github.com/CLAIRLab-HAW/cockpit-ros2-diagnostics.git"
CKPT_PKG_DIR="/usr/local/share/cockpit/ros2-diagnostics"

# UR dashboard_client: Clearpath startet ihn im headless-Setup NICHT mit, liefert
# aber power_on/brake_release/unlock_protective_stop/restart_safety/get_*_mode.
# Kein Build noetig (kommt aus ros-jazzy-ur-robot-driver). robot_ip = UR-Control-Box.
UR_DASH_WRAPPER="${BIN_DIR}/ur-dashboard.sh"
UR_DASH_UNIT="clearpath-custom-ur-dashboard.service"
UR_DASH_UNIT_PATH="/etc/systemd/system/${UR_DASH_UNIT}"
UR_DASH_NS="${MANIP_NS}"
UR_DASH_ROBOT_IP="${ARM_ROBOT_IP}"

# ur-state-manager: prepare/recover/ensure_ready/power_off-Services fuer den Arm.
# Wird (wie onrobot-rg6) geklont+gebaut und per Boot-Service gestartet. Braucht den
# dashboard_client (clearpath-custom-ur-dashboard.service) -> startet das Launch mit start_dashboard_client:=false.
USM_WRAPPER="${BIN_DIR}/ur-state-manager.sh"
USM_UNIT="clearpath-custom-ur-state-manager.service"
USM_UNIT_PATH="/etc/systemd/system/${USM_UNIT}"

# arm-controllers: laedt die Extra-Controller (--inactive) + Mode-Manager beim Boot.
# Nutzt denselben ur-state-manager-Workspace (kein eigener Build).
# arm-controllers: 2026-07-29 ABGELOEST. Die Extra-Controller (--inactive) und der
# ur_controller_mode_manager kommen jetzt aus ur_state_manager.launch.py
# (Argument load_arm_controllers, Default true): gleiches Paket, gleicher Workspace,
# gleicher User, identischer Lifecycle -> kein Grund fuer eine zweite Unit.
ARM_CTRL_OLD_UNIT="clearpath-custom-arm-controllers.service"
ARM_CTRL_OLD_WRAPPER="${BIN_DIR}/arm-controllers.sh"

# joint-states (Phase 2): robot-weiter joint_state_aggregator (/a200_0553/joint_states)
# + Relays der sauberen Arm-/Greifer-Quell-Topics zurueck auf den platform/joint_states-
# Bus (fuer RSP + move_group). Nutzt den onrobot-rg6-Workspace (rg6_control
# joint_states.launch.py), kein eigener Build.
JS_WRAPPER="${BIN_DIR}/joint-states.sh"
JS_UNIT="clearpath-custom-joint-states.service"
JS_UNIT_PATH="/etc/systemd/system/${JS_UNIT}"

# manipulators-watchdog: deckt ZWEI Luecken ab, die auf ROS-Ebene NICHT loesbar sind.
#  (a) Wird der UR erst LANGE NACH dem Boot bestromt, scheitert die einmalige
#      ros2_control-HW-Aktivierung des ur_robot_driver (Arm war stromlos) - und
#      ros2_control retryt sie NICHT. Folge: JSC stumm, Arm bleibt "Stopped".
#  (b) clearpath-robot.service-Restart bei schon bestromtem Arm: alte ExternalControl-
#      Instanz haelt das Reverse-Socket, neue HW-Aktivierung schlaegt fehl -> JSC
#      stumm -> Arm in RViz flach. (robot_program_running allein ist KEIN Health-Signal:
#      controller-seitig, bleibt 'true' bei totem PC-Motion-Link.)
# Health-Signal ist daher der joint_state_broadcaster-Stream (.../manipulators/
# joint_states). Dieser Timer erkennt "Arm pingbar, aber JSC stumm" und startet
# clearpath-manipulators.service EINMAL neu (mit Cooldown gegen Schleifen). Zusaetzlich
# legt ein SIGINT-Stop-Drop-in auf clearpath-manipulators.service Ros-Graceful-Shutdown
# statt SIGTERM-Ignore (90s Zombie mit Socket-Kollision) fest.
WD_WRAPPER="${BIN_DIR}/manipulators-watchdog.sh"
WD_UNIT="clearpath-custom-manipulators-watchdog.service"
WD_UNIT_PATH="/etc/systemd/system/${WD_UNIT}"
WD_TIMER="clearpath-custom-manipulators-watchdog.timer"
WD_TIMER_PATH="/etc/systemd/system/${WD_TIMER}"
WD_ROBOT_IP="${ARM_ROBOT_IP}"
WD_PROGRAM_TOPIC="${MANIP_NS}/io_and_status_controller/robot_program_running"
# SIGINT-Stop-Drop-in fuer clearpath-manipulators.service (sauberes Treiber-Shutdown,
# siehe Skript-Kommentar). Drop-in ueberlebt Clearpath-Package-Updates (layert ueber
# /usr/lib/systemd/system/clearpath-manipulators.service).
WD_MANIP_DROPIN_DIR="/etc/systemd/system/clearpath-manipulators.service.d"
WD_MANIP_DROPIN="${WD_MANIP_DROPIN_DIR}/override.conf"

# robot.yaml: Das Git-Repo ist die Single Source of Truth. Beim Boot wird die
# robot.yaml VOR der Config-Generierung (clearpath-robot.service) aus dem Repo
# nachgezogen. Ohne Netz/bei Fehler bleibt die vorhandene Datei erhalten.
SETUP_REPO_URL="https://github.com/CLAIRLab-HAW/husky-custom-setup.git"
ROBOT_YAML_PATH="/etc/clearpath/robot.yaml"

# Fruehere Custom-Unit-Namen (ohne clearpath-custom--Prefix) + der alte
# Vorgaenger-Service: der Installer disable+rm sie, BEVOR er die neuen
# clearpath-custom-*-Units schreibt+aktiviert (saubere Migration des Rename).
OLD_UNIT="clearpath-set-update-rate.service"
OLD_UNITS=(
  "${OLD_UNIT}"
  "rg6-bringup.service"
  "ur-dashboard.service"
  "ur-state-manager.service"
  "arm-controllers.service"
  "joint-states.service"
  "manipulators-watchdog.service"
  "manipulators-watchdog.timer"
  "robot-yaml-update.service"
)
OLD_FILES=("${BIN_DIR}/set-update-rate.py" "${BIN_DIR}/wait-for-clearpath.sh")
# Verwaiste Drop-in-Verzeichnisse der alten Namen (Prefix-Rename -> Drop-in-Pfad
# passt nicht mehr zur neuen Unit; Inhalt ist PartOf=clearpath-manipulators, das
# die neue Unit ohnehin schon selbst traegt -> sicher zu entfernen).
OLD_DIRS=("/etc/systemd/system/joint-states.service.d")
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

# Timestamp-Backups ("<datei>.bak.<zeitstempel>") rotieren: nur die KEEP neuesten
# behalten (Default 5). Nie fatal (leeres Glob etc.) -> set -e-sicher.
prune_backups() {
    local file="$1" keep="${2:-5}"
    ls -1t "${file}".bak.* 2>/dev/null | tail -n "+$((keep + 1))" | xargs -r rm -f -- || true
}

# Realer Nutzer (fuer den Workspace-Build), nicht root:
REAL_USER="${SUDO_USER:-robot}"
USER_HOME="$(getent passwd "$REAL_USER" | cut -d: -f6)"
RG6_WS="${USER_HOME}/onrobot-rg6"
USM_WS="${USER_HOME}/ur-state-manager"
SETUP_WS="${USER_HOME}/husky-custom-setup"   # versionierte robot.yaml (Symlink-Ziel)
CKPT_WS="${USER_HOME}/cockpit-ros2-diagnostics"

if [ "$RG6_REPO_URL" = "REPLACE_WITH_GIT_URL" ]; then
    echo "FEHLER: Bitte oben im Skript RG6_REPO_URL auf die Git-URL von onrobot-rg6 setzen."
    exit 1
fi

# --- Vorgaenger-/Alt-Namen abloesen (Migration auf clearpath-custom-*) ------
# Alle alten Custom-Unit-Namen disable+stop+rm, bevor die neuen clearpath-custom-*
# Units geschrieben+aktiviert werden. Fenster: alte Services kurz gestoppt ->
# neue direkt danach aktiviert (Wartungszeitpunkt; Arm ggf. neu prepare).
#
# WICHTIG: nicht nur auf list-unit-files pruefen. Wurde die Unit-Datei bei einem
# frueheren Lauf schon entfernt, der Prozess aber nicht gestoppt, laeuft die Unit
# als "not-found aber active" weiter - und fehlt in list-unit-files. Solche
# Zombies (Boot-Prozesse unter altem Namen, z.B. doppelter ur_state_manager mit
# altem auto_recover) faengt nur der is-active-Check. 'systemctl stop' wirkt
# auch auf not-found-Units (systemd fuehrt sie in-memory weiter); 'disable'
# dagegen braucht die Unit-Datei -> getrennt und Fehler dort tolerieren.
# Stop-Fehler NICHT verschlucken, sondern laut warnen (sonst laufen alte
# Prozesse unbemerkt neben den neuen Units weiter).
for u in "${OLD_UNITS[@]}"; do
    known=0
    systemctl list-unit-files 2>/dev/null | grep -q "^${u}" && known=1
    state="$(systemctl is-active "${u}" 2>/dev/null || true)"
    if [ "$known" = "1" ] || [ "$state" = "active" ] || [ "$state" = "activating" ]; then
        echo ">>> Entferne alte Unit ${u} (state=${state:-unbekannt})"
        systemctl disable "${u}" 2>/dev/null || true
        if ! systemctl stop "${u}" 2>/dev/null; then
            echo "    WARN: 'systemctl stop ${u}' fehlgeschlagen - alte Prozesse"
            echo "    laufen ggf. weiter (pruefen: systemctl status ${u})."
        fi
    fi
    rm -f "/etc/systemd/system/${u}"
done
for f in "${OLD_FILES[@]}"; do
    [ -e "$f" ] && { echo ">>> Entferne alte Datei $f"; rm -f "$f"; }
done
for d in "${OLD_DIRS[@]}"; do
    [ -d "$d" ] && { echo ">>> Entferne verwaistes Verzeichnis $d"; rm -rf "$d"; }
done
# Stale Backup-Leichen der alten Namen raeumen (Commit a13f226 hat das Stapfen
# beim Installer behoben; alte .bak.* vom letzten Stand liegen aber noch auf Platte).
rm -f /etc/systemd/system/manipulators-watchdog.service.bak.* \
      /usr/local/bin/manipulators-watchdog.sh.bak.* 2>/dev/null || true

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
     (rg6_control joint_states.launch.py, clearpath-custom-joint-states.service) haelt den
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





AGGREGATOR_YAML = "/etc/clearpath/platform/config/diagnostic_aggregator.yaml"
MANIPULATOR_UNIT_FILE = (
    "/etc/systemd/system/clearpath-custom-manipulator-diagnostics.service")
MANIPULATOR_STATUS_PREFIX = "manipulator_diagnostics"

# Analyzer-Block fuer den Manipulator, flach mit Punkt-Keys geschrieben.
# ROS 2 behandelt 'a.b: 1' und 'a: {b: 1}' identisch (beides ergibt den
# Parameter 'a.b') -- flach zu schreiben macht den Patch unabhaengig davon,
# ob der Generator die uebrigen Analyzer verschachtelt oder flach ablegt.
# 'expected' ist wichtig: fehlt ein Status (Node tot), erzeugt der Aggregator
# dafuer einen STALE-Eintrag, statt ihn stillschweigend verschwinden zu lassen.
MANIPULATOR_ANALYZERS = {
    "manipulator.type": "diagnostic_aggregator/AnalyzerGroup",
    "manipulator.path": "Manipulator",
    "manipulator.analyzers.arm.type": "diagnostic_aggregator/GenericAnalyzer",
    "manipulator.analyzers.arm.path": "Arm",
    "manipulator.analyzers.arm.startswith": [f"{MANIPULATOR_STATUS_PREFIX}: Arm"],
    "manipulator.analyzers.arm.expected": [
        f"{MANIPULATOR_STATUS_PREFIX}: Arm Mode",
        f"{MANIPULATOR_STATUS_PREFIX}: Arm Control",
        f"{MANIPULATOR_STATUS_PREFIX}: Arm Joints",
        f"{MANIPULATOR_STATUS_PREFIX}: Arm Controllers",
    ],
    "manipulator.analyzers.gripper.type": "diagnostic_aggregator/GenericAnalyzer",
    "manipulator.analyzers.gripper.path": "Gripper",
    "manipulator.analyzers.gripper.startswith": [
        f"{MANIPULATOR_STATUS_PREFIX}: Gripper"],
    "manipulator.analyzers.gripper.expected": [
        f"{MANIPULATOR_STATUS_PREFIX}: Gripper"],
}


def add_manipulator_analyzers(label):
    """Manipulator-Analyzer in die generierte diagnostic_aggregator.yaml (Schritt 6).

    clearpath_generator_common erzeugt Analyzer nur fuer Platform (Power,
    E-Stop, Drive) und Sensoren -- Arm und Greifer kommen im Generator gar
    nicht vor.  Ohne diesen Block landen die Status des
    manipulator_diagnostics-Node im Catch-All des Aggregators (bzw. gar nicht)
    und tauchen in Cockpit nicht als eigene Gruppe auf.

    Nur aktiv, wenn der manipulator-diagnostics-Boot-Service installiert ist
    (die Unit-Datei ist der Schalter, wie beim octomap-feed): Datei loeschen
    + Reboot = Analyzer wieder weg.  Idempotent, .bak, atomar.
    """
    if not os.path.exists(MANIPULATOR_UNIT_FILE):
        log(f"{label}: manipulator-diagnostics nicht installiert - uebersprungen.")
        return False
    try:
        import yaml
    except ImportError:
        log(f"{label}: PyYAML fehlt (apt: python3-yaml) - uebersprungen.", err=True)
        return False
    if not os.path.isfile(AGGREGATOR_YAML):
        log(f"{label}: {AGGREGATOR_YAML} fehlt (Generierung gelaufen?) - "
            "uebersprungen.", err=True)
        return False
    try:
        with open(AGGREGATOR_YAML) as f:
            data = yaml.safe_load(f)
    except (OSError, yaml.YAMLError) as e:
        log(f"{label}: {AGGREGATOR_YAML} nicht lesbar: {e}", err=True)
        return False
    if not isinstance(data, dict):
        log(f"{label}: {AGGREGATOR_YAML} hat unerwartetes Format - uebersprungen.",
            err=True)
        return False

    # Der Generator schreibt <namespace>: <node>: ros__parameters: ...
    # Die Namespace-Ebene kann je nach Version fehlen -> beide Formen suchen.
    params = None
    if "diagnostic_aggregator" in data:
        params = data["diagnostic_aggregator"].get("ros__parameters")
    else:
        for val in data.values():
            if isinstance(val, dict) and "diagnostic_aggregator" in val:
                params = val["diagnostic_aggregator"].get("ros__parameters")
                break
    if not isinstance(params, dict):
        log(f"{label}: kein diagnostic_aggregator.ros__parameters - uebersprungen.",
            err=True)
        return False

    # Schon verschachtelt vorhanden (z.B. von Hand eingetragen)? Dann nicht
    # zusaetzlich flach danebenschreiben - das gaebe doppelte Analyzer.
    if isinstance(params.get("manipulator"), dict):
        log(f"{label}: bereits (verschachtelt) vorhanden.")
        return False

    changed = False
    for key, value in MANIPULATOR_ANALYZERS.items():
        if params.get(key) != value:
            params[key] = value
            changed = True
    if not changed:
        log(f"{label}: bereits korrekt.")
        return False

    backup = AGGREGATOR_YAML + ".bak"
    if not os.path.exists(backup):
        try:
            shutil.copy2(AGGREGATOR_YAML, backup)
        except OSError:
            pass
    tmp = AGGREGATOR_YAML + ".tmp"
    try:
        with open(tmp, "w") as f:
            yaml.safe_dump(data, f, sort_keys=False, default_flow_style=False)
        os.replace(tmp, AGGREGATOR_YAML)
    except OSError as e:
        log(f"{label}: kann {AGGREGATOR_YAML} nicht schreiben: {e}", err=True)
        return False
    log(f"{label}: Analyzer-Gruppe 'Manipulator' (Arm + Gripper) eingetragen.")
    return True


def run_rg6_moveit_patch(label):
    """RG6 in die frisch generierte MoveIt-Config einhaengen.

    Delegiert an die root-eigene Kopie des selbst-enthaltenen Tools aus dem
    onrobot-rg6-Repo (rg6_moveit_patch: robot.srdf + manipulators/config/
    moveit.yaml, idempotent), die der Installer nach /usr/local/bin kopiert.
    Bewusst KEIN Aufruf direkt aus /home/*: dieser Service laeuft als root -
    Code aus einem user-schreibbaren Workspace waere eine Rechteausweitung
    (Workspace-/Repo-Schreibzugriff -> root bei jedem Boot). Die Kopie aendert
    sich nur durch einen erneuten Installer-Lauf (explizite Admin-Entscheidung).
    Muss NACH clearpath-robot-generate und VOR clearpath-manipulators laufen -
    genau das Fenster dieses Services. Fehlt die Kopie (Installer nie mit
    vorhandenem onrobot-rg6-Workspace gelaufen), wird nur gewarnt."""
    import subprocess
    tool = "/usr/local/bin/rg6-moveit-patch"
    if not os.path.isfile(tool):
        log(f"{label}: {tool} fehlt (Installer mit onrobot-rg6-Workspace "
            "laufen lassen) - MoveIt ohne Greifer.", err=True)
        return False
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
    #    manipulators/joint_states (Relay + Aggregator via clearpath-custom-joint-states.service).
    move_arm_joint_states("arm joint_states -> manipulators")
    # 4) RG6 in MoveIt: robot.srdf (Gruppe 'gripper' + EE) und moveit.yaml
    #    (GripperCommand-Controller + joint_limits) patchen (onrobot-rg6-Tool).
    run_rg6_moveit_patch("rg6 moveit")
    # 5) ENTFERNT 2026-07-29 (A4): die Occupancy-Map-Monitor-Sensorparameter
    #    stehen jetzt nativ in robot.yaml unter
    #    manipulators.moveit.ros_parameters.move_group - der Generator
    #    schreibt sie selbst in moveit.yaml. Kein Patch mehr noetig.
    # 6) Manipulator-Analyzer in die generierte diagnostic_aggregator.yaml --
    #    NUR wenn der manipulator-diagnostics-Boot-Service installiert ist.
    #    Erst damit erscheinen Arm + Greifer als eigene Gruppe in
    #    diagnostics_agg (Cockpit, rqt_robot_monitor, Diagnose-Capture).
    add_manipulator_analyzers("manipulator analyzers")
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
SUBSYSTEM=="tty", ATTRS{idVendor}=="0403", ATTRS{idProduct}=="6001", ATTRS{serial}=="A908RWEO", SYMLINK+="clearpath/um7", MODE="0666"

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

# --- UR-Treiber-Ports vor der Ephemeral-Vergabe schuetzen -------------------
# ur_client_library bindet FESTE Ports: 50001 reverse, 50002 script sender,
# 50003 trajectory, 50004 script command. Alle vier liegen im flüchtigen
# Portbereich des Kernels (net.ipv4.ip_local_port_range = 32768-60999) -> jeder
# andere Prozess kann einen davon fuer eine AUSGEHENDE Verbindung zugewiesen
# bekommen, bevor der Arm-Treiber ihn bindet. Passiert am 2026-07-29 real:
# der image_processing_container (clearpath-platform) zog 50004 als Quellport
# fuer eine Loopback-Verbindung zu teleop_node -> der Treiber scheiterte mit
# "Failed to bind socket for port 50004. Reason: Address already in use" und
# hing in einer Retry-Schleife; die Controller-Spawner gaben nach 5 Versuchen
# auf -> Arm ohne Controller. Ein Treiber-Neustart half NICHT (die fremde
# Verbindung lebte weiter) - erst ein Neustart von clearpath-platform gab den
# Port frei. Reservieren nimmt die Ports aus der automatischen Vergabe;
# explizites bind() durch den Treiber bleibt erlaubt. Rein additiv, idempotent.
SYSCTL_UR_PORTS="/etc/sysctl.d/10-ur-reserved-ports.conf"
echo ">>> Schreibe ${SYSCTL_UR_PORTS} (UR-Ports 50001-50004 reservieren)"
install -d -m 0755 /etc/sysctl.d
cat > "$SYSCTL_UR_PORTS" <<'SYSCTL_EOF'
# UR-Treiber-Ports (ur_client_library) aus der Ephemeral-Vergabe nehmen.
# Ohne das kann ein beliebiger Prozess 50001-50004 als Quellport belegen und
# der ur_robot_driver scheitert beim Binden ("Address already in use").
net.ipv4.ip_local_reserved_ports = 50001-50004
SYSCTL_EOF
chmod 0644 "$SYSCTL_UR_PORTS"
if sysctl -p "$SYSCTL_UR_PORTS" >/dev/null 2>&1; then
    echo "    aktiv: $(cat /proc/sys/net/ipv4/ip_local_reserved_ports)"
else
    echo "    WARN: sysctl -p fehlgeschlagen - greift spaetestens beim naechsten Boot."
fi

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
    if [ -f "$NETPLAN_FILE" ]; then
        cp -a "$NETPLAN_FILE" "${NETPLAN_FILE}.bak.$(date +%Y%m%d%H%M%S)"
        prune_backups "$NETPLAN_FILE"
    fi
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
    prune_backups "$GRUB_FILE"
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
UR_ROBOT_IP="${UR_ROBOT_IP:-${ARM_ROBOT_IP}}"
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
        if [ -f "$UR_CALIB_FILE" ]; then
            cp -a "$UR_CALIB_FILE" "${UR_CALIB_FILE}.bak.$(date +%Y%m%d%H%M%S)"
            prune_backups "$UR_CALIB_FILE"
        fi
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

# --- rg6_moveit_patch als root-eigene Kopie installieren --------------------
# Der Boot-Service clearpath-custom-setup laeuft als root und haengt den RG6
# in die MoveIt-Config. Das Tool dafuer stammt aus dem User-Workspace - es als
# root DIREKT von dort auszufuehren waere eine Rechteausweitung (wer in den
# Workspace schreiben kann, bekaeme root bei jedem Boot; via git pull sogar das
# Remote-Repo). Daher hier eine root-eigene Kopie: sie aendert sich nur durch
# einen erneuten Installer-Lauf, nicht durch Aenderungen im Workspace.
RG6_PATCH_SRC=""
for cand in "${RG6_WS}/install/rg6_control/lib/rg6_control/rg6_moveit_patch" \
            "${RG6_WS}/src/rg6_control/scripts/rg6_moveit_patch"; do
    [ -f "$cand" ] && { RG6_PATCH_SRC="$cand"; break; }
done
if [ -n "$RG6_PATCH_SRC" ]; then
    echo ">>> Installiere ${RG6_MOVEIT_PATCH_BIN} (Kopie von ${RG6_PATCH_SRC})"
    install -m 0755 -o root -g root "$RG6_PATCH_SRC" "$RG6_MOVEIT_PATCH_BIN"
elif [ -f "$RG6_MOVEIT_PATCH_BIN" ]; then
    echo ">>> rg6_moveit_patch: Workspace-Tool nicht gefunden - vorhandene Kopie ${RG6_MOVEIT_PATCH_BIN} bleibt."
else
    echo "    WARN: rg6_moveit_patch nicht gefunden (onrobot-rg6 geklont/gebaut?) - RG6-MoveIt-Patch beim Boot inaktiv, bis der Installer mit vorhandenem Workspace erneut laeuft."
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
# dieser Service muss ihn neu laden.
# PartOf propagiert Stop/Restart NUR eine Hop-Ebene und NUR bei DIREKTEM Job auf
# der Ziel-Unit (propagierte Jobs werden NICHT weitergereicht). Stack-Restart in
# der Praxis: 'systemctl restart clearpath-robot' -> clearpath-manipulators
# startet nur indirekt neu -> OHNE PartOf=clearpath-robot wuerde dieser Service
# nicht mit-restarten. Daher an BEIDE Wurzeln: robot (praktischer Stack-Restart)
# + manipulators (direkter Treiber-Restart). Stop clearpath-robot stoppt ihn mit.
PartOf=clearpath-robot.service clearpath-manipulators.service
# Aufgeben statt endlos neu starten. Ohne diese zwei Zeilen greift systemds
# Voreinstellung (DefaultStartLimitIntervalSec=10s, Burst=5) NIE: bei
# RestartSec=5 passen in ein 10-s-Fenster nur zwei Neustarts, die Grenze von
# fuenf wird nicht erreicht -- ein fehlgeschlagener colcon-Build erzeugt dann
# eine endlose 5-Sekunden-Schleife, die Logs flutet und CPU zieht, ohne je
# gruen zu werden. Am 2026-08-17 am Roboter nachgemessen (ROBOTER-TODO R5):
# StartLimitIntervalUSec=10s, StartLimitBurst=5, RestartSec=5.
# 120 s Fenster: fuenf Versuche dauern ~25 s, danach bleibt die Unit 'failed'
# stehen und ist als Fehler sichtbar, statt sich selbst zu verdecken.
StartLimitIntervalSec=120
StartLimitBurst=5

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
    confirm ">>> ${UR_DASH_UNIT} ist bereits installiert. Aktualisieren?" || DO_DASH=0
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
# A2: KEINE Kopplung an clearpath-manipulators. Der dashboard_client spricht
# ausschliesslich TCP:29999 mit der UR-Control-Box und braucht den ROS-Treiber
# nicht. Der Watchdog startet clearpath-manipulators neu und braucht die
# Dashboard-Services waehrend genau dieser Recovery durchgehend (get_robot_mode,
# get_safety_mode, resend_robot_program) - mit PartOf riss er sie selbst mit runter.
# Ordnung an clearpath-robot bleibt: erst danach existiert /etc/clearpath/setup.bash.
After=clearpath-robot.service
# PartOf nur an clearpath-robot: ein Stack-Stop/-Restart nimmt ihn mit,
# ein reiner Treiber-Restart (clearpath-manipulators) nicht.
PartOf=clearpath-robot.service

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
# dashboard_client (clearpath-custom-ur-dashboard.service) -> Launch mit start_dashboard_client:=false.
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
        || echo "    WARN: colcon build fehlgeschlagen - ${USM_UNIT} laeuft erst nach erfolgreichem Build."

    echo ">>> Installiere ${USM_WRAPPER} + ${USM_UNIT}"
    cat > "$USM_WRAPPER" <<EOF
#!/usr/bin/env bash
# Startet den ur_state_manager (prepare/recover/ensure_ready/power_off).
# start_dashboard_client:=false -> der dashboard_client laeuft via clearpath-custom-ur-dashboard.service.
# auto_recover:=false -> der auto_recover-Watcher AUS: er wuerde per 'recover'
#   die Bremsen loesen + ExternalControl starten (Arm -> RUNNING). Wir wollen nach
#   einem Restart aber NUR 'Treiber verbunden' (Arm bleibt IDLE, Bremsen angelegt,
#   kein automatisches Bremsenloesen/Bestromen). Zum Bewegen ruft der Bediener
#   manuell 'prepare'. Treiber-Connect passiert von selbst (JSC); der Watchdog ist
#   die Notbremse (nur Treiber-Restart, keine Bremsen/Bestromung).
source /etc/clearpath/setup.bash
source ${USM_WS}/install/setup.bash
exec ros2 launch ur_state_manager ur_state_manager.launch.py start_dashboard_client:=false auto_recover:=false
EOF
    chmod 0755 "$USM_WRAPPER"

    cat > "$USM_UNIT_PATH" <<EOF
[Unit]
Description=UR state manager (prepare/recover/ensure_ready/power_off fuer den UR5)
# Nach dem dashboard_client starten (liefert die Dashboard-Services). Ist
# clearpath-custom-ur-dashboard.service nicht installiert, ist das After= ein No-op.
After=clearpath-manipulators.service clearpath-custom-ur-dashboard.service
Wants=clearpath-manipulators.service
# Mit-Neustart: startet clearpath-manipulators (Treiber/controller_manager) neu,
# muss auch dieser Node neu starten - sonst zeigen der robot_state_helper und der
# Adapter auf stale io_and_status_controller-Topics/-Services.
# PartOf propagiert Stop/Restart nur eine Hop-Ebene und nur bei DIREKTEM Job auf
# der Ziel-Unit. Stack-Restart via 'systemctl restart clearpath-robot' startet
# clearpath-manipulators nur indirekt -> ohne PartOf=clearpath-robot wuerde dieser
# Service nicht mit-restarten. Daher an BEIDE Wurzeln (robot + manipulators);
# Stop clearpath-robot stoppt ihn dann mit.
PartOf=clearpath-robot.service clearpath-manipulators.service

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
# --- arm-controllers: abgeloeste Unit entfernen ---------------------------
if systemctl list-unit-files 2>/dev/null | grep -q "^${ARM_CTRL_OLD_UNIT}"; then
    echo ">>> Entferne abgeloeste ${ARM_CTRL_OLD_UNIT} (jetzt Teil von ur-state-manager)"
    systemctl disable --now "$ARM_CTRL_OLD_UNIT" 2>/dev/null || true
    rm -f "/etc/systemd/system/${ARM_CTRL_OLD_UNIT}" "$ARM_CTRL_OLD_WRAPPER"
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
# Watchdog: erkennt "Arm erreichbar, aber PC-seitiger Motion-Link (ur_robot_driver)
# NICHT verbunden". Health-Signal ist der joint_state_broadcaster-Stream auf
# .../manipulators/joint_states - der publisht NUR, wenn das ros2_control-HW-Interface
# aktiviert ist und reale Arm-Gelenke liest.
# robot_program_running allein reicht NICHT als "verbunden": das ist der
# controller-seitige ExternalControl-Status (via Dashboard/RTDE) und bleibt 'true',
# selbst wenn der PC-Motion-Link tot ist - z.B. haengebliebener Reconnect nach einem
# clearpath-robot.service-Restart bei schon bestromtem Arm (alte ExternalControl-
# Instanz haelt das Reverse-Socket, neue HW-Aktivierung schlaegt fehl, JSC bleibt
# inactive -> Topic stumm -> Arm in RViz flach). Deckt damit ZWEI Faelle ab:
#   (a) Kaltstart mit spaet bestromtem Arm: HW-Aktivierung einmalig gescheitert (Arm
#       war stromlos), ros2_control retryt sie nicht -> JSC stumm.
#   (b) Service-Restart mit schon bestromtem Arm: neue HW-Aktivierung schlaegt fehl
#       (Socket-Kollision mit der alten Instanz) -> JSC stumm.
# Recovery: Treiber neu starten (clearpath-manipulators.service) + ExternalControl
# neu starten (resend_robot_program). Der Arm wird NICHT automatisch bestromt
# (kein power_on/brake_release) - Bestromung ist Bediener-Entscheidung (schuetzt
# Wartung/Feierabend); ist der Arm POWER_OFF, laeuft keine Recovery (kein
# Treiber-Loop gegen stromlosen Arm). Protective-/Safety-Stops (safety_mode !=
# NORMAL) werden NICHT auto-gecleart (bleiben manuell) - resend uebersprungen.
# Aufruf: manipulators-watchdog.sh <ROBOT_IP> <TOPIC> <RUN_USER> <RUN_HOME>
#   TOPIC = .../io_and_status_controller/robot_program_running (Namespace wird
#   daraus abgeleitet; Dashboard- + Resend-Services + JSC-Topic unter demselben NS).
set -uo pipefail

ROBOT_IP="${1:?ROBOT_IP fehlt}"
TOPIC="${2:?TOPIC fehlt}"
RUN_USER="${3:?RUN_USER fehlt}"
RUN_HOME="${4:?RUN_HOME fehlt}"
SERVICE="clearpath-manipulators.service"
DASH_SVC="clearpath-custom-ur-dashboard.service"
COOLDOWN="${WD_COOLDOWN:-180}"          # s: nach einer Recovery so lange nicht erneut
JS_TIMEOUT="${WD_JS_TIMEOUT:-25}"      # s: auf JSC-Nachricht warten (JSC braucht nach manipulators-Restart bis ~15s -> grosszuegig, erst >JS_TIMEOUT ohne Nachricht = Motion-Link wirklich tot)
RPR_WAIT="${WD_RPR_WAIT:-15}"           # Iterationen: JSC-streamt-wieder-Bestaetigung nach resend
STATE="/run/manipulators-watchdog.state"
TAG="manipulators-watchdog"
log() { echo "${TAG}: $*"; }

# Namespace aus dem Topic ableiten (.../io_and_status_controller/robot_program_running).
NS="${TOPIC%/io_and_status_controller/*}"
DASH_NS="${NS}/dashboard_client"
RESEND_SVC="${NS}/io_and_status_controller/resend_robot_program"
JS_TOPIC="${NS}/joint_states"   # joint_state_broadcaster-Ausgang; lebt nur bei aktivem HW-Interface
PLATFORM_JS_TOPIC="${NS%/manipulators}/platform/joint_states"  # Fallback-Bus (s. Health-Check)
DRY_RUN="${WD_DRY_RUN:-0}"      # 1 = nur melden, was passieren wuerde (Test)
RPR_TOPIC="${TOPIC}"            # robot_program_running (latched/transient_local!)
RPR_TIMEOUT="${WD_RPR_TIMEOUT:-6}"      # s: auf den gelatchten Wert warten
RESEND_STATE="/run/manipulators-watchdog.resend"
RESEND_COOLDOWN="${WD_RESEND_COOLDOWN:-60}"  # s: nicht im Timer-Takt spammen

# ROS-Befehl als RUN_USER im selben Graphen ausfuehren.
ros_cmd() { sudo -u "$RUN_USER" env HOME="$RUN_HOME" bash -lc "source /etc/clearpath/setup.bash && $*"; }

# --- Helfer: Modus-/Safety-Abfrage und Trigger-Aufrufe (alle via Dashboard) ---
robot_mode() { ros_cmd "timeout 10 ros2 service call '${DASH_NS}/get_robot_mode' ur_dashboard_msgs/srv/GetRobotMode" 2>&1 | grep -oE 'Robotmode: [A-Z_]+' | head -1; }
safety_mode() { ros_cmd "timeout 10 ros2 service call '${DASH_NS}/get_safety_mode' ur_dashboard_msgs/srv/GetSafetyMode" 2>&1 | grep -oE 'Safetymode: [A-Z_]+' | head -1; }
call_trigger() {  # $1 Service-Pfad, $2 Timeout(s); 0 = success=True
    local svc="$1" t="${2:-12}"
    ros_cmd "timeout ${t} ros2 service call '${svc}' std_srvs/srv/Trigger" 2>&1 | grep -q 'success=True'
}



# --- ExternalControl-Nachzuendung (Fall: RTDE liest, aber Motion-Link fehlt) ---
# Der JSC streamt schon, sobald die Control-Box an ist - RTDE-Lesen funktioniert
# unabhaengig von ExternalControl. Wird der Arm ERST NACH der HW-Aktivierung
# bestromt (typisch: App ruft prepare), ging das einmalig gesendete
# ExternalControl-Programm ins Leere und ros2_control wiederholt es nicht:
# Lesen ok, Schreiben tot, Arm bewegt sich nicht. Der JSC-Health-Check sieht das
# NICHT - erst die Konjunktion "JSC streamt UND robot_program_running" ist
# belastbar. Reaktion hier bewusst MINIMAL: nur resend_robot_program, kein
# Treiber-Neustart, kein Bestromen. Gate: nur wenn der Bediener den Arm schon
# auf RUNNING gebracht hat und keine Safety-Stoerung ansteht.
ensure_external_control() {
    ros_cmd "timeout ${RPR_TIMEOUT} ros2 topic echo --once --qos-durability transient_local '${RPR_TOPIC}'" 2>/dev/null \
        | grep -q 'data: true' && return 0
    if [ "$DRY_RUN" = "1" ]; then
        log "DRY_RUN=1 -> ExternalControl steht nicht; haette resend_robot_program geschickt."
        return 0
    fi
    local rm_now; rm_now="$(robot_mode)"
    if [ "$rm_now" != "Robotmode: RUNNING" ]; then
        return 0   # Arm nicht betriebsbereit -> nichts tun (Bediener-Entscheidung)
    fi
    local sm_now; sm_now="$(safety_mode)"
    if [ "$sm_now" != "Safetymode: NORMAL" ]; then
        log "ExternalControl steht nicht, aber Safety-Modus ist '${sm_now:-unbekannt}' -> kein resend (manuelle Freigabe noetig)."
        return 0
    fi
    local now_r; now_r="$(date +%s)"
    if [ -f "$RESEND_STATE" ]; then
        local last_r; last_r="$(cat "$RESEND_STATE" 2>/dev/null || echo 0)"
        [ -n "$last_r" ] || last_r=0
        if [ "$(( now_r - last_r ))" -lt "$RESEND_COOLDOWN" ]; then
            return 0
        fi
    fi
    echo "$now_r" > "$RESEND_STATE"
    log "Arm ist RUNNING und der JSC streamt, aber ExternalControl laeuft nicht (robot_program_running != true) -> resend_robot_program. KEIN Treiber-Neustart, kein Bestromen."
    if call_trigger "${RESEND_SVC}" 20; then
        sleep 3
        if ros_cmd "timeout ${RPR_TIMEOUT} ros2 topic echo --once --qos-durability transient_local '${RPR_TOPIC}'" 2>/dev/null | grep -q 'data: true'; then
            log "ExternalControl wieder aktiv."
        else
            log "resend gesendet, robot_program_running noch nicht true - naechster Lauf prueft erneut (Cooldown ${RESEND_COOLDOWN}s)."
        fi
    else
        log "resend_robot_program fehlgeschlagen - naechster Lauf prueft erneut (Cooldown ${RESEND_COOLDOWN}s)."
    fi
}

# 1) Arm ueberhaupt erreichbar? Nein -> bewusst nichts tun (Arm noch aus; der
#    Watchdog soll NUR beim spaeten Einschalten / nach Treiber-Ausfall anspringen,
#    nicht dauernd).
if ! ping -c1 -W1 "$ROBOT_IP" >/dev/null 2>&1; then
    exit 0
fi

# 2) Health-Check: lebt der PC-seitige Motion-Link? Signal = JSC-Stream auf
#    .../manipulators/joint_states (reale Arm-Gelenke, nur verfuegbar wenn das
#    ros2_control-HW-Interface aktiviert ist). robot_program_running (true/false)
#    ist KEIN ausreichendes Signal (controller-seitig, bleibt true bei totem
#    PC-Motion-Link). Grace-Timeout grosszuegig: der JSC braucht nach einem
#    manipulators-Restart bis ~15s -> erst >JS_TIMEOUT ohne Nachricht = wirklich tot.
if ros_cmd "timeout ${JS_TIMEOUT} ros2 topic echo --once '${JS_TOPIC}'" >/dev/null 2>&1; then
    ensure_external_control    # JSC-Lesepfad ok - aber steht auch der Schreibpfad?
    exit 0
fi
# Fallback: Arm-Joints koennen auch auf dem platform-Bus ankommen - naemlich dann,
# wenn der Stock-Patch move_arm_joint_states (clearpath-custom-setup.py Schritt 3)
# nach einem apt-Update nicht mehr greift. Ohne diesen Zweig laese der Watchdog
# Stille auf einem KERNGESUNDEN Roboter und startete den Treiber im Cooldown-Takt
# dauerhaft neu. Health-Signal ist "Arm-Gelenke kommen an" - egal auf welchem Bus.
if ros_cmd "timeout ${JS_TIMEOUT} ros2 topic echo --once '${PLATFORM_JS_TOPIC}'" 2>/dev/null \
     | grep -q 'arm_0_shoulder_pan_joint'; then
    log "WARN: Arm-Joints kommen auf ${PLATFORM_JS_TOPIC} statt ${JS_TOPIC} an -> der Stock-Patch move_arm_joint_states greift NICHT (apt-Update?). Motion-Link ist GESUND, keine Recovery. Pruefen: journalctl -t clearpath-custom-setup -b"
    exit 0
fi

# 3) Cooldown pruefen (/run wird beim Boot geleert -> pro Boot frisch).
now="$(date +%s)"
if [ -f "$STATE" ]; then
    last="$(cat "$STATE" 2>/dev/null || echo 0)"
    [ -n "$last" ] || last=0
    if [ "$(( now - last ))" -lt "$COOLDOWN" ]; then
        log "Motion-Link tot (JSC stumm), aber letzte Recovery < ${COOLDOWN}s her -> warte."
        exit 0
    fi
fi

log "Arm erreichbar (${ROBOT_IP}), aber JSC ${JS_TOPIC} stumm (Motion-Link tot) -> Recovery: ${SERVICE} neu starten + ExternalControl neu starten. KEIN Auto-Bestromen des Arms (Bediener-Entscheidung)."
echo "$now" > "$STATE"

# 3a) clearpath-custom-ur-dashboard.service sicherstellen (Mode-Abfrage + resend
#     brauchen den Dashboard-Client; unabhaengig von manipulators, bleibt oben).
if [ "$(systemctl is-active "$DASH_SVC" 2>/dev/null)" != "active" ]; then
    log "${DASH_SVC} nicht aktiv -> starte es."
    systemctl start "$DASH_SVC" || true
    sleep 3
fi

# 3b) Arm bewusst aus? KEIN Auto-Recovery und KEIN Auto-Bestromen - der Watchdog
#     powert den Arm NIE selbst (Bediener-Entscheidung; schuetzt Wartung/Feierabend).
#     Verhindert zusaetzlich ein Endlos-Restarten des Treibers gegen einen stromlosen
#     Arm (HW-Aktivierung schlaegt ohnehin fehl -> JSC bliebe stumm -> Loop).
rm_mode="$(robot_mode)"
if [ "$rm_mode" = "Robotmode: POWER_OFF" ]; then
    log "Arm ist POWER_OFF (bewusst stromlos) -> kein Auto-Recovery, kein Bestromen. Bei Bedarf manuell bestromen; der Watchdog verbindet den Motion-Link, sobald der Arm an ist."
    exit 0
fi

# 3c) Treiber neu starten (blockierend). Mit dem SIGINT-Stop-Drop-in auf
#     clearpath-manipulators.service (siehe unten, WD_MANIP_DROPIN) stirbt der alte
#     ros2_control_node sauber (Reverse-Socket geordnet geschlossen) statt SIGTERM bis
#     zu 90s zu ignorieren -> der neue Controller-Manager startet gegen ein freies Socket.
#     TimeoutStartSec des watchdog-Service (300s) deckt langsames Stoppen + Recovery ab.
if [ "$DRY_RUN" = "1" ]; then
    log "DRY_RUN=1 -> haette jetzt ${SERVICE} neu gestartet + ExternalControl resendet. Kein Eingriff."
    exit 0
fi
systemctl restart "$SERVICE" || log "systemctl restart ${SERVICE} lief nicht sauber - versuche Recovery trotzdem weiter."

# 3d) Safety-Check: Protective-/Safety-Stop wird NICHT auto-gecleart (manuell).
#     Waehrend eines Safety-Stops kein resend (Bediener muss erst freigeben).
sm="$(safety_mode)"
if [ "$sm" != "Safetymode: NORMAL" ]; then
    log "Safety-Modus ist '${sm:-unbekannt}' (kein NORMAL) -> Protective-/Safety-Stop. NICHT auto-gecleart, resend uebersprungen. Manuelle Begutachtung noetig."
    exit 0
fi

# 3e) ExternalControl direkt neu starten (resend_robot_program) - mit Retries, weil
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

# 3f) Erfolg verifizieren: JSC streamt wieder (reale Arm-Gelenke). Zuverlaessiger als
#     rpr, weil es direkt den PC-Motion-Link bestaetigt (nicht nur das controller-seitige
#     Programm). Kurz - resend hat ExternalControl gestartet, JSC wird schnell aktiv.
ok=""
for i in $(seq 1 "${RPR_WAIT}"); do
    if ros_cmd "timeout 6 ros2 topic echo --once '${JS_TOPIC}'" >/dev/null 2>&1; then
        ok=1; break
    fi
    sleep 1
done
if [ -n "$ok" ]; then
    log "Recovery erfolgreich: ${JS_TOPIC} streamt wieder."
else
    log "resend gesendet, aber ${JS_TOPIC} noch stumm. Naechster Timer-Lauf prueft erneut (Cooldown ${COOLDOWN}s)."
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
# Recovery blockiert beim systemctl restart + Dashboard-Aufrufe + Polls. Mit dem
# SIGINT-Stop-Drop-in (WD_MANIP_DROPIN) stoppt der Treiber in ~1-3s; ohne Drop-in
# kann SIGTERM bis zu 90s bis SIGKILL brauchen. systemd-Default-Timeout (90s) wuerde
# den oneshot mittendrin killen -> grosszuegig (Puffer fuer Slow-Stop + Recovery).
TimeoutStartSec=300
# Script-echo-Zeilen unter journalctl -t manipulators-watchdog sammelbar.
SyslogIdentifier=manipulators-watchdog
EOF
    chmod 0644 "$WD_UNIT_PATH"

    cat > "$WD_TIMER_PATH" <<EOF
[Unit]
Description=Periodischer manipulators-watchdog-Check (Treiber-Reconnect bei spaetem Arm-Einschalten ODER haengengebliebenem Reconnect nach Service-Restart)

[Timer]
# Erst nach der normalen Boot-Hochlaufzeit beginnen (Treiber Zeit geben), dann
# regelmaessig. Kadenz 10s (statt 30s): so schlaegt der Watchdog auch nach einem
# clearpath-robot.service-Restart mit schon bestromtem Arm binnen ~10s an, sobald
# der JSC-Stream (Health-Signal) aussetzt. Grace-Timeout im Skript (JS_TIMEOUT=25s)
# verhindert Fehl-Alarme waehrend des ~15s manipulators-Hochlaufs.
OnBootSec=90
OnUnitActiveSec=10
AccuracySec=2

[Install]
WantedBy=timers.target
EOF
    chmod 0644 "$WD_TIMER_PATH"

    # --- SIGINT-Stop-Drop-in fuer clearpath-manipulators.service -------------
    # Ros-Knoten (ros2_control_node, move_group, robot_state_pub) reagieren auf SIGINT
    # mit sauberem ROS-Graceful-Shutdown (Reverse-/Dashboard-Socket geordnet
    # geschlossen) statt SIGTERM bis zu 90s zu ignorieren. Verhindert die Socket-
    # Kollision beim Reconnect nach einem Service-Restart mit schon bestromtem Arm
    # (alte ExternalControl-Instanz haelt das Reverse-Socket -> neue HW-Aktivierung
    # schlaegt fehl -> Arm in RViz flach). Drop-in layert ueber der Clearpath-Unit
    # (/usr/lib/systemd/system/...) und ueberlebt Package-Updates.
    install -d -m 0755 "$WD_MANIP_DROPIN_DIR"
    cat > "$WD_MANIP_DROPIN" <<'DROPEOF'
[Unit]
Description=Harte Stop-Parameter fuer clearpath-manipulators (sauberes Treiber-Shutdown)

[Service]
KillSignal=SIGINT
TimeoutStopSec=95
KillMode=control-group
SendSIGKILL=yes
# A7: ros2_control_node setzt seinen Control-Thread per configure_sched_fifo()
# auf SCHED_FIFO (Default-Prio 50). Systemd-Units lesen KEINE
# /etc/security/limits.conf (pam_limits gilt nur fuer Login-Sessions) -> ohne
# LimitRTPRIO scheitert das mit EPERM und der Loop laeuft SCHED_OTHER.
# Gemessen 2026-07-29: Overruns bei 125 Hz (bis 18.5 ms Zyklus).
LimitRTPRIO=99
DROPEOF
    chmod 0644 "$WD_MANIP_DROPIN"
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
# (clearpath-manipulators + rg6-bringup). After= rg6-bringup -> Start NACH neuem
# rg6-Publisher. PartOf=clearpath-manipulators: der rg6-Joint-Relay/Aggregator
# (custom rg6_control-Nodes joint_state_relay/joint_state_aggregator) resubscribed
# unter rmw_zenoh NICHT zuverlaessig, wenn die rg6-JSC nach einem manipulators-/
# rg6-bringup-Restart neu publisht -> ohne Mit-Restart fallen die rg6-Joints aus dem
# TF-Feed und der Greifer-TF wird flach. Daher restartet joint-states mit der
# clearpath-manipulators-Kaskade und baut die Subscriptions sauber wieder auf
# (After=rg6-bringup sichert die Reihenfolge). Arm-Relay unbeeinflusst (Arm-JSC geht
# direkt in manipulators/joint_states, nicht ueber joint-states).
After=clearpath-platform.service clearpath-manipulators.service clearpath-custom-rg6-bringup.service
Wants=clearpath-platform.service
# Mit-Neustart an BEIDE Wurzeln (robot + manipulators): PartOf propagiert
# Stop/Restart nur eine Hop-Ebene und nur bei DIREKTEM Job. Stack-Restart via
# 'systemctl restart clearpath-robot' startet clearpath-manipulators nur indirekt
# -> ohne PartOf=clearpath-robot wuerden die rg6-Joint-Relays/Aggregatoren nicht
# mit-restarten -> Greifer-TF wird flach. Stop clearpath-robot stoppt ihn mit.
PartOf=clearpath-robot.service clearpath-manipulators.service

[Service]
User=${REAL_USER}
ExecStart=${JS_WRAPPER}
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
chmod 0644 "$JS_UNIT_PATH"

# --- robot.yaml: versionierte Datei per Symlink (offizieller Clearpath-Weg) ---
# Clearpath sieht vor, die robot.yaml versioniert zu halten und per SYMLINK nach
# /etc/clearpath/robot.yaml zu legen (Customization-Package-Konzept). Das ersetzt
# den frueheren Boot-Download (clearpath-custom-robot-yaml-update.service, 2026-07-29
# entfernt): keine Netzabhaengigkeit im Bootpfad, reproduzierbare Konfiguration, und
# ein 'git pull' wirkt SOFORT statt erst beim naechsten Boot -- clearpath-robot-check
# md5summt /etc/clearpath/robot.yaml im Sekundentakt und startet den Stack bei
# Aenderung neu (md5sum folgt dem Symlink).
echo ">>> robot.yaml: Repo-Klon + Symlink (${SETUP_WS} -> ${ROBOT_YAML_PATH})"
if [ -d "${SETUP_WS}/.git" ]; then
    sudo -u "$REAL_USER" git -C "$SETUP_WS" pull --ff-only || echo "    WARN: git pull fehlgeschlagen, nutze vorhandenen Stand"
else
    sudo -u "$REAL_USER" git clone "$SETUP_REPO_URL" "$SETUP_WS" || echo "    WARN: git clone fehlgeschlagen"
fi
if [ -f "${SETUP_WS}/robot.yaml" ]; then
    if [ -L "$ROBOT_YAML_PATH" ] && [ "$(readlink -f "$ROBOT_YAML_PATH")" = "$(readlink -f "${SETUP_WS}/robot.yaml")" ]; then
        echo "    Symlink bereits korrekt - keine Aenderung."
    else
        # Vorhandene ECHTE Datei sichern, bevor sie durch den Symlink ersetzt wird.
        if [ -f "$ROBOT_YAML_PATH" ] && [ ! -L "$ROBOT_YAML_PATH" ]; then
            if ! cmp -s "$ROBOT_YAML_PATH" "${SETUP_WS}/robot.yaml"; then
                echo "    ACHTUNG: vorhandene ${ROBOT_YAML_PATH} weicht vom Repo-Stand ab!"
                confirm "    Trotzdem durch den Symlink ersetzen (Backup wird angelegt)?" || {
                    echo "    robot.yaml: uebersprungen (Symlink NICHT gesetzt)."; SKIP_SYMLINK=1; }
            fi
            [ "${SKIP_SYMLINK:-0}" = "1" ] || cp -a "$ROBOT_YAML_PATH" "${ROBOT_YAML_PATH}.pre-symlink.$(date +%Y%m%d%H%M%S)"
        fi
        if [ "${SKIP_SYMLINK:-0}" != "1" ]; then
            install -d -m 0755 "$(dirname "$ROBOT_YAML_PATH")"
            ln -sfn "${SETUP_WS}/robot.yaml" "$ROBOT_YAML_PATH"
            echo "    Symlink gesetzt: ${ROBOT_YAML_PATH} -> ${SETUP_WS}/robot.yaml"
        fi
    fi
else
    echo "    WARN: ${SETUP_WS}/robot.yaml fehlt - Symlink NICHT gesetzt, vorhandene Datei bleibt."
fi
# Alten Boot-Download-Service abloesen (falls von einer frueheren Installation da).
if systemctl list-unit-files 2>/dev/null | grep -q "^clearpath-custom-robot-yaml-update"; then
    echo ">>> Entferne abgeloesten clearpath-custom-robot-yaml-update.service"
    systemctl disable --now clearpath-custom-robot-yaml-update.service 2>/dev/null || true
    rm -f /etc/systemd/system/clearpath-custom-robot-yaml-update.service "${BIN_DIR}/robot-yaml-update.sh"
fi

# --- Octomap-Feed (optional): dichte Hindernis-Schicht fuer move_group -----
# Schritt 2 der HRL-Hindernis-Architektur: move_group pflegt aus der Wrist-
# D435 einen Octomap (Occupancy Map Monitor) und weicht damit auch Hindernissen
# aus, die der offboard Objekt-Tracker nicht (oder noch nicht) kennt --
# Raycasts raeumen freigewordenen Raum automatisch.  Dieser Service liefert
# die gedrosselte PointCloud2 (octomap_feed.py, Default 5 Hz / stride 2);
# die move_group-Sensorparameter setzt der Boot-Patcher (Schritt 5) NUR,
# wenn die Unit-Datei existiert.  Deinstallation: 'systemctl disable --now
# clearpath-custom-octomap-feed', Unit-Datei loeschen, reboot (der Patcher
# laesst moveit.yaml dann wieder unangetastet; .bak liegt daneben).
DO_OCTO=1
if [ -f "$OCTO_UNIT_PATH" ]; then
    confirm ">>> ${OCTO_UNIT} ist bereits installiert. Aktualisieren?" || DO_OCTO=0
else
    confirm ">>> Octomap-Feed installieren (move_group weicht dann auch ungetrackten Hindernissen aus; ~5 Hz Onboard-Last)?" || DO_OCTO=0
fi
if [ "$DO_OCTO" -eq 1 ]; then
    echo ">>> Installiere ${OCTO_FEED_BIN}"
    OCTO_TMP="$(mktemp)"
    OCTO_SRC=""
    if curl -fsSL --connect-timeout 5 --max-time 30 "$OCTO_FEED_URL" -o "$OCTO_TMP"; then
        if python3 -c "import sys; compile(open(sys.argv[1]).read(), sys.argv[1], 'exec')" "$OCTO_TMP"; then
            OCTO_SRC="$OCTO_TMP"
        else
            echo "    WARN: Download ist kein gueltiges Python - verwerfe."
        fi
    fi
    if [ -z "$OCTO_SRC" ] && [ -f "$(dirname "$0")/scripts/octomap_feed.py" ]; then
        echo "    Download nicht verfuegbar - nutze lokale Repo-Kopie."
        OCTO_SRC="$(dirname "$0")/scripts/octomap_feed.py"
    fi
    if [ -n "$OCTO_SRC" ]; then
        install -m 0755 -o root -g root "$OCTO_SRC" "$OCTO_FEED_BIN"
        # Selbsttest der Konvertierung (numpy-only, kein ROS noetig).
        python3 "$OCTO_FEED_BIN" --selftest || echo "    WARN: Selbsttest fehlgeschlagen - Service wird trotzdem installiert (Logs pruefen)."

        echo ">>> Installiere ${OCTO_WRAPPER} + ${OCTO_UNIT}"
        cat > "$OCTO_WRAPPER" <<EOF
#!/usr/bin/env bash
# Gedrosselte Depth->PointCloud2-Quelle fuer MoveIts Octomap (octomap_feed).
source /etc/clearpath/setup.bash
exec python3 ${OCTO_FEED_BIN}
EOF
        chmod 0755 "$OCTO_WRAPPER"

        cat > "$OCTO_UNIT_PATH" <<EOF
[Unit]
Description=Octomap feed: Depth -> PointCloud2 fuer MoveIts Occupancy Map Monitor
After=clearpath-sensors.service
Wants=clearpath-sensors.service
# Stack-Restart-Verhalten wie rg6-bringup: an beide Wurzeln haengen
# (praktischer Stack-Restart laeuft ueber clearpath-robot).
PartOf=clearpath-robot.service clearpath-sensors.service

[Service]
User=${REAL_USER}
ExecStart=${OCTO_WRAPPER}
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
        chmod 0644 "$OCTO_UNIT_PATH"
        # Reine PRUEFUNG (kein apt!): der PointCloudOctomapUpdater kommt aus
        # moveit_ros_perception. Fehlt das Paket, laeuft der Feed zwar, aber
        # der Boot-Patcher traegt die move_group-Sensorparameter bewusst
        # nicht ein (Gate) - Installation ist eine Admin-Entscheidung.
        if ! ls -d /opt/ros/*/share/moveit_ros_perception >/dev/null 2>&1; then
            echo "    WARN: ros-<distro>-moveit-ros-perception ist NICHT installiert."
            echo "          Der Octomap bleibt inaktiv (Patcher-Gate), bis das Paket da ist."
            echo "          Installation NUR bewusst im Wartungsfenster (apt-Historie dieses"
            echo "          Roboters beachten; vorher 'apt-get install -s' pruefen)."
        fi
    else
        echo "    WARN: octomap_feed.py weder ladbar noch lokal vorhanden - Octomap uebersprungen."
    fi
    rm -f "$OCTO_TMP"
else
    echo ">>> Octomap-Feed: uebersprungen."
fi

# --- Manipulator-Diagnose (optional) ---------------------------------------
# UR-Mode/Safety/ExternalControl + RG6-Zustand -> diagnostic_msgs auf dem
# /diagnostics-Topic des Clearpath-Aggregators. Der Aggregator-Analyzer dazu
# kommt vom Boot-Patcher (Schritt 6) und ist auf DIESE Unit-Datei gegated:
# Unit loeschen + reboot = Manipulator wieder aus der Diagnose raus.
# Deinstallation: 'systemctl disable --now clearpath-custom-manipulator-diagnostics',
# Unit-Datei loeschen, reboot (.bak der aggregator-yaml liegt daneben).
DO_MD=1
if [ -f "$MD_UNIT_PATH" ]; then
    confirm ">>> ${MD_UNIT} ist bereits installiert. Aktualisieren?" || DO_MD=0
else
    confirm ">>> Manipulator-Diagnose installieren (UR5 + RG6 erscheinen dann in Cockpit/diagnostics_agg)?" || DO_MD=0
fi
if [ "$DO_MD" -eq 1 ]; then
    echo ">>> Installiere ${MD_BIN}"
    MD_TMP="$(mktemp)"
    MD_SRC=""
    if curl -fsSL --connect-timeout 5 --max-time 30 "$MD_FEED_URL" -o "$MD_TMP"; then
        if python3 -c "import sys; compile(open(sys.argv[1]).read(), sys.argv[1], 'exec')" "$MD_TMP"; then
            MD_SRC="$MD_TMP"
        else
            echo "    WARN: Download ist kein gueltiges Python - verwerfe."
        fi
    fi
    if [ -z "$MD_SRC" ] && [ -f "$(dirname "$0")/scripts/manipulator_diagnostics.py" ]; then
        echo "    Download nicht verfuegbar - nutze lokale Repo-Kopie."
        MD_SRC="$(dirname "$0")/scripts/manipulator_diagnostics.py"
    fi
    if [ -n "$MD_SRC" ]; then
        install -m 0755 -o root -g root "$MD_SRC" "$MD_BIN"
        # Selbsttest der Bewertungslogik (reines Python, kein ROS noetig).
        python3 "$MD_BIN" --selftest || echo "    WARN: Selbsttest fehlgeschlagen - Service wird trotzdem installiert (Logs pruefen)."

        echo ">>> Installiere ${MD_WRAPPER} + ${MD_UNIT}"
        # rg6_msgs kommt aus dem onrobot-rg6-Workspace; /etc/clearpath/setup.bash
        # zieht ihn ueber system.ros2.workspaces schon mit, das explizite source
        # ist die Absicherung fuer den Fall, dass der Eintrag mal fehlt.
        cat > "$MD_WRAPPER" <<EOF
#!/usr/bin/env bash
# UR5 + OnRobot RG6 als diagnostic_msgs fuer den Clearpath-diagnostic_aggregator.
source /etc/clearpath/setup.bash
[ -f ${RG6_WS}/install/setup.bash ] && source ${RG6_WS}/install/setup.bash
exec python3 ${MD_BIN} --ros-args \\
    -p manipulator_ns:=${MANIP_NS} \\
    -p robot_ip:=${ARM_ROBOT_IP}
EOF
        chmod 0755 "$MD_WRAPPER"

        cat > "$MD_UNIT_PATH" <<EOF
[Unit]
Description=Manipulator-Diagnose: UR5 + RG6 -> diagnostic_msgs (Cockpit/diagnostics_agg)
After=clearpath-manipulators.service ${RG6_UNIT}
Wants=clearpath-manipulators.service
# Wie rg6-bringup an BEIDE Wurzeln haengen: der praktische Stack-Restart laeuft
# ueber clearpath-robot, der direkte Treiber-Restart ueber clearpath-manipulators.
PartOf=clearpath-robot.service clearpath-manipulators.service

[Service]
User=${REAL_USER}
ExecStart=${MD_WRAPPER}
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
        chmod 0644 "$MD_UNIT_PATH"
    else
        echo "    WARN: manipulator_diagnostics.py weder ladbar noch lokal vorhanden - Manipulator-Diagnose uebersprungen."
    fi
    rm -f "$MD_TMP"
else
    echo ">>> Manipulator-Diagnose: uebersprungen."
fi

# --- RTDE-Input-Recipe ohne Tool-DO ----------------------------------------
# Voraussetzung dafuer, dass der ur_robot_driver neben der OnRobot-URCap
# ueberhaupt startet: die URCap ist selbst RTDE-Client und belegt
# tool_digital_output_mask, der Treiber stirbt sonst beim RTDE-Setup an
# "controlled by another RTDE client". robot.yaml zeigt FEST auf
# /home/robot/rtde_input_recipe_no_tool.txt -- fehlt die Datei nach einem
# Neuaufsetzen, startet der Treiber nicht, und zwar ohne Hinweis auf sie.
RTDE_RECIPE_SRC="$(dirname "$0")/rtde_input_recipe_no_tool.txt"
RTDE_RECIPE_DST="${USER_HOME}/rtde_input_recipe_no_tool.txt"
if [ -f "$RTDE_RECIPE_SRC" ]; then
    install -m 0644 -o "$REAL_USER" -g "$REAL_USER" \
        "$RTDE_RECIPE_SRC" "$RTDE_RECIPE_DST"
    echo ">>> RTDE-Recipe -> ${RTDE_RECIPE_DST}"
else
    echo "    WARN: ${RTDE_RECIPE_SRC} fehlt - der UR-Treiber startet ohne sie NICHT."
fi

# --- RG6-Greifer-Bruecke (XML-RPC an die OnRobot-URCap) --------------------
# Ersetzt den rg6_control-Tool-DO-Pfad, den das Recipe oben totlegt: ROS kann
# kein Tool-DO mehr setzen, also kommandiert dieser Node den Greifer direkt
# per XML-RPC (rg_grip auf 192.168.131.40:41414). Er laeuft ONBOARD, weil der
# Endpoint am Arm-Subnetz haengt -- von der Workstation gibt es dorthin keine
# Route -- und weil der Roboter auch ohne Funkstrecke greifen koennen muss.
RG6_BRIDGE_BIN="${BIN_DIR}/rg6-grip-bridge"
RG6_BRIDGE_WRAPPER="${BIN_DIR}/rg6-grip-bridge-wrapper"
RG6_BRIDGE_UNIT="clearpath-custom-rg6-grip-bridge.service"
RG6_BRIDGE_UNIT_PATH="/etc/systemd/system/${RG6_BRIDGE_UNIT}"
RC_DST="/usr/local/lib/spact"
RC_REPO="https://github.com/CLAIRLab-HAW/robot-contract.git"

DO_RG6_BRIDGE=1
if [ -f "$RG6_BRIDGE_UNIT_PATH" ]; then
    confirm ">>> ${RG6_BRIDGE_UNIT} ist bereits installiert. Aktualisieren?" || DO_RG6_BRIDGE=0
else
    confirm ">>> RG6-Greifer-Bruecke installieren (kommandiert den Greifer per XML-RPC an die OnRobot-URCap; ersetzt den toten rg6_control-Tool-DO-Pfad)?" || DO_RG6_BRIDGE=0
fi

if [ "$DO_RG6_BRIDGE" -eq 1 ]; then
    # Lokale Repo-Kopie ZUERST -- kein Download-first wie bei octomap_feed.
    # Wer den Installer aus dem Checkout laufen laesst, will den Stand des
    # Checkouts; die umgekehrte Reihenfolge ist genau das Muster, aus dem der
    # octomap_feed.py-Drift in drei Fassungen entstanden ist.
    RG6_SRC="$(dirname "$0")/scripts/rg6_grip_bridge.py"
    if [ ! -f "$RG6_SRC" ]; then
        echo "    WARN: ${RG6_SRC} fehlt - RG6-Bruecke uebersprungen."
        DO_RG6_BRIDGE=0
    elif ! python3 -c "import sys; compile(open(sys.argv[1]).read(), sys.argv[1], 'exec')" "$RG6_SRC"; then
        echo "    WARN: ${RG6_SRC} ist kein gueltiges Python - verwerfe."
        DO_RG6_BRIDGE=0
    fi
fi

if [ "$DO_RG6_BRIDGE" -eq 1 ]; then
    # robot_contract ist der DRAHT-Vertrag (parse_gripper_command /
    # gripper_result). Er wird mitgeliefert statt im Node nachgebaut: eine
    # zweite Fassung ist dieselbe Driftquelle wie oben -- und sie traefe hier
    # das Protokoll, nicht einen Parameter. Reines Python (pyyaml + numpy,
    # beides auf dem Roboter vorhanden).
    #
    # DREI Suchpfade, dann erst das Netz -- dasselbe Muster wie die
    # wakeup.sh-Wrapper. Auf der Workstation liegt das Repo im Workspace
    # daneben; auf dem Roboter liegt husky-custom-setup ALLEIN in ~, dort
    # gibt es "../../contract/..." nicht.
    RC_SRC=""
    for cand in \
        "${ROBOT_CONTRACT_SRC:-}" \
        "$(dirname "$0")/../../contract/robot-contract/src/robot_contract" \
        "${USER_HOME}/robot-contract/src/robot_contract" \
        "${USER_HOME}/clearpath/contract/robot-contract/src/robot_contract"
    do
        [ -n "$cand" ] && [ -d "$cand" ] && { RC_SRC="$cand"; break; }
    done
    RC_TMP=""
    if [ -z "$RC_SRC" ]; then
        echo "    robot_contract nicht lokal gefunden - hole ${RC_REPO}"
        RC_TMP="$(mktemp -d)"
        if git clone --depth 1 "$RC_REPO" "${RC_TMP}/robot-contract" >/dev/null 2>&1; then
            RC_SRC="${RC_TMP}/robot-contract/src/robot_contract"
        fi
    fi
    if [ -n "$RC_SRC" ] && [ -d "$RC_SRC" ]; then
        install -d -m 0755 "$RC_DST"
        rm -rf "${RC_DST}/robot_contract"
        cp -a "$RC_SRC" "${RC_DST}/robot_contract"
        find "${RC_DST}/robot_contract" -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true
        echo "    robot_contract -> ${RC_DST}/robot_contract  (aus ${RC_SRC})"
    else
        echo "    WARN: robot_contract nicht auffindbar - der Node startet ohne es NICHT."
        echo "          Abhilfe: ROBOT_CONTRACT_SRC=<pfad/zu/src/robot_contract> setzen."
        DO_RG6_BRIDGE=0
    fi
    [ -n "$RC_TMP" ] && rm -rf "$RC_TMP"
fi

if [ "$DO_RG6_BRIDGE" -eq 1 ]; then
    echo ">>> Installiere ${RG6_BRIDGE_BIN}"
    install -m 0755 -o root -g root "$RG6_SRC" "$RG6_BRIDGE_BIN"
    # Selbsttest ohne ROS -- Einheiten, float-Zwang, Klemmung, Timeout,
    # Draht-Vertrag, Getriebe, Nebenlaeufigkeit.
    PYTHONPATH="${RC_DST}:${PYTHONPATH:-}" python3 "$RG6_BRIDGE_BIN" --selftest \
        || echo "    WARN: Selbsttest fehlgeschlagen - Service wird trotzdem installiert (Logs pruefen)."

    cat > "$RG6_BRIDGE_WRAPPER" <<EOF
#!/usr/bin/env bash
# RG6-Greifer per XML-RPC an die OnRobot-URCap (rg6_grip_bridge).
source /etc/clearpath/setup.bash
export PYTHONPATH="${RC_DST}:\${PYTHONPATH:-}"
exec python3 ${RG6_BRIDGE_BIN}
EOF
    chmod 0755 "$RG6_BRIDGE_WRAPPER"

    cat > "$RG6_BRIDGE_UNIT_PATH" <<EOF
[Unit]
Description=RG6 gripper bridge (XML-RPC an die OnRobot-URCap)
After=clearpath-manipulators.service
Wants=clearpath-manipulators.service
PartOf=clearpath-robot.service clearpath-manipulators.service
# OHNE diese beiden dreht eine kaputte Unit ENDLOS: die systemd-Voreinstellung
# ist Burst=5 in 10 s, bei RestartSec=5 passen da nur zwei Versuche hinein --
# die Grenze wird nie erreicht. Am 2026-08-17 an der rg6-bringup-Unit
# nachgerechnet. 120 s, weil fuenf Versuche a 5 s rund 25 s dauern; die Unit
# bleibt danach sichtbar als 'failed' stehen, statt sich selbst zu verdecken.
StartLimitIntervalSec=120
StartLimitBurst=5

[Service]
Type=simple
User=${REAL_USER}
ExecStart=${RG6_BRIDGE_WRAPPER}
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
    chmod 0644 "$RG6_BRIDGE_UNIT_PATH"
    systemctl daemon-reload
    systemctl enable "$RG6_BRIDGE_UNIT" >/dev/null 2>&1 \
        || echo "    WARN: systemctl enable ${RG6_BRIDGE_UNIT} fehlgeschlagen."
    echo ">>> ${RG6_BRIDGE_UNIT} installiert und aktiviert."
else
    echo ">>> RG6-Greifer-Bruecke: uebersprungen."
fi

# --- Cockpit-Plugin mit Manipulator-Panel (optional) ------------------------
# Fork von clearpathrobotics/cockpit-ros2-diagnostics: zusaetzlich zum
# generischen Diagnose-Baum eine eigene Manipulator-Ansicht (Arm-Mode/Safety/
# ExternalControl/Motion-Link + Gelenktabelle, Greifer-Weite/grip_detected/
# Tool-Power). Die Daten kommen aus demselben diagnostics_agg-Strom -- ohne
# den manipulator-diagnostics-Service oben bleibt das Panel unsichtbar.
#
# Installation nach /usr/local/share/cockpit/ros2-diagnostics: Cockpit
# bevorzugt /usr/local vor /usr/share, der Fork ueberdeckt also das apt-Paket,
# ohne es zu ersetzen. Rueckbau = Verzeichnis loeschen (kein apt).
# HINWEIS: apt-Updates von cockpit-ros2-diagnostics wirken sich dann nicht
# mehr sichtbar aus, solange der Fork liegt - Fork bei Bedarf nachziehen.
DO_CKPT=1
if [ -d "$CKPT_PKG_DIR" ]; then
    confirm ">>> Cockpit-Plugin (Fork mit Manipulator-Panel) ist installiert. Aktualisieren?" || DO_CKPT=0
else
    confirm ">>> Cockpit-Plugin mit Manipulator-Panel installieren (ueberdeckt das apt-Plugin unter /usr/share)?" || DO_CKPT=0
fi
if [ "$DO_CKPT" -eq 1 ]; then
    if ! dpkg -s cockpit-bridge >/dev/null 2>&1; then
        echo "    WARN: cockpit-bridge ist nicht installiert - das Plugin wird erst nach der Cockpit-Installation sichtbar."
    fi
    echo ">>> cockpit-ros2-diagnostics (Fork) nach ${CKPT_WS} (Nutzer ${REAL_USER})"
    CKPT_OK=1
    if [ -d "${CKPT_WS}/.git" ]; then
        sudo -u "$REAL_USER" git -C "$CKPT_WS" pull --ff-only || echo "    WARN: git pull fehlgeschlagen, nutze vorhandenen Stand"
    else
        sudo -u "$REAL_USER" git clone "$CKPT_REPO_URL" "$CKPT_WS" || CKPT_OK=0
    fi
    if [ "$CKPT_OK" -eq 1 ]; then
        # Bevorzugt ein vorgebautes dist/ aus dem Checkout. Der Build braucht
        # nodejs+npm (~500 Pakete) und einen git-fetch der Cockpit-Bibliothek --
        # das gehoert bewusst NICHT auf den Roboter, wenn es vermeidbar ist
        # (apt-Historie dieses Roboters). Der Installer installiert daher kein
        # nodejs; er baut nur, wenn die Toolchain schon da ist.
        if [ ! -f "${CKPT_WS}/dist/manifest.json" ]; then
            if command -v npm >/dev/null 2>&1 && command -v make >/dev/null 2>&1; then
                echo ">>> Kein vorgebautes dist/ - baue auf dem Roboter (npm + make)"
                sudo -u "$REAL_USER" env HOME="$USER_HOME" bash -lc \
                    "cd '$CKPT_WS' && make" || CKPT_OK=0
            else
                echo "    WARN: weder dist/ noch npm/make vorhanden."
                echo "          Auf einem Rechner MIT Toolchain bauen und das Ergebnis herbringen:"
                echo "            git clone ${CKPT_REPO_URL} && cd cockpit-ros2-diagnostics && make"
                echo "            rsync -a dist/ ${REAL_USER}@<robot>:${CKPT_WS}/dist/"
                echo "          Danach diesen Installer erneut laufen lassen."
                CKPT_OK=0
            fi
        fi
    fi
    if [ "$CKPT_OK" -eq 1 ] && [ -f "${CKPT_WS}/dist/manifest.json" ]; then
        echo ">>> Installiere Plugin nach ${CKPT_PKG_DIR}"
        # Alten Inhalt entfernen, damit geloeschte Dateien nicht liegenbleiben.
        rm -rf "$CKPT_PKG_DIR"
        install -d -m 0755 "$CKPT_PKG_DIR"
        cp -r "${CKPT_WS}/dist/." "$CKPT_PKG_DIR/"
        chown -R root:root "$CKPT_PKG_DIR"
        # Source-Maps sind gross und auf dem Roboter nutzlos (das Debian-Paket
        # wirft sie ebenfalls weg).
        find "$CKPT_PKG_DIR" -name '*.map' -delete
        echo "    Cockpit neu laden: Browser-Reload auf http://<robot>:9090 genuegt."
    else
        echo "    WARN: Cockpit-Plugin nicht installiert (s. Meldungen oben) - das apt-Plugin bleibt aktiv."
    fi
else
    echo ">>> Cockpit-Plugin: uebersprungen."
fi

# --- aktivieren ------------------------------------------------------------
echo ">>> systemd neu einlesen + Services aktivieren (+ starten, nicht nur Boot-Symlink)"
systemctl daemon-reload
# enable --now: aktiviert den Boot-Symlink UND startet die Unit SOFORT. Wichtig bei
# Re-Deploy/Rename auf einem laufenden System: das Migration-disable --now der alten
# Namen stoppt sie, und plain 'enable' wuerde die neuen erst beim naechsten Reboot
# starten -> der ganze Custom-Stack (inkl. ur-state-manager/auto_recover + Watchdog-
# Timer) bliebe bis zum Reboot tot. Wants=clearpath-manipulators zieht den Treiber
# hoch, falls er noch nicht laeuft; After= sichert die Reihenfolge.
systemctl enable --now "$UNIT_NAME" "$RG6_UNIT" "$JS_UNIT"
[ -f "$UR_DASH_UNIT_PATH" ] && systemctl enable --now "$UR_DASH_UNIT"
[ -f "$USM_UNIT_PATH" ] && systemctl enable --now "$USM_UNIT"
# Watchdog: den TIMER aktivieren + starten (die .service ist der oneshot-Check, den er triggert).
[ -f "$WD_TIMER_PATH" ] && systemctl enable --now "$WD_TIMER"
[ -f "$OCTO_UNIT_PATH" ] && systemctl enable --now "$OCTO_UNIT"
[ -f "$MD_UNIT_PATH" ] && systemctl enable --now "$MD_UNIT"

echo ">>> Unit-Syntax pruefen"
VERIFY_UNITS=("$UNIT_PATH" "$RG6_UNIT_PATH" "$JS_UNIT_PATH")
[ -f "$UR_DASH_UNIT_PATH" ] && VERIFY_UNITS+=("$UR_DASH_UNIT_PATH")
[ -f "$USM_UNIT_PATH" ] && VERIFY_UNITS+=("$USM_UNIT_PATH")
[ -f "$WD_UNIT_PATH" ] && VERIFY_UNITS+=("$WD_UNIT_PATH" "$WD_TIMER_PATH")
[ -f "$OCTO_UNIT_PATH" ] && VERIFY_UNITS+=("$OCTO_UNIT_PATH")
[ -f "$MD_UNIT_PATH" ] && VERIFY_UNITS+=("$MD_UNIT_PATH")
systemd-analyze verify "${VERIFY_UNITS[@]}" && echo "    Units OK."

# --- Patches jetzt einmal anwenden -----------------------------------------
if [ -f "$FOXGLOVE_YAML" ]; then
    echo ">>> Wende Config-Patches jetzt einmalig an"
    "$PY_PATH" || true
fi

echo
echo "=============================================================="
echo "Installation abgeschlossen."
echo "  ${UNIT_NAME} : patcht Configs bei jedem Boot"
echo "  ${ROBOT_YAML_PATH} -> ${SETUP_WS}/robot.yaml (Symlink, SSOT im Repo)"
echo "  ${RG6_UNIT}            : startet rg6_control + joint_state_broadcaster + urscript_interface"
echo "  ${JS_UNIT}           : joint_state_aggregator + Legacy-Bus-Relays (Phase 2)"
[ -f "$UR_DASH_UNIT_PATH" ] && \
echo "  ${UR_DASH_UNIT}           : startet ur_robot_driver dashboard_client"
[ -f "$USM_UNIT_PATH" ] && \
echo "  ${USM_UNIT}       : startet ur_state_manager (prepare/recover) + Extra-Controller + Mode-Manager"
[ -f "$WD_TIMER_PATH" ] && \
echo "  ${WD_TIMER}    : Treiber-Reconnect bei spaetem Arm-Einschalten ODER hängengebliebenem Reconnect nach Service-Restart (Health-Signal = JSC-Stream, Kadenz 10s)"
echo "  clearpath-manipulators.service.d/override.conf : SIGINT-Stop-Drop-in (sauberes Treiber-Shutdown, verhindert Socket-Kollision beim Reconnect)"
[ -f "$RG6_MOVEIT_PATCH_BIN" ] && \
echo "  ${RG6_MOVEIT_PATCH_BIN}     : root-eigene Kopie des rg6_moveit_patch (vom Boot-Service genutzt, aktualisiert nur der Installer)"
[ -f "$OCTO_UNIT_PATH" ] && \
echo "  ${OCTO_UNIT}   : Depth->PointCloud2 fuer MoveIts Octomap (Patch-Schritt 5 setzt die move_group-Sensorparameter beim Boot)"
[ -f "$MD_UNIT_PATH" ] && \
echo "  ${MD_UNIT} : UR5 + RG6 -> diagnostic_msgs (Patch-Schritt 6 traegt die Analyzer beim Boot ein)"
[ -d "$CKPT_PKG_DIR" ] && \
echo "  ${CKPT_PKG_DIR} : Cockpit-Plugin mit Manipulator-Panel (ueberdeckt das apt-Plugin unter /usr/share)"
echo
echo "Damit ALLES greift, einmal neu starten:"
echo "  sudo systemctl restart clearpath-robot.service   # oder reboot"
echo
echo "Logs:"
echo "  journalctl -t clearpath-custom-setup -b"
echo "  journalctl -t robot-yaml-update -b"
echo "  journalctl -u ${RG6_UNIT} -b"
echo "  journalctl -u ${JS_UNIT} -b"
[ -f "$UR_DASH_UNIT_PATH" ] && \
echo "  journalctl -u ${UR_DASH_UNIT} -b"
[ -f "$USM_UNIT_PATH" ] && \
echo "  journalctl -u ${USM_UNIT} -b"
[ -f "$WD_TIMER_PATH" ] && \
echo "  journalctl -t manipulators-watchdog -b   # + 'systemctl list-timers ${WD_TIMER}'"
[ -f "$OCTO_UNIT_PATH" ] && \
echo "  journalctl -u ${OCTO_UNIT} -b"
[ -f "$MD_UNIT_PATH" ] && \
echo "  journalctl -u ${MD_UNIT} -b   # + 'ros2 topic echo ${MANIP_NS%/manipulators}/diagnostics_agg'"
echo
echo "Hinweis: robot.yaml wird ab jetzt aus dem Git-Repo verwaltet (SSOT)."
echo "  Aenderungen (platform.extras.urdf, system.ros2.workspaces, Arm-/Sensor-Config)"
echo "  im Repo pflegen (${SETUP_WS}) - der Symlink macht sie SOFORT wirksam:"
echo "  clearpath-robot-check erkennt die Aenderung und startet den Stack neu."
echo "=============================================================="
