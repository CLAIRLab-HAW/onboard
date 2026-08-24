#!/usr/bin/env python3
"""rg6_kennlinie: den Greiferweg Stuetzstelle fuer Stuetzstelle vermessen (R19 Punkt 2).

Die Frage, die hier noch offen ist:  das Modell setzt die offene Grenze auf
159,0 mm, der Messschieber sagt ~151 mm.  Weicht die Weite ueber den GANZEN
Weg gleichmaessig ab, sitzt der Fehler im Pad-Versatz (kPadOffsetM); erreicht
die Hand die 159 mm gar nicht, ist die Kurbel-Totlage als offene Grenze zu
weit gegriffen.  Beantwortbar nur mit einem Durchlauf ueber den ganzen Hub,
und den faehrt dieses Skript.

WOFUER ES NICHT MEHR DA IST -- die AI2-Kennlinie (das urspruengliche R19
Punkt 3).  Sie eichte ``in_closed``/``in_open`` in
``rg6_joint_state_broadcaster.cpp``, und diesen Knoten gibt es nicht mehr:
der RG6 haengt an der OnRobot-URCap, seine Weite kommt aus ``rg_get_width``.
AI2 beantwortet seitdem nur noch "liegt am Tool-Anschluss Versorgung an" und
ist als Weitenquelle ausdruecklich verworfen (bis zu 17 mm falsch geeicht).
Das Feld ``analog_input2_v`` bleibt in der Ausgabe stehen, damit sich die
ALTEN Durchlaeufe weiter gegen die neuen halten lassen -- es ist nicht mehr
nachzutragen.

    !!! DIESES SKRIPT BEWEGT DEN GREIFER !!!

Nur mit jemandem am Geraet fahren.  Der Arm steht dabei; bewegt wird
ausschliesslich die Hand.  Am 2026-08-17 hat sich der Greifer schon einmal in
``busy: true`` festgefahren.  Die damalige Erholung (``set_tool_power`` aus,
wieder an, dann open) gibt es NICHT mehr -- der Service kam aus rg6_control.
Heute fuehrt der Weg ueber die URCap: ``rg_stop``, dann ein neues Kommando;
hilft das nicht, das URCap-Programm am Teach-Panel neu starten.

    python3 rg6_kennlinie.py > /tmp/rg6-kennlinie.json

In eine DATEI, nicht in eine Pipe: am 2026-08-17 hat ein ``| tail -20`` das
Ergebnis eines vollstaendigen Durchgangs vernichtet, der die Hardware schon
bewegt hatte.  Eine Messung, die den Roboter anfasst, wiederholt man nicht,
weil man die Ausgabe abgeschnitten hat.

Fuer den Vergleich mit alten Laeufen kommt AI2 weiterhin aus

    /a200_0553/manipulators/io_and_status_controller/tool_data

mit ``manipulators/`` im Pfad.  Der Pfad ohne dieses Segment liefert stumm
gar nichts, und das sieht wie ein totes Topic aus.
"""

from __future__ import annotations

import argparse
import json
import sys
import time

from rg6_grip_bridge import Rg6Client, Rg6Error, await_settled

#: Ueber den ganzen Weg, mit Verdichtung am offenen Anschlag -- dort sitzt die
#: offene Frage aus R19 Punkt 2 (Modell 159,0 mm, Messschieber ~151 mm).
WIDTHS_MM = [160.0, 151.0, 140.0, 120.0, 100.0, 80.0, 60.0, 40.0, 20.0, 0.0]
#: Der RG6 braucht sichtbar Zeit bis zum Stillstand; zu frueh gelesen misst
#: man die Fahrt, nicht den Anschlag.  2,5 s reichen dafuer NICHT: am
#: 2026-08-19 kroch der gemeldete Wert danach noch rund 0,9 mm weiter und stand
#: erst nach Minuten (dann auf 0,18 mm ruhig).  Wer den offenen Anschlag
#: ausmessen will, nimmt --settle 30 oder mehr; 2,5 s bleibt die Vorgabe,
#: damit ein schneller Funktionslauf nicht zehn Minuten dauert.
SETTLE_S = 2.5
#: Klein genug, dass ein versehentlich eingelegtes Objekt nicht gequetscht
#: wird -- gemessen werden soll der Weg, nicht die Kraft.  Das Handbuch
#: (v6.6.2) merkt zudem an, dass die Sollkraft die Breitengenauigkeit
#: verschlechtert; fuer eine Eichung also --force 25 (das Minimum).
FORCE_N = 40.0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--settle",
        type=float,
        default=SETTLE_S,
        metavar="S",
        help="Ruhezeit je Stuetzstelle in Sekunden (Vorgabe: %(default)s)",
    )
    ap.add_argument(
        "--force",
        type=float,
        default=FORCE_N,
        metavar="N",
        help="Greifkraft in Newton, 25..120 (Vorgabe: %(default)s)",
    )
    ap.add_argument(
        "--both",
        action="store_true",
        help="nach dem absteigenden Weg denselben aufsteigend fahren "
        "-- beantwortet, ob der gemeldete Wert von der "
        "Fahrtrichtung abhaengt",
    )
    args = ap.parse_args()

    settle_s, force_n = args.settle, args.force
    widths = list(WIDTHS_MM) + (list(reversed(WIDTHS_MM)) if args.both else [])

    client = Rg6Client()
    rows = []
    for width_mm in widths:
        try:
            client.grip(width_mm / 1000.0, force_n)
        except Rg6Error as exc:
            rows.append({"commanded_mm": width_mm, "error": str(exc)})
            print(f"# {width_mm:6.1f} mm -> FEHLER {exc}", file=sys.stderr)
            continue
        # Erst das Ende der Fahrt abwarten (busy-Flanken), DANN die Ruhezeit:
        # sonst faellt bei kurzen --settle die halbe Ruhe noch in die Fahrt.
        try:
            await_settled(client)
        except Rg6Error as exc:
            rows.append({"commanded_mm": width_mm, "error": str(exc)})
            continue
        time.sleep(settle_s)
        try:
            st = client.state()
        except Rg6Error as exc:
            rows.append({"commanded_mm": width_mm, "error": str(exc)})
            continue
        rows.append(
            {
                "commanded_mm": width_mm,
                # Wanduhr des Zustandslesens -- haelt die Zeile an einen
                # Zeitpunkt, gegen den sich eine parallel mitgeschriebene Spur
                # (frueher AI2) legen laesst.
                "t_read": time.time(),
                "device_width_mm": st.width_m * 1000.0,
                "busy": st.busy,
                "grip_detected": st.grip_detected,
                "status": st.status,
                "safety_failed": st.safety_failed,
                # Bleibt als Feld stehen, damit sich alte Durchlaeufe (in denen
                # AI2 die Weitenquelle war) Zeile fuer Zeile gegen neue halten
                # lassen.  Nachzutragen ist es nicht mehr -- die Weite kommt vom
                # Geraet, s. Kopf.
                "analog_input2_v": None,
            }
        )
        print(
            f"# {width_mm:6.1f} mm -> {st.width_m * 1000:6.2f} mm "
            f"(busy={st.busy}, grip={st.grip_detected})",
            file=sys.stderr,
        )

    json.dump(
        {
            "widths_mm": widths,
            "settle_s": settle_s,
            "force_n": force_n,
            "both_directions": args.both,
            "rows": rows,
        },
        sys.stdout,
        indent=1,
    )
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
