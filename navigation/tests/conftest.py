"""Nur EIN Test darf den Roboter zur Zeit fahren.

Der Root-Lauf verteilt mit ``-n 4 --dist loadfile`` auf mehrere Prozesse, und ``loadfile`` gruppiert nach DATEI --
test_platform_mock_e2e.py und test_navigation_e2e.py landen also auf verschiedenen Workern und fahren gleichzeitig los.
Beide kommandieren dieselbe Basis und lesen dieselbe Odometrie.

Am 2026-08-22 gemessen: beide meldeten exakt dieselben Werte (3,878 -> 4,058) und beide schlugen fehl.  Jeder hatte die
Bewegung des anderen gemessen.  Das ist derselbe Fehler, den CLAUDE.md fuer die drei offboard_e2e-Pakete beschreibt --
"sie teilen sich Server und Arm".

Eine Dateisperre wirkt ueber Prozessgrenzen und damit auch ueber xdist-Worker.  Sie serialisiert NUR die Tests, die
wirklich fahren; lesende Tests laufen weiter parallel.
"""

import os
import tempfile

import pytest
from filelock import FileLock

#: Neben dem Temp-Verzeichnis, nicht im Repo -- eine Sperrdatei ist Laufzeit,
#: kein Artefakt.
_LOCK_PATH = os.path.join(tempfile.gettempdir(), "husky-navigation-base.lock")


@pytest.fixture
def exclusive_base():
    """Exklusiver Zugriff auf die fahrende Basis.

    Jeder Test, der cmd_vel schickt oder ein Navigationsziel sendet, MUSS diese Fixture anfordern -- sonst misst er die
    Fahrt eines anderen Tests.
    """
    with FileLock(_LOCK_PATH, timeout=600):
        yield
