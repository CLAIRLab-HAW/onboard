#!/usr/bin/env python3
"""rg6_grip_bridge: kommandiert den RG6 per XML-RPC an die OnRobot-URCap.

Warum nicht mehr ueber rg6_control (Tool-DO0):  die URCap ist selbst
RTDE-Client und belegt ``tool_digital_output_mask``.  Damit der
ur_robot_driver ueberhaupt startet, laeuft er auf einem Input-Recipe OHNE die
tool_digital_output*-Zeilen -- ROS kann seitdem kein Tool-DO mehr setzen, und
rg6_control steuerte den Greifer ausschliesslich darueber.  Der Treiber ist
damit tot, nicht kaputt.

Warum nicht per URScript ueber Port 30002:  ``rg_grip`` legt erst das
Installations-Preamble an, das PolyScope vor jedes generierte Programm setzt.
Ein ueber 30002 gesendetes Skript laeuft ohne den Preamble, das Symbol wird
verworfen (gemessen: kein Programmwechsel, AI2 unveraendert,
``textmsg("literal")`` als Kontrolle durch).

Warum onboard und nicht im Offboard-Container:  der Endpoint haengt am
Arm-Subnetz 192.168.131.0/24, und von der Workstation gibt es dorthin keine
Route.  Und der Roboter muss greifen koennen, auch wenn die Funkstrecke weg
ist -- dasselbe Argument, mit dem R16 die Reflexschicht onboard verortet.

Der Endpoint bietet mehr als ``rg_grip``: einen vollstaendigen Status-Rueckweg
(``rg_get_width``, ``rg_get_busy``, ``rg_get_grip_detected``,
``rg_get_status``, ``rg_get_safety_failed``).  Die Spannungsnaeherung ueber AI2
wird dadurch ueberfluessig -- und AI2 ist als um ~17 mm falsch geeicht
aufgefallen, gemessen gegen genau diese Getter.

Was dieser Node NICHT tut:  er spricht das ``/twin/*``-JSON-Protokoll nicht.
Das tut ``plan_server`` im Offboard-Container, und zwar auf ``mock`` und
``real`` gleich -- ein Codepfad statt zweier.  Hier gibt es ausschliesslich
Standard-ROS-Schnittstellen::

    control_msgs/GripperCommand  (Action)   <- MoveIt und plan_server
    sensor_msgs/JointState       (Topic)    -> rg6_finger_joint
    std_msgs/String              (Topic)    -> rg6/bridge_state, eigenes JSON

Damit braucht der Roboter ``robot_contract`` NICHT.  Das Paket ist privat (vom
Roboter aus nicht einmal klonbar), und der Installer hat die Bruecke deshalb
kommentarlos uebersprungen -- eine Abhaengigkeit, die das Deployment
verhindert, ist keine Absicherung.  Geblieben sind Namen (ROS-Parameter) und
die Getriebekinematik (erzeugte Tabelle, s. FingerKinematics).

Selbsttest ohne ROS (laeuft auch auf der Workstation)::

    python3 rg6_grip_bridge.py --selftest
"""

from __future__ import annotations

import json
import pathlib
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

    @property
    def readable(self) -> bool:
        """Hat die URCap tatsaechlich GEMESSEN -- oder nur geantwortet?

        Der Endpoint sitzt in der Control-Box und ist auch dann erreichbar,
        wenn am Tool-Anschluss nichts anliegt.  Er wirft dann KEINEN Fault,
        sondern antwortet mit seinem eigenen Kennzeichen fuer "keine Messung":

            rg_get_width -> -999.0    rg_get_status -> -1
            rg_get_busy  -> True      rg_get_safety_failed -> True

        Am 2026-08-24 am a200-0553 direkt am Endpoint abgefragt, waehrend der
        Arm auf POWER_OFF stand.  Ohne diese Pruefung geht -999 mm durch
        ``angle_from_width`` (das die WEITE klemmt, statt zu extrapolieren)
        und kommt als 1,25478 rad heraus -- ein VOLLSTAENDIG GESCHLOSSENER
        Greifer, veroeffentlicht als Messwert.  Genau das war live zu sehen:
        rg6_finger_joint = 1,25478 auf platform/joint_states, also in RSP,
        TF und der Planungsszene von move_group, bei stromlosem Greifer.

        Der stillgelegte rg6_control hatte dagegen eine Sperre -- die
        Totschwelle auf AI2/AI3 (``dead_input_threshold``).  Sie ist mit ihm
        weggefallen, ohne dass hier etwas an ihre Stelle getreten waere: die
        Bruecke verlaesst sich darauf, dass ein toter Greifer eine EXCEPTION
        wirft.  Er wirft keine.
        """
        lo_mm, hi_mm = WIDTH_RANGE_MM
        return self.status >= 0 and lo_mm <= self.width_m * 1000.0 <= hi_mm


def _clamp(value: float, lo: float, hi: float) -> float:
    return min(max(float(value), lo), hi)


class Rg6Client:
    """XML-RPC-Schnittstelle zur OnRobot-URCap.

    Die EINZIGE Stelle, an der Einheiten gewechselt werden: das Profil und der
    ``/twin/*``-Draht rechnen in Metern, der Endpoint in Millimetern.
    """

    def __init__(
        self, url: str = DEFAULT_URL, tool_index: int = 0, timeout_s: float = 3.0
    ) -> None:
        self._url = url
        self._tool = int(tool_index)
        # Harter Timeout: ohne ihn haelt ein toter Endpoint den Worker-Thread
        # unbegrenzt, und mit ihm den joint_states-Publisher.
        transport = xmlrpc.client.Transport()
        transport.timeout = float(timeout_s)
        self._proxy = xmlrpc.client.ServerProxy(
            url, transport=transport, allow_none=True
        )
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
            raise Rg6Error(
                f"rg_grip({width_mm:.1f} mm, {force:.1f} N) "
                f"antwortete {rc!r} statt 0"
            )

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
            raise Rg6Error(
                f"{method}: Fault {exc.faultCode} " f"{exc.faultString}"
            ) from exc
        except OSError as exc:
            raise Rg6Error(
                f"{method}: {self._url} nicht erreichbar " f"({exc})"
            ) from exc


def await_settled(
    client,
    start_timeout_s: float = 1.0,
    motion_timeout_s: float = 10.0,
    poll_s: float = 0.05,
) -> Rg6State:
    """Warten, bis die Hand steht, und DANN den Zustand lesen.

    ``rg_grip`` quittiert die **Annahme**, nicht das Ergebnis.  Wer sofort
    danach liest, bekommt die Weite von vorher -- ueber den Draht gemessen:
    kommandierte 60 mm, gefahren auf 64,96 mm, gemeldete 2,8 mm (der
    Startwert).  Mit ``width_m`` war auch ``grasped`` wertlos, und das ist das
    Feld, wegen dem der ganze Rueckweg existiert.

    Gewartet wird auf **beide** Flanken, und der Grund fuer die erste ist
    gemessen: nach dem Kommando steht ``busy`` noch rund 0,4 s auf false,
    bevor der Greifer losfaehrt.  Ein blosses "warte, solange busy" kehrte in
    dieser Luecke sofort zurueck -- derselbe Fehler in neuem Gewand.

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


class FingerKinematics:
    """Gelenkwinkel <-> Greifweite, aus einer erzeugten Tabelle.

    Warum eine Tabelle und kein Import:  dieser Node laeuft auf dem ROBOTER
    und soll dort nichts brauchen, was nicht zum Roboter gehoert.  Ein Import
    aus ``robot_contract`` scheiterte daran, dass das Paket privat ist und der
    Installer die Bruecke deshalb kommentarlos uebersprang.

    Warum eine Tabelle und keine Formel:  die Finger des rg6_v2 sind eine
    Viergelenkkette ohne geschlossene Form.  Eine danebengestellte Naeherung
    waere die Zweitfassung, an der Modell und Treiber schon einmal
    auseinandergelaufen sind (R19).

    Die Datei erzeugt ``tools/derive_finger_kinematics.py`` aus dem
    GENERIERTEN URDF; sie ist Daten, kein Code, und traegt ihre Herkunft im
    Kopf.  27 Stuetzstellen halten den Interpolationsfehler bei 0,047 mm --
    unter der Fingerpositionsaufloesung des RG6 (0,1 mm laut Datenblatt).
    """

    def __init__(self, path: str) -> None:
        with open(path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
        tab = raw["table_q_rad_width_m"]
        self._q = [float(z[0]) for z in tab]
        self._w = [float(z[1]) for z in tab]
        if sorted(self._q) != self._q:
            raise ValueError(f"{path}: Stuetzstellen nicht aufsteigend in q")
        # Die Weite MUSS fallen: darauf beruht die Umkehrung.  Steigt sie
        # irgendwo, sind Stuetzstellen jenseits des Nulldurchgangs erwischt
        # worden, wo die Finger im Modell durcheinander hindurchfahren.
        if any(b >= a for a, b in zip(self._w, self._w[1:])):
            raise ValueError(f"{path}: Weite faellt nicht monoton")
        self.joint = str(raw.get("joint", "rg6_finger_joint"))
        self.q_min, self.q_max = self._q[0], self._q[-1]
        self.max_width_m, self.min_width_m = self._w[0], self._w[-1]
        self.source = path

    def width_from_angle(self, q: float) -> float:
        """Geklemmt auf den Tabellenrand: jenseits des Anschlags gilt der Anschlag."""
        q = min(max(float(q), self.q_min), self.q_max)
        for i in range(1, len(self._q)):
            if q <= self._q[i]:
                t = (q - self._q[i - 1]) / (self._q[i] - self._q[i - 1])
                return self._w[i - 1] + t * (self._w[i] - self._w[i - 1])
        return self._w[-1]

    def angle_from_width(self, width_m: float) -> float:
        """Umkehrung, ebenfalls geklemmt.  Die Tabelle faellt, also rueckwaerts."""
        w = min(max(float(width_m), self.min_width_m), self.max_width_m)
        for i in range(1, len(self._w)):
            if w >= self._w[i]:
                t = (self._w[i - 1] - w) / (self._w[i - 1] - self._w[i])
                return self._q[i - 1] + t * (self._q[i] - self._q[i - 1])
        return self._q[-1]


#: Was zuletzt an den Greifer ging.  Bewusst dieselben Namen wie in
#: rg6_msgs/GripperState.COMMAND_* -- die Manipulator-Diagnose zeigt sie an,
#: und ein Namenswechsel haette dort nur den Klartext kaputtgemacht.
COMMAND_NONE = "NONE"
COMMAND_GRIP = "GRIP"
COMMAND_STOP = "STOP"


def goal_to_grip(
    position_rad: float,
    max_effort_n: float,
    linkage,
    default_force_n: float,
    force_range_n,
) -> tuple:
    """``control_msgs/GripperCommand``-Ziel -> ``(Weite in m, Kraft in N)``.

    MoveIt kommandiert den Greifer als GELENKWERT, nicht als Weite -- die
    Umrechnung macht dieselbe Getriebegeometrie, die auch das URDF traegt.

    ``max_effort <= 0`` heisst im Vertrag von GripperCommand "nimm, was
    passt", nicht "Kraft null": MoveIt laesst das Feld haeufig leer.  Dann
    gilt die Profilvorgabe.  Geklemmt wird auf den Geraetebereich, damit ein
    zu grosser Wunsch als das ankommt, was der RG6 kann.
    """
    lo, hi = float(force_range_n[0]), float(force_range_n[1])
    force = (
        float(default_force_n)
        if max_effort_n is None or max_effort_n <= 0.0
        else min(max(float(max_effort_n), lo), hi)
    )
    return float(linkage.width_from_angle(float(position_rad))), force


def goal_result(
    state, target_width_m: float, force_n: float, linkage, tolerance_m: float
) -> dict:
    """Ergebnisfelder fuer GripperCommand, aus dem GEMESSENEN Zustand.

    ``stalled`` ist ``grip_detected``:  der RG6 meldet damit, dass er die
    Kraftgrenze VOR der Zielweite erreicht hat -- also genau "steht, aber
    nicht am Ziel", was das Feld bedeutet.

    ``effort`` ist die KOMMANDIERTE Kraft, nicht eine gemessene: der Endpoint
    bietet keinen Kraftrueckgabewert.  Eine erfundene Zahl waere schlimmer als
    eine ehrliche Wiederholung des Sollwerts.

    ``tolerance_m`` ist bewusst grob:  der Rueckgabewert des Geraets liegt um
    +3 bis +5 mm ueber der wahren Weite (R19, mit dem Messschieber
    verankert).  Solange diese Abweichung nicht herausgerechnet wird, kann
    ``reached_goal`` nicht schaerfer sein als dieser Fehler.
    """
    return {
        "position": float(linkage.angle_from_width(state.width_m)),
        "effort": float(force_n),
        "stalled": bool(state.grip_detected),
        "reached_goal": abs(state.width_m - float(target_width_m))
        <= float(tolerance_m),
    }


def status_payload(state, last_command: str = COMMAND_NONE) -> dict:
    """Geraetezustand fuer ``<ns>/rg6/bridge_state`` -- flach, als JSON.

    Warum ein eigenes Topic und nicht rg6_msgs/GripperState:  rg6_msgs liegt
    nicht im Bootpfad des Roboters, und ein Statustopf, der ein Paket von dort
    braucht, waere genau die Abhaengigkeit, die hier abgebaut wird.  JSON in
    einem std_msgs/String kostet keinen Build und kein Overlay.

    NICHT enthalten sind AI2/AI3:  die Rohspannungen stehen auf
    ``io_and_status_controller/tool_data``, und wer sie braucht, liest sie
    dort.  Sie hier zu spiegeln hiesse, eine zweite Quelle fuer dieselbe Zahl
    zu schaffen -- und AI2 ist als um bis zu 17 mm falsch geeicht gemessen
    worden (R19), also gerade keine gute Zweitmeinung.
    """
    return {
        "width_m": state.width_m,
        "busy": state.busy,
        "grip_detected": state.grip_detected,
        "status": state.status,
        "safety_failed": state.safety_failed,
        "last_command": last_command,
    }


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
    state = {
        "width_mm": 103.26,
        "busy": False,
        "grip": False,
        "target_mm": 103.26,
        "phasen": [],
    }

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
            state["width_mm"] = state["target_mm"]  # Fahrt zu Ende
        return phase == "faehrt"

    def rg_stop(tool):
        log.append(("stop", tool))
        return 0

    srv = SimpleXMLRPCServer(("127.0.0.1", 0), logRequests=False, allow_none=True)
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
        else:  # pragma: no cover
            raise AssertionError("toter Endpoint haette Rg6Error geben muessen")

        # 5a. Ein Ergebnis, das SOFORT nach rg_grip gelesen wird, meldet die
        #     Weite von VORHER.  Am 2026-08-19 ueber den Draht gemessen:
        #     kommandierte 60 mm, gefahren auf 64,96 mm, gemeldet 2,8 mm --
        #     der Startwert.  ``rg_grip`` quittiert die Annahme, nicht das
        #     Ergebnis, und mit ``width_m`` waere auch ``grasped`` wertlos.
        cli.grip(0.020, 40.0)
        assert (
            abs(cli.state().width_m - 0.020) > 0.001
        ), "zu frueh gelesen -> alter Wert"

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

        # 5c. Der MoveIt-Weg: GripperCommand kommandiert einen GELENKWERT.
        #     MoveIt braucht den Greifer nie am controller_manager -- es
        #     braucht diese Action, und die laeuft in einem normalen Executor,
        #     nicht im 8-ms-Zyklus des CB3.  Genau deshalb konnte der
        #     stillgelegte rg6_control sie anbieten, ohne ein
        #     Hardware-Interface zu sein.
        kin = FingerKinematics(
            str(pathlib.Path(__file__).with_name("rg6_finger_kinematics.json"))
        )
        width, force = goal_to_grip(
            kin.angle_from_width(0.100), 55.0, kin, 40.0, (25.0, 120.0)
        )
        assert abs(width - 0.100) < 2e-4, width  # Tabellenaufloesung
        assert force == 55.0, force
        # Leeres max_effort heisst "nimm, was passt" -- nicht "Kraft null".
        assert goal_to_grip(0.0, 0.0, kin, 40.0, (25.0, 120.0))[1] == 40.0
        # ... und ein zu grosser Wunsch wird geklemmt, nicht durchgereicht.
        assert goal_to_grip(0.0, 999.0, kin, 40.0, (25.0, 120.0))[1] == 120.0

        st_closed = Rg6State(
            width_m=0.0605,
            busy=False,
            grip_detected=True,
            status=0,
            safety_failed=False,
        )
        res = goal_result(st_closed, 0.060, 40.0, kin, tolerance_m=0.008)
        assert res["reached_goal"] is True and res["stalled"] is True, res
        assert res["effort"] == 40.0, res
        # Weit daneben ist weit daneben, auch wenn der Greifer steht.
        assert (
            goal_result(st_closed, 0.100, 40.0, kin, tolerance_m=0.008)["reached_goal"]
            is False
        )

        # 5b. Der Statustopf traegt den GERAETEZUSTAND, nicht den Befehl --
        #     genau das bewertet die Manipulator-Diagnose.
        st = Rg6State(
            width_m=0.1032,
            busy=False,
            grip_detected=True,
            status=0,
            safety_failed=False,
        )
        status = status_payload(st, COMMAND_GRIP)
        assert status["width_m"] == st.width_m, status
        assert status["grip_detected"] is True, status
        assert status["last_command"] == COMMAND_GRIP, status
        # Er muss durch json.dumps passen -- er geht als String auf den Draht.
        assert json.loads(json.dumps(status)) == status, status
        # AI2/AI3 gehoeren NICHT hinein (s. Docstring): eine zweite Quelle
        # fuer dieselbe Zahl, und die schlechtere.
        assert "width_raw" not in status and "force_raw" not in status, status

        # 5c. Eine ANTWORT ist noch keine MESSUNG (Rg6State.readable).
        #     Die Werte sind die am 2026-08-24 am a200-0553 gelesenen, mit
        #     dem Arm auf POWER_OFF.
        assert st.readable, "eine echte Messung muss durchgehen"
        dead = Rg6State(
            width_m=-0.999, busy=True, grip_detected=True, status=-1, safety_failed=True
        )
        assert not dead.readable, "-999 mm / status -1 ist keine Messung"
        # Ohne die Sperre wuerde daraus ein VOLLSTAENDIG GESCHLOSSENER Greifer
        # -- die Klemmung extrapoliert nicht, sie rastet am Anschlag ein.
        assert abs(kin.angle_from_width(dead.width_m) - kin.q_max) < 1e-9
        # Beide Haelften der Pruefung greifen fuer sich: ein Fehlerstatus
        # allein reicht, und eine Weite jenseits des Nennbereichs auch.
        assert not Rg6State(
            width_m=0.060,
            busy=False,
            grip_detected=False,
            status=-1,
            safety_failed=False,
        ).readable
        assert not Rg6State(
            width_m=0.400,
            busy=False,
            grip_detected=False,
            status=0,
            safety_failed=False,
        ).readable
        # Die Nenngrenzen selbst sind noch gueltig -- das Geraet meldet bis zu
        # 5 mm ueber dem Backenmass (R19), das darf nicht als tot gelten.
        assert Rg6State(
            width_m=0.160,
            busy=False,
            grip_detected=False,
            status=0,
            safety_failed=False,
        ).readable
        assert Rg6State(
            width_m=0.0, busy=False, grip_detected=False, status=0, safety_failed=False
        ).readable

        # 6. Weite -> Fingergelenk kommt aus der ERZEUGTEN Tabelle, nicht
        #    aus einer Formel und nicht aus robot_contract (R19; der Roboter
        #    soll den privaten Vertrag nicht brauchen).
        # Monoton: weiter offen -> KLEINERER Gelenkwert (0 = ganz offen).
        assert kin.angle_from_width(0.100) < kin.angle_from_width(0.045)
        # Hin und zurueck trifft sich selbst, im Rahmen der Tabellenaufloesung.
        # min_width_m statt 0.0: das Modell schliesst nur bis 0,4 mm, dort
        # beruehren sich die Pads.  Eine Rundreise ueber 0,0 pruefte das
        # Klemmen, nicht die Interpolation.
        for w in (kin.min_width_m, 0.020, 0.060, 0.100, kin.max_width_m):
            assert abs(kin.width_from_angle(kin.angle_from_width(w)) - w) < 2e-4, w
        # Geklemmt wird die WEITE, nicht extrapoliert: jenseits des Anschlags
        # gilt der Anschlag, sonst laege eine negative Weite still hinter der
        # geschlossenen Stellung.
        assert kin.angle_from_width(-0.05) == kin.angle_from_width(kin.min_width_m)
        assert kin.angle_from_width(0.300) == kin.angle_from_width(kin.max_width_m)
        # Die Tabelle endet VOR dem Punkt, an dem die Finger im Modell
        # durcheinander fahren -- sonst waere die Umkehrung nicht eindeutig.
        assert kin.q_max < 1.30, kin.q_max
        assert kin.max_width_m > 0.15 and kin.min_width_m < 0.002

        # 7. Zwei Threads auf EINER ServerProxy -- im Node sind das der
        #    Greif-Worker und der Fingergelenk-Poller.  Ohne die Sperre in
        #    _call verschraenken sich ihre Requests auf dem gemeinsamen
        #    Socket; das aeussert sich als ResponseNotReady/BadStatusLine.
        errors = []

        def _hammer():
            try:
                for _ in range(25):
                    cli.state()
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=_hammer) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert not errors, errors
    finally:
        srv.shutdown()

    print(
        "rg6_grip_bridge selftest: OK (Einheiten, float-Zwang, Klemmung, "
        "Timeout, Statustopf, Getriebetabelle, Nebenlaeufigkeit)"
    )
    return 0


# ---------------------------------------------------------------------------
# ROS-Node -- rclpy wird ERST HIER importiert, damit --selftest auch auf der
# Workstation laeuft, wo kein rclpy liegt.
# ---------------------------------------------------------------------------
def run(argv) -> int:
    import rclpy
    from rclpy.node import Node
    from std_msgs.msg import String

    rclpy.init(args=argv)
    node = Node("rg6_grip_bridge")
    log = node.get_logger()

    node.declare_parameter("endpoint_url", DEFAULT_URL)
    node.declare_parameter("tool_index", 0)
    node.declare_parameter("timeout_s", 3.0)
    # Namen und Grenzen als PARAMETER, nicht aus einem Profil: sie sind das
    # Einzige, was dieser Node ueber seine Umgebung wissen muss, und dafuer
    # ein privates Python-Paket auf den Roboter zu legen war der Grund, warum
    # der Installer die Bruecke ueberhaupt nicht installieren konnte.
    node.declare_parameter("manipulators_ns", "/a200_0553/manipulators")
    node.declare_parameter("driver_joint", "rg6_finger_joint")
    node.declare_parameter("action_name", "")  # leer = aus manipulators_ns
    node.declare_parameter("default_force_n", 40.0)
    node.declare_parameter("force_range_n", [25.0, 120.0])
    node.declare_parameter("kinematics_file", "")  # leer = neben dem Skript
    # Warten auf das Ende der Fahrt (s. await_settled).  Als Parameter, weil
    # die Zahlen aus einer Messung an EINEM Greifer stammen: 0,4 s Anlauf,
    # 1,2 s Fahrt ueber 45 mm.  1,0 s Anlauffenster ist zugleich die
    # Wartezeit fuer ein Kommando, das gar nichts zu tun hat.
    node.declare_parameter("settle_start_timeout_s", 1.0)
    node.declare_parameter("settle_motion_timeout_s", 10.0)
    node.declare_parameter("settle_poll_s", 0.05)

    def _p(name):
        return node.get_parameter(name).value

    client = Rg6Client(
        _p("endpoint_url"), int(_p("tool_index")), float(_p("timeout_s"))
    )

    kin_file = _p("kinematics_file") or str(
        pathlib.Path(__file__).with_name("rg6_finger_kinematics.json")
    )
    linkage = FingerKinematics(kin_file)
    log.info(
        f"Getriebetabelle: {kin_file} "
        f"({linkage.max_width_m * 1000:.1f} mm offen, "
        f"q bis {linkage.q_max:.5f} rad)"
    )

    # -- Fingergelenk ------------------------------------------------------
    # Seit rg6-bringup tot ist, fehlt rg6_finger_joint in /joint_states (am
    # 2026-08-17 gemessen).  move_group sieht den Greifer seitdem in seiner
    # DEFAULT-Stellung, und jede Freiraumpruefung um die Hand rechnet gegen
    # eine Stellung, die er nicht hat -- dieselbe Klasse wie R15, nur
    # beweglich.  Dieser Node hat die gemessene Weite ohnehin.
    from sensor_msgs.msg import JointState

    node.declare_parameter("joint_state_rate_hz", 5.0)
    manip_ns = str(_p("manipulators_ns")).rstrip("/")
    finger_joint = str(_p("driver_joint"))
    joints = node.create_publisher(
        JointState, f"{manip_ns}/endeffectors/joint_states", 10
    )
    # Derselbe Poll traegt den Zustand fuer die Manipulator-Diagnose.  Sie
    # liest ihn hier -- <ns>/rg6/state hat keinen Publisher.
    states = node.create_publisher(String, f"{manip_ns}/rg6/bridge_state", 10)
    last_command = [COMMAND_NONE]

    def _poll_joint() -> None:
        """Den Fingerwert aus der GEMESSENEN Weite, nicht aus dem Befehl.

        Eigener Thread und KEIN ROS-Timer:  ``client.state()`` ist ein
        blockierender XML-RPC-Aufruf.  Im Timer-Callback haenge er am Executor
        -- bei totem Endpoint 3 s alle 200 ms, und der Greifbefehl kaeme in
        derselben Zeit nicht durch.  Derselbe Grund, aus dem schon ``_work``
        ausgelagert ist.

        Die Umrechnung Weite -> Gelenk macht die Getriebegeometrie des Profils
        (R19), nicht dieser Node.
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
            # Dieselbe Regel, nur fuer den Fall, in dem der Endpoint ANTWORTET,
            # ohne gemessen zu haben (state.readable, s. dort).  -999 mm laeuft
            # sonst durch die Klemmung und wird zu einem geschlossenen Greifer
            # -- eine Zahl, die move_group fuer bare Muenze nimmt.
            #
            # Der Zustandstopf geht WEITER raus, das Gelenk nicht: die
            # Rohantwort (status -1, safety_failed) ist genau das, was die
            # Manipulator-Diagnose braucht, um den Ausfall zu melden.  Waere
            # auch er still, sae die Diagnose nur ein Altern und koennte
            # "Bruecke tot" nicht von "Greifer stromlos" unterscheiden.
            states.publish(
                String(data=json.dumps(status_payload(state, last_command[0])))
            )
            if not state.readable:
                time.sleep(period)
                continue
            msg = JointState()
            msg.header.stamp = node.get_clock().now().to_msg()
            msg.name = [finger_joint]
            msg.position = [float(linkage.angle_from_width(state.width_m))]
            joints.publish(msg)
            time.sleep(period)

    threading.Thread(target=_poll_joint, daemon=True).start()

    # EIN Befehl je Zeit.  Ein zweiter waehrend der Fahrt wird ABGELEHNT, nicht
    # eingereiht: am 2026-08-17 haben zehn aufeinandergestapelte Goals den
    # alten Treiber in busy=true mit width_raw am Anschlag festgefahren.
    inflight = threading.Lock()

    # -- MoveIt ------------------------------------------------------------
    # Zweiter Eingang zum selben Geraet: die GripperCommand-Action.  Ohne sie
    # zeigt der Controller-Eintrag in moveit.yaml auf nichts, und ein
    # Greifbefehl aus RViz oder MoveGroupInterface laeuft auf `real` in einen
    # Timeout statt in ein "kann ich nicht".  Im Mock bedient rg6_control_sim
    # denselben Namen -- die Bruecke laeuft nur onboard, also gibt es nie zwei
    # Server.
    #
    # Der Greifer haengt dabei NICHT am controller_manager: eine Action laeuft
    # im Executor, nicht im 8-ms-Zyklus des CB3.  Ein blockierender
    # XML-RPC-Aufruf (gemessen 1,33 s bis zum Stillstand) waere dort das Ende
    # jeder Armregelung.
    from control_msgs.action import GripperCommand
    from rclpy.action import ActionServer
    from rclpy.callback_groups import ReentrantCallbackGroup

    node.declare_parameter("goal_tolerance_m", 0.008)

    def on_action(goal_handle):
        cmd = goal_handle.request.command
        width_m, force_n = goal_to_grip(
            cmd.position,
            cmd.max_effort,
            linkage,
            _p("default_force_n"),
            _p("force_range_n"),
        )
        result = GripperCommand.Result()
        if not inflight.acquire(blocking=False):
            log.warn("GripperCommand abgelehnt: ein Greifbefehl laeuft noch")
            goal_handle.abort()
            return result
        try:
            last_command[0] = COMMAND_GRIP
            client.grip(width_m, force_n)
            state = await_settled(
                client,
                float(_p("settle_start_timeout_s")),
                float(_p("settle_motion_timeout_s")),
                float(_p("settle_poll_s")),
            )
        except Rg6Error as exc:
            log.error(f"GripperCommand fehlgeschlagen: {exc}")
            goal_handle.abort()
            return result
        finally:
            inflight.release()
        fields = goal_result(
            state, width_m, force_n, linkage, float(_p("goal_tolerance_m"))
        )
        result.position = fields["position"]
        result.effort = fields["effort"]
        result.stalled = fields["stalled"]
        result.reached_goal = fields["reached_goal"]
        log.info(
            f"GripperCommand {width_m * 1000:.0f} mm @ {force_n:.0f} N -> "
            f"{state.width_m * 1000:.1f} mm "
            f"reached={result.reached_goal} stalled={result.stalled}"
        )
        goal_handle.succeed()
        return result

    action_name = str(
        _p("action_name") or f"{manip_ns}/rg6_gripper_controller/gripper_cmd"
    )
    ActionServer(
        node,
        GripperCommand,
        action_name,
        on_action,
        callback_group=ReentrantCallbackGroup(),
    )

    log.info(f"rg6_grip_bridge bereit: {client.url} <- {action_name}")
    # MultiThreaded, weil on_action bis zum Stillstand der Hand blockiert (rund
    # 1,3 s).  Single-threaded haette dieser eine Aufruf in derselben Zeit
    # /twin/gripper_cmd und jede weitere Zustellung angehalten.
    from rclpy.executors import MultiThreadedExecutor

    executor = MultiThreadedExecutor(num_threads=3)
    executor.add_node(node)
    try:
        executor.spin()
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
