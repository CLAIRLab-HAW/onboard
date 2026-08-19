#!/usr/bin/env python3
"""rg6_kennlinie: Stuetzstellen fuer die AI2-Kennlinie messen (R19 Punkt 3).

Bis heute stehen ``in_closed = 0,56 V`` und ``in_open = 10,0 V`` in
rg6_joint_state_broadcaster.cpp ausdruecklich als "grobe Schaetzung, bitte
live nachjustieren" -- und es gab nie eine Referenz, gegen die man sie haette
halten koennen.  Jetzt gibt es eine: ``rg_get_width`` kommt vom Geraet selbst,
nicht aus einer zweiten Schaetzung.

Am 2026-08-17 fiel schon an EINEM Punkt auf, wie weit die Schaetzung
danebenliegt:

    AI2 5,6696 V   ->   Geraet meldet 103,26 mm
                        Kennlinie sagt  86,6 mm      = 16,6 mm Fehlbetrag

Und sie ist nicht bloss verschoben, sondern krumm: mit dem zweiten bekannten
Paar (0,6 V / ~1,3 mm) ergaebe die Gerade 20,11 mm/V und extrapolierte auf
9,697 V zu 184 mm -- bei einem Anschlag, der real bei ~151 mm liegt.  Zwei
Punkte genuegen hier also nicht, deshalb dieser Durchlauf.

Er beantwortet nebenbei R19 Punkt 2:  weicht die Weite ueber den ganzen Weg
GLEICHMAESSIG ab, sitzt der Fehler im Pad-Versatz (kPadOffsetM); erreicht die
Hand die 159 mm gar nicht, ist die Kurbel-Totlage als offene Grenze zu weit
gegriffen.

    !!! DIESES SKRIPT BEWEGT DEN GREIFER !!!

Nur mit jemandem am Geraet fahren.  Der Arm steht dabei; bewegt wird
ausschliesslich die Hand.  Am 2026-08-17 hat sich der Greifer schon einmal in
``busy: true`` festgefahren -- die Erholung (set_tool_power aus, wieder an,
dann open) braucht jemanden, der sieht, ob sie gegriffen hat.

    python3 rg6_kennlinie.py > /tmp/rg6-kennlinie.json

In eine DATEI, nicht in eine Pipe: am 2026-08-17 hat ein ``| tail -20`` das
Ergebnis eines vollstaendigen Durchgangs vernichtet, der die Hardware schon
bewegt hatte.  Eine Messung, die den Roboter anfasst, wiederholt man nicht,
weil man die Ausgabe abgeschnitten hat.

AI2 traegt der Aufrufer nach -- es kommt aus

    /a200_0553/manipulators/io_and_status_controller/tool_data

mit ``manipulators/`` im Pfad.  Der Pfad ohne dieses Segment liefert stumm
gar nichts, und das sieht wie ein totes Topic aus.
"""
from __future__ import annotations

import json
import sys
import time

from rg6_grip_bridge import Rg6Client, Rg6Error

#: Ueber den ganzen Weg, mit Verdichtung am offenen Anschlag -- dort sitzt die
#: offene Frage aus R19 Punkt 2 (Modell 159,0 mm, Messschieber ~151 mm).
WIDTHS_MM = [160.0, 151.0, 140.0, 120.0, 100.0, 80.0, 60.0, 40.0, 20.0, 0.0]
#: Der RG6 braucht sichtbar Zeit bis zum Stillstand; zu frueh gelesen misst
#: man die Fahrt, nicht den Anschlag.
SETTLE_S = 2.5
#: Klein genug, dass ein versehentlich eingelegtes Objekt nicht gequetscht
#: wird -- gemessen werden soll der Weg, nicht die Kraft.
FORCE_N = 40.0


def main() -> int:
    client = Rg6Client()
    rows = []
    for width_mm in WIDTHS_MM:
        try:
            client.grip(width_mm / 1000.0, FORCE_N)
        except Rg6Error as exc:
            rows.append({"commanded_mm": width_mm, "error": str(exc)})
            print(f"# {width_mm:6.1f} mm -> FEHLER {exc}", file=sys.stderr)
            continue
        time.sleep(SETTLE_S)
        try:
            st = client.state()
        except Rg6Error as exc:
            rows.append({"commanded_mm": width_mm, "error": str(exc)})
            continue
        rows.append({
            "commanded_mm": width_mm,
            # Wanduhr des Zustandslesens.  Ohne sie laesst sich die Zeile
            # NICHT mit der parallel mitgeschriebenen AI2-Spur verknuepfen --
            # und ohne AI2 misst der Durchlauf nur sich selbst.
            "t_read": time.time(),
            "device_width_mm": st.width_m * 1000.0,
            "busy": st.busy,
            "grip_detected": st.grip_detected,
            "status": st.status,
            "safety_failed": st.safety_failed,
            # Vom Aufrufer nachzutragen (s. Kopf) -- bewusst als Feld
            # angelegt, damit die Zeile vollstaendig ist und niemand die
            # Zuordnung spaeter raten muss.
            "analog_input2_v": None,
        })
        print(f"# {width_mm:6.1f} mm -> {st.width_m * 1000:6.2f} mm "
              f"(busy={st.busy}, grip={st.grip_detected})", file=sys.stderr)

    json.dump({"widths_mm": WIDTHS_MM, "settle_s": SETTLE_S,
               "force_n": FORCE_N, "rows": rows}, sys.stdout, indent=1)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
