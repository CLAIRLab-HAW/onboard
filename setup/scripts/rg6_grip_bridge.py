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
            return getattr(self._proxy, method)(*args)
        except xmlrpc.client.Fault as exc:
            raise Rg6Error(f"{method}: Fault {exc.faultCode} "
                           f"{exc.faultString}") from exc
        except OSError as exc:
            raise Rg6Error(f"{method}: {self._url} nicht erreichbar "
                           f"({exc})") from exc


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
    state = {"width_mm": 103.26, "busy": False, "grip": False}

    def rg_grip(tool, width, force):
        if not isinstance(width, float) or not isinstance(force, float):
            raise xmlrpc.client.Fault(-501, "expected double")
        log.append(("grip", tool, width, force))
        state["width_mm"] = width
        return 0

    def rg_stop(tool):
        log.append(("stop", tool))
        return 0

    srv = SimpleXMLRPCServer(("127.0.0.1", 0), logRequests=False,
                             allow_none=True)
    srv.register_function(rg_grip, "rg_grip")
    srv.register_function(rg_stop, "rg_stop")
    srv.register_function(lambda t: state["width_mm"], "rg_get_width")
    srv.register_function(lambda t: state["busy"], "rg_get_busy")
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
        cli.grip(0.100, 60.0)
        assert log[-1][2] == 100.0, log[-1]
        assert abs(cli.state().width_m - 0.100) < 1e-9, cli.state()

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
    finally:
        srv.shutdown()

    print("rg6_grip_bridge selftest: OK (Einheiten, float-Zwang, Klemmung, "
          "Timeout, Draht-Vertrag)")
    return 0


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--selftest" in argv:
        return selftest()
    # 'run' definiert Task 3 in dieser Datei.  Der Aufruf steht schon hier,
    # damit --selftest von Anfang an der einzige Weg ohne ROS ist.
    return run(argv)                                   # noqa: F821


if __name__ == "__main__":
    raise SystemExit(main())
