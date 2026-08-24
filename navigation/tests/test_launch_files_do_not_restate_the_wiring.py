"""Launch-Dateien duerfen die Verdrahtung nicht ein zweites Mal formulieren.

Auf dem Mac ist launch_ros nicht installiert -- eine Launch-Datei laesst sich
hier also nicht importieren und ihr Inhalt nicht pruefen.  Was pruefbar
bleibt, ist die Herkunft: steht ein Topicname als Zeichenkette IN der
Launch-Datei, ist er dort ein zweites Mal formuliert und kann von der
geprueften Fassung wegdriften, ohne dass ein Test es merkt.

Dieselbe Lehre wie bei scripts/guard und scripts/mock -- ein Kommentar
"bei Aenderungen mitziehen" ist kein Mechanismus.
"""

from pathlib import Path

import pytest

LAUNCH_DIR = Path(__file__).resolve().parents[1] / "launch"

#: Werte, die genau einmal dastehen duerfen: in husky_navigation.wiring.
WIRED_LITERALS = ("/a200_0553/sensors/lidar3d_0/points", "/a200_0553/sensors/lidar3d_0/scan", "lidar3d_0_laser")


@pytest.mark.parametrize("launch_file", sorted(LAUNCH_DIR.glob("*.launch.py")), ids=lambda p: p.name)
def test_the_launch_file_imports_the_wiring(launch_file):
    text = launch_file.read_text(encoding="utf-8")
    assert "husky_navigation" in text, (
        f"{launch_file.name} importiert husky_navigation nicht -- die " f"Verdrahtung steht dort dann ein zweites Mal."
    )


@pytest.mark.parametrize("launch_file", sorted(LAUNCH_DIR.glob("*.launch.py")), ids=lambda p: p.name)
def test_the_launch_file_restates_no_wired_literal(launch_file):
    text = launch_file.read_text(encoding="utf-8")
    restated = [lit for lit in WIRED_LITERALS if lit in text]
    assert not restated, (
        f"{launch_file.name} formuliert {restated} selbst. Diese Werte "
        f"gehoeren nach husky_navigation.wiring -- die Launch-Datei ruft sie "
        f"ab, statt sie zu spiegeln."
    )
