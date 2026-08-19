#!/usr/bin/env python3
"""manipulator_diagnostics: UR5 + OnRobot-RG6 als diagnostic_msgs in die
Clearpath-Diagnose-Pipeline einspeisen.

Warum das noetig ist
--------------------
Der ``diagnostic_aggregator`` auf dem a200-0553 abonniert ``<ns>/diagnostics``
(also ``/a200_0553/diagnostics``) und faechert das Ergebnis nach
``<ns>/diagnostics_agg`` auf -- genau der Topic, den die Cockpit-Erweiterung
``cockpit-ros2-diagnostics`` ueber die foxglove_bridge liest.

In dieser Kette fehlt der Manipulator vollstaendig:

* ``clearpath_generator_common`` erzeugt Analyzer nur fuer Platform (Power,
  E-Stop, Drive) und Sensoren -- Arm/Greifer kommen im Generator nicht vor.
* Der ``controller_manager`` des Arms publiziert seine Diagnose in den
  *manipulators*-Namespace (``/a200_0553/manipulators/diagnostics``), also
  NICHT auf den Topic, den der Aggregator abonniert.
* Der ``ur_robot_driver`` publiziert Mode/Safety/ExternalControl ueberhaupt
  nicht als ``diagnostic_msgs``, sondern als eigene ``ur_dashboard_msgs``.
* Der RG6-Zustand kommt als JSON von ``rg6_grip_bridge`` auf
  ``rg6/bridge_state``, nicht als typisierte Message.

Dieser Node uebersetzt all das in ``diagnostic_msgs/DiagnosticArray`` und
publiziert es auf ``/a200_0553/diagnostics``.  Zusammen mit dem Analyzer-Block,
den der Boot-Patcher (``clearpath-custom-setup.py``, Schritt 6) in die
generierte ``diagnostic_aggregator.yaml`` eintraegt, erscheint der Manipulator
damit in *jedem* Diagnose-Konsumenten -- Cockpit, ``rqt_robot_monitor``,
``ros2 topic echo diagnostics_agg`` und im Diagnose-Capture-Bundle.

Gelieferte Status (Prefix = Node-Name, so erwartet es der Analyzer)
-------------------------------------------------------------------
``manipulator_diagnostics: Arm Mode``
    ``robot_mode`` + ``safety_mode`` (latched Topics des io_and_status_controller).
``manipulator_diagnostics: Arm Control``
    Der *eigentliche* Gesundheitsindikator: laeuft der joint_state-Strom des
    ``joint_state_broadcaster``?  Der stroemt nur, wenn das ros2_control-
    Hardware-Interface aktiviert ist -- ``robot_program_running`` allein ist
    KEIN gueltiges Signal (bleibt true, waehrend die PC-seitige Motion-Link
    tot ist; genau der Fall, den der manipulators-Watchdog behandelt).
``manipulator_diagnostics: Arm Joints``
    Gelenkwinkel/-geschwindigkeiten, Rate, Bewegung ja/nein.
``manipulator_diagnostics: Arm Controllers``
    ``controller_manager/list_controllers`` -- welcher Kommando-Controller
    ist aktiv (Trajectory/Freedrive/ForwardPosition/...), fehlt einer?
``manipulator_diagnostics: Gripper``
    RG6: Weite, Kraftsignal, grip_detected, busy, Tool-Power, letzter Befehl.

Aufruf (Service clearpath-custom-manipulator-diagnostics, s. Installer):
    manipulator-diagnostics --ros-args -p manipulator_ns:=/a200_0553/manipulators

Selbsttest ohne ROS (reine Bewertungslogik -- laeuft auch auf der Workstation):
    python3 manipulator_diagnostics.py --selftest
"""
from __future__ import annotations

import math
import sys
from collections import deque, namedtuple

# --------------------------------------------------------------------------- #
# Reine Bewertungslogik (ROS-frei, damit ohne Roboter testbar)
# --------------------------------------------------------------------------- #

OK, WARN, ERROR, STALE = 0, 1, 2, 3

# "INACTIVE" (ausser Betrieb, in Cockpit grau) ist KEIN diagnostic_msgs-Level --
# der Standard kennt nur OK/WARN/ERROR/STALE.  Ein eigener Byte-Wert wuerde die
# max()-Rollups des Aggregators und jeden Fremdkonsumenten (rqt_robot_monitor)
# verwirren.  Deshalb die Konvention: Level bleibt OK (es ist ja nichts kaputt)
# + der Wert 'display=inactive'.  Konsumenten, die die Konvention nicht kennen,
# sehen "OK" mit einer Klartextmeldung ("Arm ausgeschaltet") -- also nichts
# Falsches; Cockpit faerbt daraus grau.
DISPLAY_KEY = "display"
DISPLAY_INACTIVE = "inactive"

Verdict = namedtuple("Verdict", "level message inactive")
Verdict.__new__.__defaults__ = (False,)


def inactive(message):
    """Ausser Betrieb, kein Fehler -- s. DISPLAY_INACTIVE."""
    return Verdict(OK, message, True)


# ur_dashboard_msgs/RobotMode-Konstanten (hier dupliziert, damit der Selbsttest
# ohne ROS laeuft; zur Laufzeit wird gegen die echten .msg-Konstanten geprueft).
ROBOT_MODE_NAMES = {
    -1: "NO_CONTROLLER",
    0: "DISCONNECTED",
    1: "CONFIRM_SAFETY",
    2: "BOOTING",
    3: "POWER_OFF",
    4: "POWER_ON",
    5: "IDLE",
    6: "BACKDRIVE",
    7: "RUNNING",
    8: "UPDATING_FIRMWARE",
}

SAFETY_MODE_NAMES = {
    1: "NORMAL",
    2: "REDUCED",
    3: "PROTECTIVE_STOP",
    4: "RECOVERY",
    5: "SAFEGUARD_STOP",
    6: "SYSTEM_EMERGENCY_STOP",
    7: "ROBOT_EMERGENCY_STOP",
    8: "VIOLATION",
    9: "FAULT",
    10: "VALIDATE_JOINT_ID",
    11: "UNDEFINED_SAFETY_MODE",
}

# Safety-Zustaende, die einen Eingriff erfordern -> ERROR.
SAFETY_ERROR = {3, 5, 6, 7, 8, 9}
# Safety-Zustaende, die den Betrieb einschraenken -> WARN.
SAFETY_WARN = {2, 4, 10, 11}

# E-Stop ist per Software NICHT loesbar -> eigene Klartextmeldung.
SAFETY_ESTOP = {6, 7}

# Was zuletzt an den Greifer ging.  Die Bruecke schickt den Klartext direkt
# (rg6_grip_bridge.COMMAND_*); die numerischen rg6_msgs-Werte werden mit
# uebersetzt, damit archivierte Aufzeichnungen lesbar bleiben.
GRIPPER_COMMANDS = {0: "NONE", 1: "OPEN", 2: "CLOSE", 3: "GRIP"}

# robot_mode-Werte, in denen der Arm bestromt ist -- und damit auch die 24-V-
# Tool-Versorgung des RG6 ueberhaupt anliegen KANN (der Greifer haengt am
# UR-Tool-Anschluss).  BACKDRIVE (Freedrive) zaehlt dazu: Motoren stromlos,
# Steuerung und Tool-Anschluss aber versorgt.
ARM_POWERED_MODES = {4, 5, 6, 7}  # POWER_ON, IDLE, BACKDRIVE, RUNNING

# POWER_OFF ist eine BEDIENERENTSCHEIDUNG, kein Fehler: der Arm wurde bewusst
# abgeschaltet (Wartung/Feierabend).  Alles, was daraus folgt -- kein
# ExternalControl, keine belastbaren Gelenkwerte, stromloser Greifer -- ist
# dann erwartungsgemaess und wird als "ausser Betrieb" (grau) gemeldet, nicht
# als Warnung.  Der manipulators-Watchdog verhaelt sich genauso: bei POWER_OFF
# laeuft keine Recovery.
ARM_OFF_MODE = 3  # POWER_OFF


def arm_is_powered(robot_mode):
    """Kann am Tool-Anschluss ueberhaupt Spannung anliegen? -> True/False/None."""
    if robot_mode is None:
        return None
    return robot_mode in ARM_POWERED_MODES


def arm_is_off(robot_mode):
    """Bewusst abgeschaltet (POWER_OFF)? -> bool."""
    return robot_mode == ARM_OFF_MODE


def robot_mode_name(mode):
    """Int -> Klartext, unbekannte Werte bleiben lesbar."""
    if mode is None:
        return "UNKNOWN"
    return ROBOT_MODE_NAMES.get(mode, f"UNKNOWN({mode})")


def safety_mode_name(mode):
    if mode is None:
        return "UNKNOWN"
    return SAFETY_MODE_NAMES.get(mode, f"UNKNOWN({mode})")


def arm_mode_level(robot_mode, safety_mode):
    """Bewertung von robot_mode/safety_mode -> Verdict.

    Beide Topics sind latched und werden nur bei Aenderung publiziert -- ein
    ``None`` heisst also "noch nie empfangen" (Treiber/Controller nicht da),
    nicht "veraltet".  Deshalb STALE statt ERROR: die Information fehlt, der
    Arm ist deswegen nicht zwangslaeufig kaputt.
    """
    if robot_mode is None and safety_mode is None:
        return Verdict(STALE, "kein robot_mode/safety_mode empfangen - laeuft der "
                              "io_and_status_controller?")

    rm, sm = robot_mode_name(robot_mode), safety_mode_name(safety_mode)

    if safety_mode in SAFETY_ESTOP:
        return Verdict(ERROR, f"Not-Halt aktiv ({sm}) - nur physisch entriegelbar")
    if safety_mode in SAFETY_ERROR:
        return Verdict(ERROR, f"Safety-Stopp: {sm} (robot_mode {rm})")
    if robot_mode is not None and robot_mode < 3:
        # NO_CONTROLLER / DISCONNECTED / CONFIRM_SAFETY: keine Verbindung zur
        # Steuerbox bzw. Bestaetigung am Teach-Panel noetig.
        return Verdict(ERROR, f"Arm nicht ansprechbar: {rm}")
    if safety_mode in SAFETY_WARN:
        return Verdict(WARN, f"Safety eingeschraenkt: {sm} (robot_mode {rm})")
    if robot_mode == 7:
        return Verdict(OK, f"{rm}, Safety {sm}")
    if arm_is_off(robot_mode):
        # Bewusst abgeschaltet -> grau, keine Warnung (s. ARM_OFF_MODE).
        return inactive(f"Arm ausgeschaltet ({rm})")
    # BOOTING / POWER_ON / IDLE / BACKDRIVE / UPDATING_FIRMWARE: Uebergangs-
    # bzw. Sonderzustand, in dem der Arm nicht ROS-fahrbereit ist.
    return Verdict(WARN, f"nicht fahrbereit: {rm} (Safety {sm})")


def arm_control_level(program_running, joint_state_age, timeout, arm_off=False):
    """Bewertung der Motion-Link -> Verdict.

    ``joint_state_age`` ist das Alter der letzten joint_states-Nachricht mit
    Arm-Gelenken in Sekunden (``None`` = noch nie eine bekommen).  Dieser Strom
    ist das belastbare Signal: er fliesst nur, wenn das ros2_control-Hardware-
    Interface aktiv ist.  ``program_running`` (ExternalControl, per RTDE/
    Dashboard gemeldet) kann dabei faelschlich true bleiben.

    Ist der Arm ausgeschaltet, ist BEIDES erwartungsgemaess: ExternalControl
    laeuft nicht, und ob der joint_state-Strom noch fliesst, haengt nur daran,
    ob das Hardware-Interface vor dem Abschalten aktiviert war.  Daraus eine
    Warnung oder gar einen Fehler zu machen, war die Hauptquelle fuer rote
    Anzeigen am ausgeschalteten Arm -- der Watchdog ruehrt bei POWER_OFF
    bewusst ebenfalls nichts an.
    """
    if arm_off:
        return inactive("Arm ausgeschaltet - ExternalControl erwartungsgemaess gestoppt")
    if joint_state_age is None:
        return Verdict(ERROR, "kein joint_state-Strom vom Arm - Hardware-Interface "
                              "nicht aktiviert (Arm spaet eingeschaltet? "
                              "clearpath-manipulators neu starten)")
    if joint_state_age > timeout:
        return Verdict(ERROR, f"joint_state-Strom seit {joint_state_age:.1f}s "
                              "abgerissen - Motion-Link tot")
    if program_running is False:
        return Verdict(WARN, "ExternalControl laeuft nicht (Arm nicht ROS-kommandierbar)")
    if program_running is None:
        return Verdict(WARN, "ExternalControl-Status unbekannt (robot_program_running fehlt)")
    return Verdict(OK, "ExternalControl aktiv, joint_state-Strom laeuft")


def arm_joints_level(joint_count, joint_state_age, timeout, arm_off=False):
    """Bewertung der Gelenkwerte -> Verdict.

    Am ausgeschalteten Arm bleiben die POSITIONEN gueltig (Absolutgeber), aber
    Geschwindigkeit und Effort sind nur noch Rauschen -- gemessen bis
    0.05 rad/s bei voellig stillstehendem Arm.  Deshalb grau statt gruen: die
    Zahlen stehen da, aber "in Bewegung"/"in Ruhe" hat keine Aussage.
    """
    if not joint_count or joint_state_age is None or joint_state_age > timeout:
        return Verdict(STALE, "keine aktuellen Gelenkwerte")
    if arm_off:
        return inactive(f"Arm ausgeschaltet - {joint_count} Gelenke, "
                        "Werte sind die letzten Encoder-Positionen")
    return Verdict(OK, f"{joint_count} Gelenke")


def arm_controllers_level(controllers, required, arm_off=False):
    """Bewertung von list_controllers -> Verdict.

    ``controllers``: {name: state} oder ``None`` (Service nicht erreichbar).
    ``required``: Controller, die aktiv sein MUESSEN (Broadcaster + der
    Default-Kommando-Controller).  Inaktive Kommando-Controller sind
    ausdruecklich normal -- der controller_mode_manager haelt die sich
    gegenseitig ausschliessenden Modi geparkt.

    Echte Controller-Probleme bleiben auch am ausgeschalteten Arm WARN/ERROR
    (sie betreffen die ROS-Seite, nicht die Bestromung); nur der Gutfall wird
    grau, damit die Arm-Kachel geschlossen "ausser Betrieb" zeigt.
    """
    if controllers is None:
        return Verdict(STALE, "controller_manager/list_controllers nicht erreichbar")
    if not controllers:
        return Verdict(ERROR, "controller_manager kennt keine Controller")

    missing = [c for c in required if c not in controllers]
    stopped = [c for c in required if controllers.get(c) not in (None, "active")]
    if missing:
        return Verdict(ERROR, "Controller fehlen: " + ", ".join(sorted(missing)))
    if stopped:
        return Verdict(ERROR, "Controller nicht aktiv: " + ", ".join(sorted(stopped)))

    unconfigured = sorted(n for n, s in controllers.items()
                          if s not in ("active", "inactive"))
    if unconfigured:
        return Verdict(WARN, "Controller in unerwartetem Zustand: "
                             + ", ".join(unconfigured))

    active = sorted(n for n, s in controllers.items() if s == "active")
    summary = f"{len(active)}/{len(controllers)} Controller aktiv"
    if arm_off:
        return inactive(f"{summary} (Arm ausgeschaltet)")
    return Verdict(OK, summary)


#: Felder, die ``rg6_grip_bridge.status_payload`` liefert, mit dem Typ, den
#: sie haben muessen.  Was fehlt, wird None -- ein aelterer Bruecken-Stand
#: soll den Panel nicht leerraeumen, sondern nur die fehlende Zeile.
BRIDGE_FIELDS = {
    "width_m": (int, float),
    "busy": bool,
    "grip_detected": bool,
    "status": int,
    "safety_failed": bool,
    "last_command": str,
}


def parse_bridge_state(data):
    """JSON von ``<ns>/rg6/bridge_state`` -> dict, oder None wenn unbrauchbar.

    Warum ueberhaupt geparst wird:  ``rg6_grip_bridge`` meldet den
    Greiferzustand als JSON in einem ``std_msgs/String``, nicht als typisierte
    Message.  Der String kostet dafuer die Typpruefung, die ein .msg geschenkt
    bekommt, also steht sie hier.

    Nichts hiervon darf werfen:  ein Callback, der an einer fremden Nutzlast
    stirbt, nimmt den ganzen Diagnose-Node mit -- und dann fehlt auch die
    Aussage ueber den ARM, die mit dem Greifer nichts zu tun hat.
    """
    import json

    try:
        raw = json.loads(data)
    except (TypeError, ValueError):
        return None
    if not isinstance(raw, dict):
        return None
    out = {}
    for name, want in BRIDGE_FIELDS.items():
        value = raw.get(name)
        if value is None:
            out[name] = None
        elif want is bool:
            out[name] = value if isinstance(value, bool) else None
        elif isinstance(value, bool):
            # bool ist in Python eine int-Unterklasse -- ohne diesen Zweig
            # ginge ein "width_m": true als Zahl durch.
            out[name] = None
        else:
            out[name] = value if isinstance(value, want) else None
    if out["width_m"] is None and raw.get("width_m") is not None:
        return None                 # eine Weite, die keine Zahl ist: unbrauchbar
    return out


def gripper_signal_valid(width_raw, force_raw, dead_threshold):
    """Liefert der RG6 ueberhaupt ein gueltiges Tool-Signal? -> bool.

    Dieselbe Probe, die der stillgelegte rg6_control intern verwendete
    (Parameter ``dead_input_threshold``, 0.2 V): liegt keine 24-V-Tool-
    Spannung an, sinken AI2 (Weite) und AI3 (Kraft) auf ~0.05 V.

    Warum weiterhin die SPANNUNG und nicht die Antwort des XML-RPC-Endpoints:
    der Endpoint sitzt in der Control-Box und antwortet auch dann, wenn am
    Tool-Anschluss nichts anliegt.  Er weiss, was er zuletzt kommandiert hat
    -- AI2/AI3 wissen, was die Hardware tut.  Aus demselben Grund taugten
    schon die Flags des alten ``rg6_msgs/GripperState`` nicht: sie waren
    Latches bzw. der Treiber-Sollwert, und genau daran hat der Greifer am
    ausgeschalteten Arm "OK" gemeldet.
    """
    if width_raw is None or force_raw is None:
        return False
    return width_raw >= dead_threshold or force_raw >= dead_threshold


def gripper_level(state_age, timeout, signal_valid, robot_mode, width_raw,
                  dead_threshold):
    """Bewertung des RG6-Zustands -> Verdict.

    Der RG6 haengt am UR-Tool-Anschluss: ohne bestromten Arm kann er gar keine
    Versorgung haben.  Das ist dann kein Greiferfehler, sondern eine Folge des
    Armzustands -- entsprechend grau (Arm bewusst aus) bzw. WARN (Arm in einem
    Zustand, in dem er bestromt sein sollte).
    """
    if state_age is None:
        return Verdict(ERROR, "kein rg6/bridge_state - laeuft rg6-grip-bridge?")
    if state_age > timeout:
        # Die Bruecke SCHWEIGT, wenn der XML-RPC-Endpoint nicht antwortet
        # (sie meldet lieber nichts als einen alten Wert).  Ein zu altes
        # Status ist deshalb genau das Signal fuer "Endpoint weg".
        return Verdict(ERROR, f"rg6/bridge_state seit {state_age:.1f}s stumm - "
                              "rg6-grip-bridge tot oder URCap-Endpoint weg?")

    if not signal_valid:
        raw = "n/a" if width_raw is None else f"{width_raw:.2f} V"
        if arm_is_off(robot_mode):
            return inactive("Arm ausgeschaltet - Greifer ohne Versorgung "
                            f"(Tool-Signal {raw})")
        if arm_is_powered(robot_mode) is False:
            return Verdict(WARN, f"Arm nicht bestromt ({robot_mode_name(robot_mode)}) "
                                 f"- Greifer ohne Versorgung (Tool-Signal {raw})")
        # Arm bestromt, trotzdem kein Signal: die 24-V-Tool-Versorgung liegt
        # nicht an.  Sie zu setzen ist Sache der OnRobot-URCap -- der ROS-Weg
        # dorthin ginge ueber Tool-DO, und das belegt die URCap selbst.  Kein
        # ROS-Service kann das hier reparieren; nachzusehen ist am Panel.
        return Verdict(WARN, f"kein gueltiges Tool-Signal ({raw} < "
                             f"{dead_threshold:.2f} V) - Tool stromlos: "
                             "laeuft das URCap-Programm auf dem Panel?")
    return Verdict(OK, "betriebsbereit")


def gripper_summary(width_m, grip_detected, busy, stroke_m):
    """Kurztext fuer die OK-Meldung: 'offen, 158mm (99%)' / 'gegriffen, 42mm'."""
    if width_m is None:
        return "Weite unbekannt"
    mm = width_m * 1000.0
    pct = 100.0 * width_m / stroke_m if stroke_m > 0.0 else 0.0
    if busy:
        state = "in Bewegung"
    elif grip_detected:
        state = "gegriffen"
    elif width_m >= 0.95 * stroke_m:
        state = "offen"
    elif width_m <= 0.02:
        state = "geschlossen"
    else:
        state = "geoeffnet"
    return f"{state}, {mm:.0f}mm ({pct:.0f}%)"


def selftest() -> int:
    """Plausibilitaetstest der Bewertungslogik (ohne ROS, ohne numpy).

    Die Greifer-/POWER_OFF-Faelle sind 1:1 die auf dem a200-0553 gemessenen
    Werte (2026-07-29): bestromt AI2 10.00 V / AI3 1.33 V, stromlos beide
    ~0.056 V bei gleichzeitig tool_power_on=true, *_received=true, busy=true.
    """
    DEAD = 0.2

    # --- Arm Mode ---------------------------------------------------------
    assert arm_mode_level(7, 1).level == OK, "RUNNING/NORMAL muss OK sein"
    assert arm_mode_level(7, 2).level == WARN, "REDUCED -> WARN"
    assert arm_mode_level(7, 3).level == ERROR, "PROTECTIVE_STOP -> ERROR"
    assert arm_mode_level(0, 1).level == ERROR, "DISCONNECTED -> ERROR"
    assert arm_mode_level(None, None).level == STALE, "nichts empfangen -> STALE"
    assert "Not-Halt" in arm_mode_level(7, 7).message, "E-Stop braucht Klartext"
    # Safety schlaegt robot_mode: ein P-Stop bei RUNNING bleibt ERROR.
    assert arm_mode_level(5, 8).level == ERROR, "VIOLATION -> ERROR"
    # POWER_OFF ist eine Bedienerentscheidung -> grau, nicht gelb.
    off = arm_mode_level(3, 1)
    assert off.inactive and off.level == OK, "POWER_OFF -> inaktiv (grau), nicht WARN"
    assert arm_mode_level(4, 1).level == WARN, "POWER_ON (Uebergang) -> WARN"
    assert arm_mode_level(5, 1).level == WARN, "IDLE (Uebergang) -> WARN"
    # Ein Safety-Problem bleibt sichtbar, auch wenn der Arm gerade aus ist.
    assert arm_mode_level(3, 8).level == ERROR, "VIOLATION schlaegt POWER_OFF"

    # --- Arm Control ------------------------------------------------------
    assert arm_control_level(True, 0.01, 2.0).level == OK
    assert arm_control_level(False, 0.01, 2.0).level == WARN, "EC aus -> WARN"
    assert arm_control_level(True, 5.0, 2.0).level == ERROR, "Strom abgerissen -> ERROR"
    # Genau der Watchdog-Fall (b): EC meldet 'laeuft', Motion-Link ist tot.
    assert arm_control_level(True, None, 2.0).level == ERROR, "nie ein JS -> ERROR"
    assert arm_control_level(None, 0.01, 2.0).level == WARN
    # Am ausgeschalteten Arm ist "EC gestoppt" erwartungsgemaess -- und auch
    # ein toter joint_state-Strom ist dann kein Fehler (Watchdog ruht ebenfalls).
    assert arm_control_level(False, 0.01, 2.0, arm_off=True).inactive
    assert arm_control_level(False, None, 2.0, arm_off=True).inactive

    # --- Arm Joints -------------------------------------------------------
    assert arm_joints_level(6, 0.01, 2.0).level == OK
    assert arm_joints_level(6, 5.0, 2.0).level == STALE
    assert arm_joints_level(0, 0.01, 2.0).level == STALE
    assert arm_joints_level(6, 0.01, 2.0, arm_off=True).inactive, "Arm aus -> grau"

    # --- Arm Controllers --------------------------------------------------
    req = ["joint_state_broadcaster", "arm_0_joint_trajectory_controller"]
    all_ok = {"joint_state_broadcaster": "active",
              "arm_0_joint_trajectory_controller": "active",
              "freedrive_mode_controller": "inactive"}
    assert arm_controllers_level(all_ok, req).level == OK, "geparkte Modi sind normal"
    missing = dict(all_ok)
    del missing["joint_state_broadcaster"]
    assert arm_controllers_level(missing, req).level == ERROR
    stopped = dict(all_ok, joint_state_broadcaster="inactive")
    assert arm_controllers_level(stopped, req).level == ERROR
    weird = dict(all_ok, freedrive_mode_controller="unconfigured")
    assert arm_controllers_level(weird, req).level == WARN
    assert arm_controllers_level(None, req).level == STALE
    assert arm_controllers_level(all_ok, req, arm_off=True).inactive
    # Ein echtes Controller-Problem bleibt auch am ausgeschalteten Arm rot.
    assert arm_controllers_level(stopped, req, arm_off=True).level == ERROR

    # --- Gripper: Signalgueltigkeit ---------------------------------------
    assert gripper_signal_valid(10.0, 1.334, DEAD), "bestromt (gemessen)"
    assert not gripper_signal_valid(0.056, 0.053, DEAD), "stromlos (gemessen)"
    assert not gripper_signal_valid(0.0, 0.0, DEAD), "Arm POWER_OFF (gemessen)"
    assert not gripper_signal_valid(None, None, DEAD)
    # Greifer ganz zu: AI2 faellt auf die Kalibrieruntergrenze (0.56 V), liegt
    # aber ueber der Totschwelle -- darf NICHT als stromlos gelten.
    assert gripper_signal_valid(0.56, 0.9, DEAD), "geschlossener Greifer ist nicht tot"

    # --- Gripper: Zustand von der Bruecke ----------------------------------
    # Der Greiferzustand kommt als JSON von rg6_grip_bridge.
    good = parse_bridge_state(
        '{"width_m": 0.1032, "busy": false, "grip_detected": true,'
        ' "status": 0, "safety_failed": false, "last_command": "GRIP"}')
    assert good["width_m"] == 0.1032 and good["grip_detected"] is True, good
    # Kaputte oder fremde Nutzlast darf den Node NICHT umbringen -- sie ist
    # dasselbe wie "kein Status": lieber grau/rot melden als abstuerzen.
    assert parse_bridge_state("kein json") is None
    assert parse_bridge_state("[1, 2, 3]") is None
    assert parse_bridge_state('{"width_m": "breit"}') is None, "Weite muss Zahl sein"
    # Fehlende Felder sind erlaubt und werden zu None -- ein aelterer
    # Bruecken-Stand soll den Panel nicht leerraeumen.
    assert parse_bridge_state('{"width_m": 0.05}')["busy"] is None

    # --- Gripper: Bewertung -----------------------------------------------
    assert gripper_level(0.05, 2.0, True, 7, 10.0, DEAD).level == OK
    stale = gripper_level(9.0, 2.0, True, 7, 10.0, DEAD)
    assert stale.level == ERROR and "bridge" in stale.message, stale.message
    never = gripper_level(None, 2.0, True, 7, None, DEAD)
    assert never.level == ERROR and "bridge" in never.message, never.message
    # DER Fall aus dem Bugreport: Arm POWER_OFF, Greifer ohne Versorgung.
    dead_off = gripper_level(0.05, 2.0, False, 3, 0.0, DEAD)
    assert dead_off.inactive and dead_off.level == OK, "Arm aus -> Greifer grau, nicht OK"
    assert "ausgeschaltet" in dead_off.message
    # Arm bestromt, Greifer trotzdem ohne Signal -> echte Warnung mit Rezept.
    dead_on = gripper_level(0.05, 2.0, False, 7, 0.056, DEAD)
    assert dead_on.level == WARN and not dead_on.inactive
    # Die Tool-Spannung setzt die URCap, kein ROS-Service -- die Warnung muss
    # deshalb ans Panel verweisen und darf keinen Service nennen.
    assert "URCap" in dead_on.message, "Warnung muss den Ausweg nennen"
    assert "set_tool_power" not in dead_on.message, "der Service existiert nicht mehr"
    # Arm in einem unbestromten Nicht-POWER_OFF-Zustand (z.B. BOOTING).
    assert gripper_level(0.05, 2.0, False, 2, 0.0, DEAD).level == WARN

    assert "offen" in gripper_summary(0.159, False, False, 0.160)
    assert "geschlossen" in gripper_summary(0.0, False, False, 0.160)
    assert "gegriffen" in gripper_summary(0.042, True, False, 0.160)
    assert "Bewegung" in gripper_summary(0.042, False, True, 0.160)
    assert gripper_summary(None, False, False, 0.160) == "Weite unbekannt"

    # --- Armzustand -------------------------------------------------------
    assert arm_is_powered(7) and arm_is_powered(6) and arm_is_powered(4)
    assert not arm_is_powered(3) and not arm_is_powered(2)
    assert arm_is_powered(None) is None
    assert arm_is_off(3) and not arm_is_off(7)

    print("manipulator_diagnostics selftest: OK "
          f"({len(ROBOT_MODE_NAMES)} robot_modes, {len(SAFETY_MODE_NAMES)} safety_modes)")
    return 0


# --------------------------------------------------------------------------- #
# ROS-Node (nur importiert, wenn nicht --selftest)
# --------------------------------------------------------------------------- #


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--selftest" in argv:
        return selftest()

    import time

    import rclpy
    from rclpy.executors import ExternalShutdownException
    from rclpy.node import Node
    from rclpy.qos import (DurabilityPolicy, HistoryPolicy, QoSProfile,
                           ReliabilityPolicy)

    from diagnostic_msgs.msg import DiagnosticArray, DiagnosticStatus, KeyValue
    from sensor_msgs.msg import JointState
    from std_msgs.msg import Bool, String

    # Optionale Abhaengigkeiten: fehlt eine, faellt NUR der betroffene Status
    # aus (mit Klartext), der Rest laeuft weiter.  So bleibt der Node auch auf
    # einem Roboter ohne RG6-Workspace startbar.
    try:
        from ur_dashboard_msgs.msg import RobotMode, SafetyMode
        UR_MSGS_ERROR = None
    except ImportError as exc:  # pragma: no cover - haengt an der Installation
        RobotMode = SafetyMode = None
        UR_MSGS_ERROR = str(exc)

    # ToolDataMsg traegt AI2/AI3 und die Tool-Spannung -- die einzigen
    # Greiferzahlen, die NICHT von der Bruecke kommen.  Frueher stand hier
    # rg6_msgs/GripperState; das Paket faellt mit rg6_control aus dem
    # Bootpfad, und der Zustand kommt seitdem als JSON von rg6_grip_bridge.
    try:
        from ur_msgs.msg import ToolDataMsg
        TOOL_MSGS_ERROR = None
    except ImportError as exc:  # pragma: no cover
        ToolDataMsg = None
        TOOL_MSGS_ERROR = str(exc)

    try:
        from controller_manager_msgs.srv import ListControllers
        CM_MSGS_ERROR = None
    except ImportError as exc:  # pragma: no cover
        ListControllers = None
        CM_MSGS_ERROR = str(exc)

    # Latched (transient_local) + publish-on-change: genau so publiziert der
    # gpio_controller robot_mode/safety_mode/robot_program_running.  Ein
    # VOLATILE-Subscriber wuerde den aktuellen Wert beim Start verpassen und
    # bis zur naechsten Aenderung blind bleiben.
    LATCHED = QoSProfile(
        depth=1,
        history=HistoryPolicy.KEEP_LAST,
        reliability=ReliabilityPolicy.RELIABLE,
        durability=DurabilityPolicy.TRANSIENT_LOCAL,
    )

    def kv(values):
        """dict -> KeyValue[]; alles als String, wie es diagnostic_msgs will."""
        return [KeyValue(key=str(k), value=str(v)) for k, v in values.items()]

    # DiagnosticStatus.level ist im .msg ein 'byte' -- rosidl_generator_py bildet
    # das auf ein bytes-Objekt der Laenge 1 ab, NICHT auf int.  Statt das zu
    # raten, wird an der echten Konstanten abgelesen (haelt auch, falls sich das
    # in einer kuenftigen Distro aendert).
    LEVEL_AS_BYTES = isinstance(DiagnosticStatus.OK, bytes)

    def level_field(level):
        return bytes([int(level)]) if LEVEL_AS_BYTES else int(level)

    class ManipulatorDiagnostics(Node):
        def __init__(self) -> None:
            super().__init__("manipulator_diagnostics")

            ns = self.declare_parameter(
                "manipulator_ns", "/a200_0553/manipulators").value.rstrip("/")
            self.diagnostics_topic = self.declare_parameter(
                "diagnostics_topic", "/a200_0553/diagnostics").value
            self.rate_hz = float(self.declare_parameter("rate_hz", 1.0).value)
            self.arm_prefix = self.declare_parameter("arm_prefix", "arm_0_").value
            self.robot_ip = self.declare_parameter("robot_ip", "192.168.131.40").value
            # Der joint_state-Strom laeuft mit 125 Hz; 2 s Toleranz deckt einen
            # Zenoh-Hickser ab, ohne den echten Abriss zu verschleiern.
            self.js_timeout = float(
                self.declare_parameter("joint_state_timeout", 2.0).value)
            self.gripper_timeout = float(
                self.declare_parameter("gripper_timeout", 2.0).value)
            self.stroke_m = float(self.declare_parameter("stroke_m", 0.160).value)
            # Uebernommen aus dem stillgelegten rg6_control (gleichnamiger
            # Parameter): unterhalb dieser Spannung liefert der RG6 kein
            # gueltiges Tool-Signal.
            self.dead_input_threshold = float(
                self.declare_parameter("dead_input_threshold", 0.2).value)
            # Rauschen der Gelenkgeschwindigkeit am STILLSTEHENDEN Arm: bestromt
            # exakt 0.0000, unbestromt bis 0.055 rad/s gemessen. Die Schwelle
            # deckt nur den bestromten Fall ab -- unbestromt wird "in Bewegung"
            # ohnehin unterdrueckt (Status ist dann 'ausser Betrieb').
            self.motion_eps = float(
                self.declare_parameter("motion_eps_rad_s", 0.02).value)
            self.required_controllers = list(self.declare_parameter(
                "required_controllers",
                ["joint_state_broadcaster",
                 "arm_0_joint_trajectory_controller",
                 "io_and_status_controller"]).value)
            self.controller_poll_s = float(
                self.declare_parameter("controller_poll_period", 5.0).value)
            self.arm_hardware_id = self.declare_parameter(
                "arm_hardware_id", f"UR5 CB3 @ {self.robot_ip}").value
            self.gripper_hardware_id = self.declare_parameter(
                "gripper_hardware_id", "OnRobot RG6 @ UR Tool-I/O").value

            # ---- Zustand -------------------------------------------------
            self._robot_mode = None
            self._safety_mode = None
            self._program_running = None
            self._js_stamps = deque(maxlen=64)   # monotone Empfangszeiten (Arm)
            self._joints = {}                    # kurzname -> (pos, vel, eff)
            self._gripper = None                 # letzter Bruecken-Zustand (dict)
            self._gripper_time = None
            self._tool = None                    # letzte ToolDataMsg (AI2/AI3)
            self._controllers = None             # {name: state} | None
            self._controllers_time = None
            self._cm_future = None

            # ---- Subscriptions -------------------------------------------
            if RobotMode is not None:
                self.create_subscription(
                    RobotMode, f"{ns}/io_and_status_controller/robot_mode",
                    self._on_robot_mode, LATCHED)
                self.create_subscription(
                    SafetyMode, f"{ns}/io_and_status_controller/safety_mode",
                    self._on_safety_mode, LATCHED)
            self.create_subscription(
                Bool, f"{ns}/io_and_status_controller/robot_program_running",
                self._on_program_running, LATCHED)
            self.create_subscription(
                JointState, f"{ns}/joint_states", self._on_joint_states, 10)
            self.create_subscription(
                String, f"{ns}/rg6/bridge_state", self._on_gripper, 10)
            if ToolDataMsg is not None:
                self.create_subscription(
                    ToolDataMsg, f"{ns}/io_and_status_controller/tool_data",
                    self._on_tool_data, 10)

            # ---- controller_manager --------------------------------------
            self._cm_client = None
            if ListControllers is not None:
                self._cm_client = self.create_client(
                    ListControllers, f"{ns}/controller_manager/list_controllers")
                self.create_timer(self.controller_poll_s, self._poll_controllers)

            # ---- Ausgang -------------------------------------------------
            self._pub = self.create_publisher(
                DiagnosticArray, self.diagnostics_topic, 10)
            self.create_timer(1.0 / max(self.rate_hz, 0.1), self._tick)

            self.get_logger().info(
                f"manipulator_diagnostics: {ns} -> {self.diagnostics_topic} "
                f"@ {self.rate_hz:.1f} Hz")
            for missing, what in ((UR_MSGS_ERROR, "ur_dashboard_msgs"),
                                  (TOOL_MSGS_ERROR, "ur_msgs"),
                                  (CM_MSGS_ERROR, "controller_manager_msgs")):
                if missing:
                    self.get_logger().error(
                        f"{what} nicht importierbar ({missing}) - der zugehoerige "
                        "Status meldet das als Fehler. Workspace gesourct?")

        # ---- Callbacks ---------------------------------------------------
        def _on_robot_mode(self, msg) -> None:
            self._robot_mode = int(msg.mode)

        def _on_safety_mode(self, msg) -> None:
            self._safety_mode = int(msg.mode)

        def _on_program_running(self, msg: Bool) -> None:
            self._program_running = bool(msg.data)

        def _on_joint_states(self, msg: JointState) -> None:
            """Nur Arm-Gelenke zaehlen.

            Auf ``<ns>/joint_states`` liegen ZWEI Quellen: der Arm-JSB und
            der Fingerwert der Greiferbruecke.  Fuer die Motion-Link-Bewertung
            zaehlt ausschliesslich der Arm-Strom -- die Bruecke pollt ihren
            XML-RPC-Endpoint weiter, auch wenn das Arm-Hardware-Interface tot
            ist, und wuerde einen Abriss sonst kaschieren.
            """
            found = False
            for i, name in enumerate(msg.name):
                if not name.startswith(self.arm_prefix):
                    continue
                found = True
                self._joints[name[len(self.arm_prefix):]] = (
                    msg.position[i] if i < len(msg.position) else float("nan"),
                    msg.velocity[i] if i < len(msg.velocity) else float("nan"),
                    msg.effort[i] if i < len(msg.effort) else float("nan"),
                )
            if found:
                self._js_stamps.append(time.monotonic())

        def _on_gripper(self, msg) -> None:
            """JSON von rg6_grip_bridge.  Muell aendert den Zustand NICHT.

            Der alte Zeitstempel bleibt dann stehen und altert -- damit meldet
            der Panel "stumm" statt "OK mit Unsinn", und das ist die richtige
            Aussage: eine unlesbare Nutzlast ist kein Zustand.
            """
            state = parse_bridge_state(msg.data)
            if state is None:
                self.get_logger().warn(
                    f"unlesbarer rg6/bridge_state: {msg.data[:120]!r}",
                    throttle_duration_sec=10.0)
                return
            self._gripper = state
            self._gripper_time = time.monotonic()

        def _on_tool_data(self, msg) -> None:
            self._tool = msg

        def _poll_controllers(self) -> None:
            """list_controllers asynchron abfragen (nie im Timer blockieren)."""
            if self._cm_future is not None and not self._cm_future.done():
                return  # vorheriger Aufruf haengt noch -> Service ist weg
            if not self._cm_client.service_is_ready():
                self._controllers = None
                return
            self._cm_future = self._cm_client.call_async(ListControllers.Request())
            self._cm_future.add_done_callback(self._on_controllers)

        def _on_controllers(self, future) -> None:
            try:
                result = future.result()
            except Exception as exc:  # defensiv: Service-Callback nie sterben lassen
                self.get_logger().warning(
                    f"list_controllers fehlgeschlagen: {exc}",
                    throttle_duration_sec=30.0)
                self._controllers = None
                return
            self._controllers = {c.name: c.state for c in result.controller}
            self._controllers_time = time.monotonic()

        # ---- Statusaufbau ------------------------------------------------
        def _age(self, stamp):
            return None if stamp is None else time.monotonic() - stamp

        def _joint_state_age(self):
            return self._age(self._js_stamps[-1] if self._js_stamps else None)

        def _joint_state_rate(self):
            """Rate aus dem Zeitfenster der letzten Nachrichten (0.0 = unbekannt)."""
            if len(self._js_stamps) < 2:
                return 0.0
            span = self._js_stamps[-1] - self._js_stamps[0]
            return (len(self._js_stamps) - 1) / span if span > 0.0 else 0.0

        def _status(self, name, verdict, hardware_id, values):
            """Verdict + Werte -> DiagnosticStatus.

            'inactive' wird als Wert mitgeschickt (s. DISPLAY_INACTIVE), nicht
            als eigener Level -- der Level bleibt standardkonform.
            """
            status = DiagnosticStatus()
            status.name = f"{self.get_name()}: {name}"
            status.level = level_field(verdict.level)
            status.message = verdict.message
            status.hardware_id = hardware_id
            if verdict.inactive:
                values = dict(values, **{DISPLAY_KEY: DISPLAY_INACTIVE})
            status.values = kv(values)
            return status

        def _arm_off(self):
            return arm_is_off(self._robot_mode)

        def _arm_mode_status(self):
            if RobotMode is None:
                return self._status(
                    "Arm Mode",
                    Verdict(ERROR, f"ur_dashboard_msgs fehlt ({UR_MSGS_ERROR})"),
                    self.arm_hardware_id, {})
            verdict = arm_mode_level(self._robot_mode, self._safety_mode)
            powered = arm_is_powered(self._robot_mode)
            return self._status("Arm Mode", verdict, self.arm_hardware_id, {
                "robot_mode": robot_mode_name(self._robot_mode),
                "robot_mode_id": self._robot_mode,
                "safety_mode": safety_mode_name(self._safety_mode),
                "safety_mode_id": self._safety_mode,
                # Ableitung fuers UI: entscheidet mit ueber die Greifer-Anzeige.
                "arm_powered": "unknown" if powered is None else str(powered).lower(),
                "robot_ip": self.robot_ip,
            })

        def _arm_control_status(self):
            age = self._joint_state_age()
            verdict = arm_control_level(
                self._program_running, age, self.js_timeout, arm_off=self._arm_off())
            return self._status("Arm Control", verdict, self.arm_hardware_id, {
                "external_control": {True: "running", False: "stopped",
                                     None: "unknown"}[self._program_running],
                "joint_state_rate_hz": f"{self._joint_state_rate():.1f}",
                "joint_state_age_s": "never" if age is None else f"{age:.2f}",
                "joint_state_timeout_s": f"{self.js_timeout:.1f}",
                "motion_interface": ("live" if age is not None
                                     and age <= self.js_timeout else "dead"),
            })

        def _arm_joints_status(self):
            age = self._joint_state_age()
            arm_off = self._arm_off()
            verdict = arm_joints_level(
                len(self._joints), age, self.js_timeout, arm_off=arm_off)
            if verdict.level == STALE:
                return self._status(
                    "Arm Joints", verdict, self.arm_hardware_id,
                    {"joints": "", "joint_state_age_s": "never" if age is None
                     else f"{age:.2f}"})

            values = {"joints": ", ".join(self._joints)}
            moving = False
            for short, (pos, vel, eff) in self._joints.items():
                values[f"{short}_rad"] = f"{pos:.4f}"
                values[f"{short}_deg"] = f"{math.degrees(pos):.1f}"
                values[f"{short}_vel_rad_s"] = f"{vel:.4f}"
                if math.isfinite(eff):
                    values[f"{short}_effort"] = f"{eff:.2f}"
                if math.isfinite(vel) and abs(vel) > self.motion_eps:
                    moving = True
            # Am unbestromten Arm ist die Geschwindigkeit reines Rauschen -- die
            # Bewegungsaussage waere frei erfunden.
            values["moving"] = "unknown" if arm_off else str(moving).lower()
            values["rate_hz"] = f"{self._joint_state_rate():.1f}"
            if not arm_off:
                verdict = Verdict(verdict.level, f"{verdict.message}, "
                                  + ("in Bewegung" if moving else "in Ruhe"))
            return self._status("Arm Joints", verdict, self.arm_hardware_id, values)

        def _arm_controllers_status(self):
            if ListControllers is None:
                return self._status(
                    "Arm Controllers",
                    Verdict(ERROR, f"controller_manager_msgs fehlt ({CM_MSGS_ERROR})"),
                    self.arm_hardware_id, {})
            verdict = arm_controllers_level(
                self._controllers, self.required_controllers, arm_off=self._arm_off())
            values = {"required": ", ".join(self.required_controllers)}
            if self._controllers:
                values.update(self._controllers)
                active = [n for n, s in self._controllers.items()
                          if s == "active" and n not in self.required_controllers]
                values["active_optional"] = ", ".join(sorted(active)) or "-"
            return self._status("Arm Controllers", verdict,
                                self.arm_hardware_id, values)

        def _gripper_status(self):
            """Zwei Quellen, absichtlich getrennt gehalten.

            Der ZUSTAND (Weite, busy, grip_detected) kommt von der Bruecke und
            damit vom Geraet selbst.  Die SPANNUNGEN AI2/AI3 kommen aus
            ``tool_data`` und beantworten eine andere Frage: liegt am
            Tool-Anschluss ueberhaupt Versorgung an?  Sie hier zusammenzulegen
            hiesse, die am 2026-08-19 als um bis zu 17 mm falsch geeicht
            gemessene AI2-Kennlinie (R19) wieder zur Weitenquelle zu machen.
            """
            unknown = "unbekannt"
            age = self._age(self._gripper_time)
            state = self._gripper
            tool = self._tool
            dead = self.dead_input_threshold
            width_raw = None if tool is None else float(tool.analog_input2)
            force_raw = None if tool is None else float(tool.analog_input3)
            # Gueltigkeit ausschliesslich am Analogsignal festmachen: es ist
            # das einzige HARDWARE-Feedback ueber die Tool-Versorgung.
            valid = gripper_signal_valid(width_raw, force_raw, dead)
            verdict = gripper_level(age, self.gripper_timeout, valid,
                                    self._robot_mode, width_raw, dead)
            if state is None:
                return self._status("Gripper", verdict, self.gripper_hardware_id,
                                    {"state_age_s": "never",
                                     "width_raw_v": (unknown if width_raw is None
                                                     else f"{width_raw:.3f}")})

            width = state["width_m"] if valid else None
            if verdict.level == OK and not verdict.inactive:
                verdict = Verdict(verdict.level, gripper_summary(
                    width, state["grip_detected"], state["busy"], self.stroke_m))
            last = state["last_command"]
            values = {
                "width_m": unknown if width is None else f"{width:.4f}",
                "width_mm": unknown if width is None else f"{width * 1000.0:.1f}",
                "width_percent": (unknown if width is None or self.stroke_m <= 0.0
                                  else f"{100.0 * width / self.stroke_m:.0f}"),
                "stroke_mm": f"{self.stroke_m * 1000.0:.0f}",
                # Rohwerte immer zeigen: sie sind die Diagnose selbst.  Sie
                # stammen NICHT aus derselben Quelle wie die Weite -- deshalb
                # taugen sie als Gegenprobe.
                "width_raw_v": unknown if width_raw is None else f"{width_raw:.3f}",
                "force_raw_v": unknown if force_raw is None else f"{force_raw:.3f}",
                "signal_valid": str(valid).lower(),
                "dead_input_threshold_v": f"{dead:.2f}",
                # Ohne Tool-Spannung meldet auch das Geraet nichts Belastbares.
                "grip_detected": (unknown if not valid or state["grip_detected"] is None
                                  else str(state["grip_detected"]).lower()),
                "busy": (unknown if not valid or state["busy"] is None
                         else str(state["busy"]).lower()),
                # Geraetestatus, direkt vom Endpoint (rg_get_status /
                # rg_get_safety_failed) -- das gab es ueber den Tool-DO-Pfad nie.
                "device_status": unknown if state["status"] is None else str(state["status"]),
                "safety_failed": (unknown if state["safety_failed"] is None
                                  else str(state["safety_failed"]).lower()),
                "last_command": (unknown if last is None
                                 else GRIPPER_COMMANDS.get(last, str(last))),
                # ECHTES Hardware-Feedback: die gemessene Spannung, kein
                # kommandierter Sollwert.
                "tool_output_voltage_v": (unknown if tool is None
                                          else f"{float(tool.tool_output_voltage):.0f}"),
                "state_age_s": f"{age:.2f}",
            }
            return self._status("Gripper", verdict, self.gripper_hardware_id, values)

        def _tick(self) -> None:
            array = DiagnosticArray()
            array.header.stamp = self.get_clock().now().to_msg()
            array.status = [
                self._arm_mode_status(),
                self._arm_control_status(),
                self._arm_joints_status(),
                self._arm_controllers_status(),
                self._gripper_status(),
            ]
            self._pub.publish(array)

    rclpy.init()
    node = ManipulatorDiagnostics()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass  # normaler Stopp (Ctrl+C / systemd)
    except Exception:
        # SIGTERM-Shutdown-Race wie im octomap_feed: rclpys Signal-Handler
        # invalidiert den Context, waehrend spin noch ein WaitSet baut.
        if rclpy.ok():
            raise
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
