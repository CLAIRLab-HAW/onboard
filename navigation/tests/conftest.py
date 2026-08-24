"""Only ONE test may drive the robot at a time.

The root run distributes across several processes with ``-n 4 --dist loadfile``, and ``loadfile`` groups by FILE --
test_platform_mock_e2e.py and test_navigation_e2e.py therefore land on different workers and drive off at the same
time.  Both command the same base and read the same odometry.

Measured on 2026-08-22: both reported exactly the same values (3,878 -> 4,058) and both failed.  Each had measured the
other one's motion.  That is the same fault CLAUDE.md describes for the three offboard_e2e packages -- "they share
server and arm".

A file lock works across process boundaries and therefore across xdist workers too.  It serialises ONLY the tests that
really drive; read-only tests keep running in parallel.
"""

import os
import tempfile

import pytest
from filelock import FileLock

#: In the temp directory, not in the repo -- a lock file is runtime, not an
#: artefact.
_LOCK_PATH = os.path.join(tempfile.gettempdir(), "husky-navigation-base.lock")


@pytest.fixture
def exclusive_base():
    """Exclusive access to the driving base.

    Every test that sends cmd_vel or a navigation goal MUST request this fixture -- otherwise it measures another
    test's drive.
    """
    with FileLock(_LOCK_PATH, timeout=600):
        yield
