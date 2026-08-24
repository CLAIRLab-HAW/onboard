"""Die eine Stelle, an der Mock und Roboter sich unterscheiden duerfen.

rslidar_sdk nimmt EINE yaml-Datei ueber den ROS-Parameter `config_path` und kennt keine Uebersteuerung einzelner
Schluessel.  Wer Mock und Live trotzdem aus einer Quelle fahren will, muss die Datei also rendern statt sie zu
duplizieren -- zwei gepflegte yaml-Dateien waeren die Driftquelle, die dieses Vorhaben gerade vermeiden will.

ROS-frei und damit auf dem Mac testbar.
"""

from __future__ import annotations

from pathlib import Path

import yaml

#: Werte von common.msg_source.  Die Reihenfolge der Protokollzeilen im
#: Binary lautet "Online LiDAR", "ROS", "Pcap" -- also 1, 2, 3.  Verifiziert
#: wird das an der Startzeile des laufenden Knotens, nicht hier.
MSG_SOURCE_ONLINE = 1
MSG_SOURCE_ROS = 2
MSG_SOURCE_PCAP = 3

#: Wie oft die Aufnahme im Verhaeltnis zur Echtzeit abgespielt wird.
#: 1 = Echtzeit.  Schneller waere fuer Nav2 wertlos: die Costmap rechnet in
#: Sekunden, nicht in Frames.
PCAP_RATE = 1

TEMPLATE_PATH = Path(__file__).resolve().parents[2] / "config" / "rslidar_rs16.yaml"


def render(template: dict, *, pcap_path: str | None = None) -> dict:
    """Setzt die Paketquelle in eine geladene Vorlage.

    ``pcap_path=None`` -> das Geraet.  Sonst -> die Aufnahme. Die Vorlage wird veraendert und zurueckgegeben (der
    Aufrufer uebergibt ohnehin ein frisch geladenes Dict).
    """
    if "common" not in template:
        raise ValueError(
            "Vorlage ohne 'common'-Abschnitt -- rslidar_sdk findet dort "
            "msg_source und wuerde ohne jede Meldung gar nichts empfangen."
        )
    if not template.get("lidar"):
        raise ValueError(
            "Vorlage ohne 'lidar'-Abschnitt -- ohne ihn kennt der Treiber " "weder Geraetetyp noch Zielframe."
        )

    driver = template["lidar"][0].setdefault("driver", {})

    if pcap_path is None:
        template["common"]["msg_source"] = MSG_SOURCE_ONLINE
        for key in ("pcap_path", "pcap_repeat", "pcap_rate"):
            driver.pop(key, None)
    else:
        template["common"]["msg_source"] = MSG_SOURCE_PCAP
        driver["pcap_path"] = pcap_path
        driver["pcap_repeat"] = True
        driver["pcap_rate"] = PCAP_RATE

    return template


def write_resolved(out_path: str | Path, *, pcap_path: str | None = None) -> Path:
    """Rendert die Vorlage und schreibt sie -- der Pfad geht an `config_path`."""
    template = yaml.safe_load(TEMPLATE_PATH.read_text(encoding="utf-8"))
    resolved = render(template, pcap_path=pcap_path)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(yaml.safe_dump(resolved, sort_keys=False), encoding="utf-8")
    return out
