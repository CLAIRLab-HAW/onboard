"""Only ONE test may drive the robot at a time.

The root run distributes across several processes with ``-n 4 --dist loadfile``, and ``loadfile`` groups by FILE --
test_platform_mock_e2e.py and test_navigation_e2e.py therefore land on different workers and drive off at the same
time.  Both command the same base and read the same odometry.

Measured on 2026-08-22: both reported exactly the same values (3,878 ─▶ 4,058) and both failed.  Each had measured the
other one's motion.  That is the same fault CLAUDE.md describes for the three offboard_e2e packages -- "they share
server and arm".

The lock itself lives in ``robot_contract.base_testing``, not here: a conftest is directory-scoped, so a lock defined
in this package serialises this package and NOTHING in ``apps/robot-mcp``, which drives the same base.  The fixture
below is only the local name for it.
"""

import pytest

from robot_contract.base_testing import exclusive_base as _exclusive_base


@pytest.fixture
def exclusive_base():
    """Exclusive access to the driving base.

    Every test that sends cmd_vel or a navigation goal MUST request this fixture -- and so must every test that
    asserts the base did NOT move, because a foreign drive makes that assertion fail for the wrong reason.
    """
    with _exclusive_base():
        yield
