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
* Der RG6-Zustand existiert nur als ``rg6_msgs/GripperState``.

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

Selbsttest ohne ROS (reine Bewertungslogik -- laeuft auch auf dem Mac):
    python3 manipulator_diagnostics.py --selftest
"""
from __future__ import annotations

import math
import sys
from collections import deque

# --------------------------------------------------------------------------- #
# Reine Bewertungslogik (ROS-frei, damit ohne Roboter testbar)
# --------------------------------------------------------------------------- #

OK, WARN, ERROR, STALE = 0, 1, 2, 3

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

# RG6-Kommandokonstanten (rg6_msgs/GripperState.COMMAND_*).
GRIPPER_COMMANDS = {0: "NONE", 1: "OPEN", 2: "CLOSE", 3: "GRIP"}


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
    """Bewertung von robot_mode/safety_mode -> (level, message).

    Beide Topics sind latched und werden nur bei Aenderung publiziert -- ein
    ``None`` heisst also "noch nie empfangen" (Treiber/Controller nicht da),
    nicht "veraltet".  Deshalb STALE statt ERROR: die Information fehlt, der
    Arm ist deswegen nicht zwangslaeufig kaputt.
    """
    if robot_mode is None and safety_mode is None:
        return STALE, ("kein robot_mode/safety_mode empfangen - laeuft der "
                       "io_and_status_controller?")

    rm, sm = robot_mode_name(robot_mode), safety_mode_name(safety_mode)

    if safety_mode in SAFETY_ESTOP:
        return ERROR, f"Not-Halt aktiv ({sm}) - nur physisch entriegelbar"
    if safety_mode in SAFETY_ERROR:
        return ERROR, f"Safety-Stopp: {sm} (robot_mode {rm})"
    if robot_mode is not None and robot_mode < 3:
        # NO_CONTROLLER / DISCONNECTED / CONFIRM_SAFETY: keine Verbindung zur
        # Steuerbox bzw. Bestaetigung am Teach-Panel noetig.
        return ERROR, f"Arm nicht ansprechbar: {rm}"
    if safety_mode in SAFETY_WARN:
        return WARN, f"Safety eingeschraenkt: {sm} (robot_mode {rm})"
    if robot_mode == 7:
        return OK, f"{rm}, Safety {sm}"
    # POWER_OFF / POWER_ON / IDLE / BOOTING / BACKDRIVE / UPDATING_FIRMWARE:
    # bewusster Betriebszustand, aber nicht fahrbereit.
    return WARN, f"nicht fahrbereit: {rm} (Safety {sm})"


def arm_control_level(program_running, joint_state_age, timeout):
    """Bewertung der Motion-Link -> (level, message).

    ``joint_state_age`` ist das Alter der letzten joint_states-Nachricht mit
    Arm-Gelenken in Sekunden (``None`` = noch nie eine bekommen).  Dieser Strom
    ist das belastbare Signal: er fliesst nur, wenn das ros2_control-Hardware-
    Interface aktiv ist.  ``program_running`` (ExternalControl, per RTDE/
    Dashboard gemeldet) kann dabei faelschlich true bleiben.
    """
    if joint_state_age is None:
        return ERROR, ("kein joint_state-Strom vom Arm - Hardware-Interface "
                       "nicht aktiviert (Arm spaet eingeschaltet? "
                       "clearpath-manipulators neu starten)")
    if joint_state_age > timeout:
        return ERROR, (f"joint_state-Strom seit {joint_state_age:.1f}s "
                       "abgerissen - Motion-Link tot")
    if program_running is False:
        return WARN, "ExternalControl laeuft nicht (Arm nicht ROS-kommandierbar)"
    if program_running is None:
        return WARN, "ExternalControl-Status unbekannt (robot_program_running fehlt)"
    return OK, "ExternalControl aktiv, joint_state-Strom laeuft"


def arm_controllers_level(controllers, required):
    """Bewertung von list_controllers -> (level, message).

    ``controllers``: {name: state} oder ``None`` (Service nicht erreichbar).
    ``required``: Controller, die aktiv sein MUESSEN (Broadcaster + der
    Default-Kommando-Controller).  Inaktive Kommando-Controller sind
    ausdruecklich normal -- der controller_mode_manager haelt die sich
    gegenseitig ausschliessenden Modi geparkt.
    """
    if controllers is None:
        return STALE, "controller_manager/list_controllers nicht erreichbar"
    if not controllers:
        return ERROR, "controller_manager kennt keine Controller"

    missing = [c for c in required if c not in controllers]
    inactive = [c for c in required if controllers.get(c) not in (None, "active")]
    if missing:
        return ERROR, "Controller fehlen: " + ", ".join(sorted(missing))
    if inactive:
        return ERROR, "Controller nicht aktiv: " + ", ".join(sorted(inactive))

    unconfigured = sorted(n for n, s in controllers.items()
                          if s not in ("active", "inactive"))
    if unconfigured:
        return WARN, "Controller in unerwartetem Zustand: " + ", ".join(unconfigured)

    active = sorted(n for n, s in controllers.items() if s == "active")
    return OK, f"{len(active)}/{len(controllers)} Controller aktiv"


def gripper_level(state_age, timeout, tool_data_received, io_states_received,
                  tool_power_on):
    """Bewertung des RG6-Zustands -> (level, message).

    Ohne Tool-Power liefert der RG6 weder Analog- noch Digitalwerte; das ist
    nach einem Arm-Neustart voruebergehend normal (rg6_control zieht die
    Spannung auf der Programm-Flanke selbst hoch), deshalb WARN und nicht
    ERROR.
    """
    if state_age is None:
        return ERROR, "kein rg6/state - laeuft rg6_control?"
    if state_age > timeout:
        return ERROR, f"rg6/state seit {state_age:.1f}s stumm - rg6_control tot?"
    if not tool_power_on:
        return WARN, "Tool-Spannung aus - Greifer stromlos"
    if not tool_data_received:
        return WARN, "keine Tool-Analogwerte (tool_data) - Weite/Kraft unbekannt"
    if not io_states_received:
        return WARN, "keine Tool-Digitalwerte (io_states) - grip_detected/busy unbekannt"
    return OK, "betriebsbereit"


def gripper_summary(width_m, grip_detected, busy, stroke_m):
    """Kurztext fuer die OK-Meldung: 'offen 158mm (99%)' / 'gegriffen 42mm'."""
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
    """Plausibilitaetstest der Bewertungslogik (ohne ROS, ohne numpy)."""
    # --- Arm Mode ---------------------------------------------------------
    assert arm_mode_level(7, 1)[0] == OK, "RUNNING/NORMAL muss OK sein"
    assert arm_mode_level(7, 2)[0] == WARN, "REDUCED -> WARN"
    assert arm_mode_level(7, 3)[0] == ERROR, "PROTECTIVE_STOP -> ERROR"
    assert arm_mode_level(3, 1)[0] == WARN, "POWER_OFF -> WARN (bewusst aus)"
    assert arm_mode_level(0, 1)[0] == ERROR, "DISCONNECTED -> ERROR"
    assert arm_mode_level(None, None)[0] == STALE, "nichts empfangen -> STALE"
    assert "Not-Halt" in arm_mode_level(7, 7)[1], "E-Stop braucht Klartext"
    # Safety schlaegt robot_mode: ein P-Stop bei RUNNING bleibt ERROR.
    assert arm_mode_level(5, 8)[0] == ERROR, "VIOLATION -> ERROR"

    # --- Arm Control ------------------------------------------------------
    assert arm_control_level(True, 0.01, 2.0)[0] == OK
    assert arm_control_level(False, 0.01, 2.0)[0] == WARN, "EC aus -> WARN"
    assert arm_control_level(True, 5.0, 2.0)[0] == ERROR, "Strom abgerissen -> ERROR"
    # Genau der Watchdog-Fall (b): EC meldet 'laeuft', Motion-Link ist tot.
    assert arm_control_level(True, None, 2.0)[0] == ERROR, "nie ein JS -> ERROR"
    assert arm_control_level(None, 0.01, 2.0)[0] == WARN

    # --- Arm Controllers --------------------------------------------------
    req = ["joint_state_broadcaster", "arm_0_joint_trajectory_controller"]
    all_ok = {"joint_state_broadcaster": "active",
              "arm_0_joint_trajectory_controller": "active",
              "freedrive_mode_controller": "inactive"}
    assert arm_controllers_level(all_ok, req)[0] == OK, "geparkte Modi sind normal"
    missing = dict(all_ok)
    del missing["joint_state_broadcaster"]
    assert arm_controllers_level(missing, req)[0] == ERROR
    stopped = dict(all_ok, joint_state_broadcaster="inactive")
    assert arm_controllers_level(stopped, req)[0] == ERROR
    weird = dict(all_ok, freedrive_mode_controller="unconfigured")
    assert arm_controllers_level(weird, req)[0] == WARN
    assert arm_controllers_level(None, req)[0] == STALE

    # --- Gripper ----------------------------------------------------------
    assert gripper_level(0.05, 2.0, True, True, True)[0] == OK
    assert gripper_level(0.05, 2.0, True, True, False)[0] == WARN, "stromlos -> WARN"
    assert gripper_level(0.05, 2.0, False, True, True)[0] == WARN
    assert gripper_level(9.0, 2.0, True, True, True)[0] == ERROR
    assert gripper_level(None, 2.0, True, True, True)[0] == ERROR

    assert "offen" in gripper_summary(0.159, False, False, 0.160)
    assert "geschlossen" in gripper_summary(0.0, False, False, 0.160)
    assert "gegriffen" in gripper_summary(0.042, True, False, 0.160)
    assert "Bewegung" in gripper_summary(0.042, False, True, 0.160)
    assert gripper_summary(None, False, False, 0.160) == "Weite unbekannt"

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
    from std_msgs.msg import Bool

    # Optionale Abhaengigkeiten: fehlt eine, faellt NUR der betroffene Status
    # aus (mit Klartext), der Rest laeuft weiter.  So bleibt der Node auch auf
    # einem Roboter ohne RG6-Workspace startbar.
    try:
        from ur_dashboard_msgs.msg import RobotMode, SafetyMode
        UR_MSGS_ERROR = None
    except ImportError as exc:  # pragma: no cover - haengt an der Installation
        RobotMode = SafetyMode = None
        UR_MSGS_ERROR = str(exc)

    try:
        from rg6_msgs.msg import GripperState
        RG6_MSGS_ERROR = None
    except ImportError as exc:  # pragma: no cover
        GripperState = None
        RG6_MSGS_ERROR = str(exc)

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
            self._gripper = None                 # letzte GripperState-Nachricht
            self._gripper_time = None
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
            if GripperState is not None:
                self.create_subscription(
                    GripperState, f"{ns}/rg6/state", self._on_gripper, 10)

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
                                  (RG6_MSGS_ERROR, "rg6_msgs"),
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

            Auf ``<ns>/joint_states`` publizieren ZWEI Broadcaster: der
            Arm-JSB und der rg6_joint_state_broadcaster.  Fuer die Motion-Link-
            Bewertung zaehlt ausschliesslich der Arm-Strom -- der RG6-JSB laeuft
            aus ``tool_data`` weiter, auch wenn das Arm-Hardware-Interface tot
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
            self._gripper = msg
            self._gripper_time = time.monotonic()

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

        def _status(self, name, level, message, hardware_id, values):
            status = DiagnosticStatus()
            status.name = f"{self.get_name()}: {name}"
            status.level = level_field(level)
            status.message = message
            status.hardware_id = hardware_id
            status.values = kv(values)
            return status

        def _arm_mode_status(self):
            if RobotMode is None:
                return self._status(
                    "Arm Mode", ERROR,
                    f"ur_dashboard_msgs fehlt ({UR_MSGS_ERROR})",
                    self.arm_hardware_id, {})
            level, message = arm_mode_level(self._robot_mode, self._safety_mode)
            return self._status("Arm Mode", level, message, self.arm_hardware_id, {
                "robot_mode": robot_mode_name(self._robot_mode),
                "robot_mode_id": self._robot_mode,
                "safety_mode": safety_mode_name(self._safety_mode),
                "safety_mode_id": self._safety_mode,
                "robot_ip": self.robot_ip,
            })

        def _arm_control_status(self):
            age = self._joint_state_age()
            level, message = arm_control_level(
                self._program_running, age, self.js_timeout)
            return self._status("Arm Control", level, message, self.arm_hardware_id, {
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
            if not self._joints or age is None or age > self.js_timeout:
                return self._status(
                    "Arm Joints", STALE, "keine aktuellen Gelenkwerte",
                    self.arm_hardware_id,
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
                if math.isfinite(vel) and abs(vel) > 0.01:
                    moving = True
            values["moving"] = str(moving).lower()
            values["rate_hz"] = f"{self._joint_state_rate():.1f}"
            return self._status(
                "Arm Joints", OK,
                f"{len(self._joints)} Gelenke, " +
                ("in Bewegung" if moving else "in Ruhe"),
                self.arm_hardware_id, values)

        def _arm_controllers_status(self):
            if ListControllers is None:
                return self._status(
                    "Arm Controllers", ERROR,
                    f"controller_manager_msgs fehlt ({CM_MSGS_ERROR})",
                    self.arm_hardware_id, {})
            level, message = arm_controllers_level(
                self._controllers, self.required_controllers)
            values = {"required": ", ".join(self.required_controllers)}
            if self._controllers:
                values.update(self._controllers)
                active = [n for n, s in self._controllers.items()
                          if s == "active" and n not in self.required_controllers]
                values["active_optional"] = ", ".join(sorted(active)) or "-"
            return self._status("Arm Controllers", level, message,
                                self.arm_hardware_id, values)

        def _gripper_status(self):
            if GripperState is None:
                return self._status(
                    "Gripper", ERROR, f"rg6_msgs fehlt ({RG6_MSGS_ERROR})",
                    self.gripper_hardware_id, {})
            age = self._age(self._gripper_time)
            msg = self._gripper
            level, message = gripper_level(
                age, self.gripper_timeout,
                bool(msg.tool_data_received) if msg else False,
                bool(msg.io_states_received) if msg else False,
                bool(msg.tool_power_on) if msg else False)
            if msg is None:
                return self._status("Gripper", level, message,
                                    self.gripper_hardware_id,
                                    {"state_age_s": "never"})

            width = msg.width if msg.tool_data_received else None
            if level == OK:
                message = gripper_summary(
                    width, msg.grip_detected, msg.busy, self.stroke_m)
            values = {
                "width_m": "unknown" if width is None else f"{width:.4f}",
                "width_mm": "unknown" if width is None else f"{width * 1000.0:.1f}",
                "width_percent": ("unknown" if width is None or self.stroke_m <= 0.0
                                  else f"{100.0 * width / self.stroke_m:.0f}"),
                "stroke_mm": f"{self.stroke_m * 1000.0:.0f}",
                "width_raw_v": f"{msg.width_raw:.3f}",
                "force_raw_v": f"{msg.force_raw:.3f}",
                "grip_detected": str(bool(msg.grip_detected)).lower(),
                "busy": str(bool(msg.busy)).lower(),
                "tool_power_on": str(bool(msg.tool_power_on)).lower(),
                "high_force_preset": str(bool(msg.high_force_preset)).lower(),
                "last_command": GRIPPER_COMMANDS.get(
                    int(msg.last_command), str(msg.last_command)),
                "io_states_received": str(bool(msg.io_states_received)).lower(),
                "tool_data_received": str(bool(msg.tool_data_received)).lower(),
                "state_age_s": f"{age:.2f}",
            }
            return self._status("Gripper", level, message,
                                self.gripper_hardware_id, values)

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
