#!/usr/bin/env python3
"""rg6_grip_bridge: kommandiert den RG6 per XML-RPC an die OnRobot-URCap.

Warum nicht mehr ueber rg6_control (Tool-DO0):  die URCap ist selbst
RTDE-Client und belegt ``tool_digital_output_mask``.  Damit der
ur_robot_driver ueberhaupt startet, laeuft er seit husky-custom-setup
31a45d0 auf einem Input-Recipe OHNE die tool_digital_output*-Zeilen -- ROS
kann seitdem kein Tool-DO mehr setzen, und rg6_control steuerte den Greifer
ausschliesslich darueber.  Der Treiber ist damit tot, nicht kaputt.

Warum nicht per URScript ueber Port 30002:  rg_grip/rg_Width/rg_index_get()
legt erst das Installations-Preamble an, das PolyScope vor jedes generierte
Programm setzt.  Ein ueber 30002 gesendetes Skript laeuft ohne den Preamble,
das Symbol wird verworfen (2026-08-17 gemessen: kein Programmwechsel, AI2
unveraendert, ``textmsg("literal")`` als Kontrolle durch).

Warum onboard und nicht im Offboard-Container:  der Endpoint haengt am
Arm-Subnetz 192.168.131.0/24.  Von der Workstation gibt es dorthin keine
Route (2026-08-17: TCP-Timeout, kein Interface; netbird annonciert das
Subnetz nicht).  Und der Roboter muss greifen koennen, auch wenn die
Funkstrecke weg ist -- dasselbe Argument, mit dem R16 die Reflexschicht
onboard verortet.

Der Endpoint kann mehr, als frueher notiert war: neben ``rg_grip`` gibt es
einen vollstaendigen Status-Rueckweg (``rg_get_width``, ``rg_get_busy``,
``rg_get_grip_detected``, ``rg_get_status``, ``rg_get_safety_failed``).  Die
Spannungsnaeherung ueber AI2 wird dadurch ueberfluessig -- und AI2 ist am
2026-08-17 als um ~17 mm falsch geeicht aufgefallen, gemessen gegen genau
diese Getter.

Selbsttest ohne ROS (laeuft auch auf der Workstation):
    python3 rg6_grip_bridge.py --selftest
"""
from __future__ import annotations

import json
import sys
import threading
import time
import xmlrpc.client
from dataclasses import dataclass

#: Default-Endpoint.  Pfad ist "/", NICHT "/RPC2" -- der Xmlrpc-c-Abyss im
#: ToolDaemon des CB3 bedient nur die Wurzel.
DEFAULT_URL = "http://192.168.131.40:41414/"
#: RG6-Nennbereiche (Bedienungsanleitung v6.6.2).  Geklemmt wird HIER, damit
#: ein zu grosser Wunsch nicht als Fault zurueckkommt, sondern als das, was
#: das Geraet kann.
WIDTH_RANGE_MM = (0.0, 160.0)
FORCE_RANGE_N = (0.0, 120.0)


class Rg6Error(Exception):
    """Der Greifer hat ein Kommando nicht angenommen oder nicht geantwortet."""


@dataclass(frozen=True)
class Rg6State:
    """Momentaufnahme des Greifers, direkt vom Geraet."""

    width_m: float
    busy: bool
    grip_detected: bool
    status: int
    safety_failed: bool


def _clamp(value: float, lo: float, hi: float) -> float:
    return min(max(float(value), lo), hi)


class Rg6Client:
    """XML-RPC-Schnittstelle zur OnRobot-URCap.

    Die EINZIGE Stelle, an der Einheiten gewechselt werden: das Profil und der
    ``/twin/*``-Draht rechnen in Metern, der Endpoint in Millimetern.
    """

    def __init__(self, url: str = DEFAULT_URL, tool_index: int = 0,
                 timeout_s: float = 3.0) -> None:
        self._url = url
        self._tool = int(tool_index)
        # Harter Timeout: ohne ihn haelt ein toter Endpoint den Worker-Thread
        # unbegrenzt, und mit ihm den joint_states-Publisher.
        transport = xmlrpc.client.Transport()
        transport.timeout = float(timeout_s)
        self._proxy = xmlrpc.client.ServerProxy(url, transport=transport,
                                                allow_none=True)
        # ServerProxy ist NICHT thread-sicher: Proxy und Transport teilen sich
        # EINE HTTP-Verbindung.  Hier greifen zwei Threads darauf zu -- der
        # Greif-Worker und der Zustands-Poller des Fingergelenks -- und ohne
        # diese Sperre verschraenken sich ihre Requests auf dem Socket.
        self._lock = threading.Lock()

    @property
    def url(self) -> str:
        return self._url

    def grip(self, width_m: float, force_n: float) -> None:
        """Auf ``width_m`` fahren.  ``Rg6Error``, wenn das Geraet nein sagt."""
        width_mm = _clamp(width_m * 1000.0, *WIDTH_RANGE_MM)
        force = _clamp(force_n, *FORCE_RANGE_N)
        # "+ 0.0" ist NICHT kosmetisch: ein int gibt Fault -501.  Ein
        # kommandiertes 0 mm oder 60 N kaeme sonst als int auf den Draht.
        rc = self._call("rg_grip", self._tool, width_mm + 0.0, force + 0.0)
        if int(rc) != 0:
            raise Rg6Error(f"rg_grip({width_mm:.1f} mm, {force:.1f} N) "
                           f"antwortete {rc!r} statt 0")

    def stop(self) -> None:
        self._call("rg_stop", self._tool)

    def state(self) -> Rg6State:
        return Rg6State(
            width_m=float(self._call("rg_get_width", self._tool)) / 1000.0,
            busy=bool(self._call("rg_get_busy", self._tool)),
            grip_detected=bool(self._call("rg_get_grip_detected", self._tool)),
            status=int(self._call("rg_get_status", self._tool)),
            safety_failed=bool(self._call("rg_get_safety_failed", self._tool)),
        )

    def _call(self, method: str, *args):
        try:
            with self._lock:
                return getattr(self._proxy, method)(*args)
        except xmlrpc.client.Fault as exc:
            raise Rg6Error(f"{method}: Fault {exc.faultCode} "
                           f"{exc.faultString}") from exc
        except OSError as exc:
            raise Rg6Error(f"{method}: {self._url} nicht erreichbar "
                           f"({exc})") from exc


def await_settled(client, start_timeout_s: float = 1.0,
                  motion_timeout_s: float = 10.0,
                  poll_s: float = 0.05) -> Rg6State:
    """Warten, bis die Hand steht, und DANN den Zustand lesen.

    ``rg_grip`` quittiert die **Annahme**, nicht das Ergebnis.  Wer sofort
    danach liest, bekommt die Weite von vorher -- am 2026-08-19 ueber den
    Draht gemessen: kommandierte 60 mm, gefahren auf 64,96 mm, gemeldete
    2,8 mm (der Startwert).  Mit ``width_m`` war auch ``grasped`` wertlos,
    und das ist das Feld, wegen dem der ganze Rueckweg existiert.

    Gewartet wird auf **beide** Flanken, und der Grund fuer die erste ist
    gemessen: nach dem Kommando steht ``busy`` noch rund 0,4 s auf false,
    bevor der Greifer losfaehrt (65 -> 20 mm, 5-Hz-Abtastung: false bei 0,0
    und 0,2 s, true ab 0,41 s, wieder false ab 1,45 s).  Ein blosses "warte,
    solange busy" kehrte in dieser Luecke sofort zurueck -- derselbe Fehler
    in neuem Gewand.

    Beide Fenster laufen ab, statt zu haengen: faehrt der Greifer gar nicht
    erst los (er steht schon am Ziel), antwortet die Funktion nach
    ``start_timeout_s`` mit dem, was da ist.
    """
    deadline = time.monotonic() + start_timeout_s
    state = client.state()
    while not state.busy and time.monotonic() < deadline:
        time.sleep(poll_s)
        state = client.state()
    deadline = time.monotonic() + motion_timeout_s
    while state.busy and time.monotonic() < deadline:
        time.sleep(poll_s)
        state = client.state()
    return state


#: Was zuletzt an den Greifer ging.  Bewusst dieselben Namen wie in
#: rg6_msgs/GripperState.COMMAND_* -- die Manipulator-Diagnose zeigt sie an,
#: und ein Namenswechsel haette dort nur den Klartext kaputtgemacht.
COMMAND_NONE = "NONE"
COMMAND_GRIP = "GRIP"
COMMAND_STOP = "STOP"


def status_payload(state, last_command: str = COMMAND_NONE) -> dict:
    """Geraetezustand fuer ``<ns>/rg6/bridge_state`` -- flach, als JSON.

    Warum ein eigenes Topic und nicht rg6_msgs/GripperState:  mit dem
    rg6_control-Ruhestand faellt das ganze rg6_msgs-Paket aus dem Bootpfad,
    und ein Statustopf, der ein totes Paket braucht, waere genau die
    Abhaengigkeit, die hier abgebaut wird.  JSON in einem std_msgs/String
    kostet keinen Build und keinen Overlay -- dieselbe Entscheidung, die auf
    ``/twin/*`` schon getragen hat.

    NICHT enthalten sind AI2/AI3:  die Rohspannungen stehen auf
    ``io_and_status_controller/tool_data``, und wer sie braucht, liest sie
    dort.  Sie hier zu spiegeln hiesse, eine zweite Quelle fuer dieselbe Zahl
    zu schaffen -- und AI2 ist am 2026-08-19 als um bis zu 17 mm falsch
    geeicht gemessen worden (R19), also gerade keine gute Zweitmeinung.
    """
    return {
        "width_m": state.width_m,
        "busy": state.busy,
        "grip_detected": state.grip_detected,
        "status": state.status,
        "safety_failed": state.safety_failed,
        "last_command": last_command,
    }


def result_payload(request_id: str, phase: str, *, state, reason: str = "",
                   detail: str = "", elapsed_s: float = 0.0) -> dict:
    """``/twin/result``-Nutzlast — gebaut von robot_contract, nicht von hier.

    Warum importiert statt nachgebaut:  eine zweite Fassung des Vertrags ist
    genau das Muster, an dem octomap_feed.py schon einmal in drei Fassungen
    auseinandergelaufen ist -- und es traefe diesmal den DRAHT, nicht einen
    Parameter.  robot_contract haengt nur an pyyaml und numpy, beide sind auf
    dem Roboter da; der Installer legt es mit ab.

    ``io_states_received`` heisst im Vertrag "es liegt echter Geraetestatus
    vor".  Beim rg6_control-Pfad kam der aus Tool-DI0, hier aus
    ``rg_get_grip_detected`` -- dieselbe Aussage, andere Quelle.  Ohne
    ``state`` ist er False, und der Vertrag macht ``grasped`` dann zwingend
    None.
    """
    from robot_contract import twin_protocol as tp

    return tp.gripper_result(
        request_id, phase,
        source="real",
        reason=reason,
        detail=detail,
        elapsed_s=elapsed_s,
        grasped=None if state is None else state.grip_detected,
        reached_goal=False,
        width_m=None if state is None else state.width_m,
        force_raw=None,
        io_states_received=state is not None,
        tool_data_received=state is not None,
    )


# ---------------------------------------------------------------------------
# Selbsttest -- ohne ROS, damit er auch auf der Workstation laeuft.
# ---------------------------------------------------------------------------
def _spawn_fake_urcap():
    """Lokaler XML-RPC-Doppelgaenger; gibt (server, thread, url, log) zurueck.

    Er bildet die zwei Eigenheiten des echten Endpoints nach, an denen sich
    ein Fehler versteckt: int-Argumente sind ein Fault -501, und die Weite
    kommt in Millimetern zurueck.
    """
    from xmlrpc.server import SimpleXMLRPCServer

    log = []
    state = {"width_mm": 103.26, "busy": False, "grip": False,
             "target_mm": 103.26, "phasen": []}

    def rg_grip(tool, width, force):
        if not isinstance(width, float) or not isinstance(force, float):
            raise xmlrpc.client.Fault(-501, "expected double")
        log.append(("grip", tool, width, force))
        # Nachgebildet nach der Messung am 2026-08-19 (65 -> 20 mm): nach dem
        # Kommando steht ``busy`` noch rund 0,4 s auf false, DANN faehrt die
        # Hand rund 1,2 s, und erst am Ende steht die neue Weite.  ``rg_grip``
        # selbst kehrt sofort zurueck -- es quittiert die Annahme, nicht das
        # Ergebnis.
        state["target_mm"] = width
        state["phasen"] = ["ruht", "ruht", "faehrt", "faehrt", "faehrt"]
        return 0

    def rg_get_busy(tool):
        if not state["phasen"]:
            return state["busy"]
        phase = state["phasen"].pop(0)
        if not state["phasen"]:
            state["width_mm"] = state["target_mm"]   # Fahrt zu Ende
        return phase == "faehrt"

    def rg_stop(tool):
        log.append(("stop", tool))
        return 0

    srv = SimpleXMLRPCServer(("127.0.0.1", 0), logRequests=False,
                             allow_none=True)
    srv.register_function(rg_grip, "rg_grip")
    srv.register_function(rg_stop, "rg_stop")
    srv.register_function(lambda t: state["width_mm"], "rg_get_width")
    srv.register_function(rg_get_busy, "rg_get_busy")
    srv.register_function(lambda t: state["grip"], "rg_get_grip_detected")
    srv.register_function(lambda t: 0, "rg_get_status")
    srv.register_function(lambda t: False, "rg_get_safety_failed")
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    host, port = srv.server_address
    return srv, thread, f"http://{host}:{port}/", log


def selftest() -> int:
    srv, _thread, url, log = _spawn_fake_urcap()
    try:
        cli = Rg6Client(url)

        # 1. Weite geht in Millimetern raus und kommt in Metern zurueck.
        #    Gelesen wird NACH der Fahrt -- warum, steht bei 5a.
        cli.grip(0.100, 60.0)
        assert log[-1][2] == 100.0, log[-1]
        assert abs(await_settled(cli, poll_s=0.0).width_m - 0.100) < 1e-9

        # 2. Beide Zahlen sind float -- der Doppelgaenger faultet sonst.
        cli.grip(0.0, 60.0)
        assert isinstance(log[-1][2], float) and isinstance(log[-1][3], float)

        # 3. Geklemmt wird auf den Geraetebereich, nicht durchgereicht.
        cli.grip(0.500, 999.0)
        assert log[-1][2] == 160.0 and log[-1][3] == 120.0, log[-1]

        # 4. Ein toter Endpoint ist ein Rg6Error, kein Haenger.
        dead = Rg6Client("http://127.0.0.1:9/", timeout_s=0.5)
        try:
            dead.state()
        except Rg6Error:
            pass
        else:                                    # pragma: no cover
            raise AssertionError("toter Endpoint haette Rg6Error geben muessen")

        # 5. Der Draht-Vertrag kommt aus robot_contract, nicht von hier.
        from robot_contract import twin_protocol as tp
        cmd = tp.parse_gripper_command(
            json.dumps({"close": True, "request_id": "r1", "width_m": 0.1}))
        assert cmd["request_id"] == "r1" and cmd["width_m"] == 0.1

        st = Rg6State(width_m=0.1032, busy=False, grip_detected=True,
                      status=0, safety_failed=False)
        payload = result_payload("r1", "succeeded", state=st, elapsed_s=0.4)
        assert payload["grasped"] is True, payload
        assert abs(payload["width_m"] - 0.1032) < 1e-9, payload

        # Ohne Geraetestatus ist 'grasped' DREIWERTIG None, nicht False --
        # sonst hiesse "keine Daten" dasselbe wie "nichts gegriffen".
        blind = result_payload("r2", "failed", state=None, reason="not_available")
        assert blind["grasped"] is None, blind

        # 5a. Ein Ergebnis, das SOFORT nach rg_grip gelesen wird, meldet die
        #     Weite von VORHER.  Am 2026-08-19 ueber den Draht gemessen:
        #     kommandierte 60 mm, gefahren auf 64,96 mm, gemeldet 2,8 mm --
        #     der Startwert.  ``rg_grip`` quittiert die Annahme, nicht das
        #     Ergebnis, und mit ``width_m`` waere auch ``grasped`` wertlos.
        cli.grip(0.020, 40.0)
        assert abs(cli.state().width_m - 0.020) > 0.001, "zu frueh gelesen -> alter Wert"

        # ... und mit dem Warten stimmt er.  Gewartet wird auf BEIDE Flanken:
        #     der Greifer steht nach dem Kommando noch rund 0,4 s still
        #     (gemessen), ein blosses "solange busy" kehrte sofort zurueck.
        cli.grip(0.045, 40.0)
        settled = await_settled(cli, poll_s=0.0)
        assert abs(settled.width_m - 0.045) < 1e-9, settled

        # Faehrt der Greifer gar nicht erst los (er steht schon am Ziel),
        # antwortet das Warten nach dem Anlauffenster -- nicht nie.
        stalled = await_settled(cli, start_timeout_s=0.05, poll_s=0.0)
        assert abs(stalled.width_m - 0.045) < 1e-9, stalled

        # 5b. Der Statustopf traegt den GERAETEZUSTAND, nicht den Befehl --
        #     die Manipulator-Diagnose bewertet ihn, seit rg6_control und mit
        #     ihm rg6_msgs/GripperState in Ruhestand gehen.
        status = status_payload(st, COMMAND_GRIP)
        assert status["width_m"] == st.width_m, status
        assert status["grip_detected"] is True, status
        assert status["last_command"] == COMMAND_GRIP, status
        # Er muss durch json.dumps passen -- er geht als String auf den Draht.
        assert json.loads(json.dumps(status)) == status, status
        # AI2/AI3 gehoeren NICHT hinein (s. Docstring): eine zweite Quelle
        # fuer dieselbe Zahl, und die schlechtere.
        assert "width_raw" not in status and "force_raw" not in status, status

        # 6. Weite -> Fingergelenk kommt aus der Getriebegeometrie des Profils,
        #    nicht aus einem Ankerpaar (R19).
        from robot_contract import load_profile
        linkage = load_profile().gripper.linkage
        # Monoton fallend: weiter offen -> kleinerer (negativerer) Gelenkwert.
        assert linkage.angle_from_width(0.100) < linkage.angle_from_width(0.045)
        # Ganz zu ist die obere Gelenkgrenze, ganz auf die untere -- und die
        # WEITE wird geklemmt, nicht das acos-Argument: eine negative Weite
        # laege sonst still jenseits der geschlossenen Stellung.
        assert linkage.angle_from_width(-0.05) == linkage.angle_from_width(0.0)
        assert (linkage.angle_from_width(0.300)
                == linkage.angle_from_width(linkage.max_width_m))

        # 7. Zwei Threads auf EINER ServerProxy -- im Node sind das der
        #    Greif-Worker und der Fingergelenk-Poller.  Ohne die Sperre in
        #    _call verschraenken sich ihre Requests auf dem gemeinsamen
        #    Socket; das aeussert sich als ResponseNotReady/BadStatusLine.
        errors = []

        def _hammer():
            try:
                for _ in range(25):
                    cli.state()
            except Exception as exc:             # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=_hammer) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert not errors, errors
    finally:
        srv.shutdown()

    print("rg6_grip_bridge selftest: OK (Einheiten, float-Zwang, Klemmung, "
          "Timeout, Draht-Vertrag, Statustopf, Getriebe, Nebenlaeufigkeit)")
    return 0


# ---------------------------------------------------------------------------
# ROS-Node -- rclpy wird ERST HIER importiert, damit --selftest auch auf der
# Workstation laeuft, wo kein rclpy liegt.
# ---------------------------------------------------------------------------
def run(argv) -> int:
    import rclpy
    from rclpy.node import Node
    from std_msgs.msg import String
    from robot_contract import load_profile
    from robot_contract import twin_protocol as tp

    profile = load_profile()

    rclpy.init(args=argv)
    node = Node("rg6_grip_bridge")
    log = node.get_logger()

    node.declare_parameter("endpoint_url", DEFAULT_URL)
    node.declare_parameter("tool_index", 0)
    node.declare_parameter("timeout_s", 3.0)
    node.declare_parameter("default_force_n",
                           float(profile.gripper.default_effort_n))
    node.declare_parameter("open_width_m",
                           float(profile.gripper.linkage.max_width_m))
    # Warten auf das Ende der Fahrt (s. await_settled).  Als Parameter, weil
    # die Zahlen aus einer Messung an EINEM Greifer stammen: 0,4 s Anlauf,
    # 1,2 s Fahrt ueber 45 mm.  1,0 s Anlauffenster ist zugleich die
    # Wartezeit fuer ein Kommando, das gar nichts zu tun hat.
    node.declare_parameter("settle_start_timeout_s", 1.0)
    node.declare_parameter("settle_motion_timeout_s", 10.0)
    node.declare_parameter("settle_poll_s", 0.05)

    def _p(name):
        return node.get_parameter(name).value

    client = Rg6Client(_p("endpoint_url"), int(_p("tool_index")),
                       float(_p("timeout_s")))
    results = node.create_publisher(String, tp.RESULT_TOPIC, 10)

    # -- Fingergelenk ------------------------------------------------------
    # Seit rg6-bringup tot ist, fehlt rg6_finger_joint in /joint_states (am
    # 2026-08-17 gemessen).  move_group sieht den Greifer seitdem in seiner
    # DEFAULT-Stellung, und jede Freiraumpruefung um die Hand rechnet gegen
    # eine Stellung, die er nicht hat -- dieselbe Klasse wie R15, nur
    # beweglich.  Dieser Node hat die gemessene Weite ohnehin.
    from sensor_msgs.msg import JointState

    node.declare_parameter("joint_state_rate_hz", 5.0)
    finger_joint = profile.gripper.driver_joint
    linkage = profile.gripper.linkage
    joints = node.create_publisher(
        JointState, f"{profile.manipulators.ns}/endeffectors/joint_states", 10)
    # Derselbe Poll traegt den Zustand fuer die Manipulator-Diagnose.  Sie las
    # ihn bis zum rg6_control-Ruhestand aus rg6_msgs/GripperState auf
    # <ns>/rg6/state; dieses Topic hat seitdem keinen Publisher mehr.
    states = node.create_publisher(
        String, f"{profile.manipulators.ns}/rg6/bridge_state", 10)
    last_command = [COMMAND_NONE]

    def _poll_joint() -> None:
        """Den Fingerwert aus der GEMESSENEN Weite, nicht aus dem Befehl.

        Eigener Thread und KEIN ROS-Timer:  ``client.state()`` ist ein
        blockierender XML-RPC-Aufruf.  Im Timer-Callback haenge er am
        Executor -- bei totem Endpoint 3 s (der Transport-Timeout) alle
        200 ms, und der Greifbefehl kaeme in derselben Zeit nicht durch.
        Das ist derselbe Grund, aus dem schon ``_work`` ausgelagert ist.

        Die Umrechnung Weite -> Gelenk macht die Getriebegeometrie des
        Profils (R19), nicht dieser Node -- es ist dieselbe Kinematik, die
        auch das URDF traegt.
        """
        period = 1.0 / float(_p("joint_state_rate_hz"))
        while rclpy.ok():
            try:
                state = client.state()
            except Rg6Error:
                # Still bleiben ist besser als luegen -- und das SCHWEIGEN ist
                # zugleich das Signal: die Diagnose bewertet das Alter des
                # letzten Statuses und meldet den Ausfall daraus.
                time.sleep(period)
                continue
            msg = JointState()
            msg.header.stamp = node.get_clock().now().to_msg()
            msg.name = [finger_joint]
            msg.position = [float(linkage.angle_from_width(state.width_m))]
            joints.publish(msg)
            states.publish(String(
                data=json.dumps(status_payload(state, last_command[0]))))
            time.sleep(period)

    threading.Thread(target=_poll_joint, daemon=True).start()

    # EIN Befehl je Zeit.  Ein zweiter waehrend der Fahrt wird ABGELEHNT, nicht
    # eingereiht: am 2026-08-17 haben zehn aufeinandergestapelte Goals den
    # alten Treiber in busy=true mit width_raw am Anschlag festgefahren.
    inflight = threading.Lock()
    seen: set = set()

    def _emit(payload: dict) -> None:
        results.publish(String(data=json.dumps(payload)))

    def _work(cmd: dict) -> None:
        request_id = cmd["request_id"]
        started = time.monotonic()
        try:
            width_m = cmd.get("width_m")
            if width_m is None:
                # Ohne Zielweite bedeutet close=True "ganz zu", close=False
                # "ganz auf".  Der Endpoint kennt keine Presets, nur Weiten.
                width_m = 0.0 if cmd["close"] else float(_p("open_width_m"))
            force_n = float(cmd.get("force_n") or _p("default_force_n"))
            last_command[0] = COMMAND_GRIP
            client.grip(float(width_m), force_n)
            # NICHT sofort lesen: rg_grip quittiert die Annahme, nicht das
            # Ergebnis (Begruendung und Messung bei await_settled).
            state = await_settled(client, float(_p("settle_start_timeout_s")),
                                  float(_p("settle_motion_timeout_s")),
                                  float(_p("settle_poll_s")))
            _emit(result_payload(request_id, "succeeded", state=state,
                                 elapsed_s=time.monotonic() - started))
            log.info(f"gripper {width_m * 1000:.0f} mm @ {force_n:.0f} N -> "
                     f"{state.width_m * 1000:.1f} mm "
                     f"grip={state.grip_detected} [{request_id}]")
        except Rg6Error as exc:
            log.error(f"gripper failed: {exc}")
            _emit(result_payload(request_id, "failed", state=None,
                                 reason="not_available", detail=str(exc),
                                 elapsed_s=time.monotonic() - started))
        finally:
            inflight.release()

    def on_gripper(msg) -> None:
        try:
            cmd = tp.parse_gripper_command(msg.data)
        except ValueError as exc:
            log.warn(f"bad gripper_cmd: {exc}")
            return
        request_id = cmd["request_id"]
        if request_id in seen:
            return
        seen.add(request_id)
        if not inflight.acquire(blocking=False):
            _emit(result_payload(request_id, "failed", state=None,
                                 reason="busy",
                                 detail="ein Greifbefehl laeuft noch"))
            return
        _emit(result_payload(request_id, "started", state=None))
        # xmlrpc.client blockiert.  Im Callback wuerde ein haengender Endpoint
        # den Executor anhalten -- und mit ihm den joint_states-Publisher.
        threading.Thread(target=_work, args=(cmd,), daemon=True).start()

    node.create_subscription(String, tp.GRIPPER_CMD_TOPIC, on_gripper, 10)
    log.info(f"rg6_grip_bridge bereit: {client.url} "
             f"<- {tp.GRIPPER_CMD_TOPIC}")
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()
    return 0


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--selftest" in argv:
        return selftest()
    return run(argv)


if __name__ == "__main__":
    raise SystemExit(main())
