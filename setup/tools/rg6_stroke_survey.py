#!/usr/bin/env python3
"""rg6_stroke_survey: measure the gripper stroke point by point (R19 item 2).

The open question:  the model puts the open limit at 159.0 mm, the caliper says ~151 mm.  If the width is off by the
same amount over the WHOLE stroke, the error sits in the pad offset (``kPadOffsetM``); if the hand never reaches 159 mm
at all, the crank dead centre is too generous an open limit.  Only a run across the full stroke answers that, and this
script drives it.

``analog_input2_v`` is always ``None``.  AI2 answers a different question -- whether the tool connector has power at all
-- and is explicitly rejected as a width source: on 2026-08-19 it measured up to 17 mm off.  The field stays in the
output so runs recorded under the older calibration line up column for column (see the repo CHANGELOG).

    !!! THIS SCRIPT MOVES THE GRIPPER !!!

Only run it with somebody at the device.  The arm stays put; only the hand moves.  On 2026-08-17 the gripper jammed in
``busy: true`` once already.  The way out is the URCap: ``rg_stop``, then a fresh command; if that does not help,
restart the URCap program from the teach pendant.

    python3 rg6_stroke_survey.py > /tmp/rg6-stroke-survey.json

Into a FILE, not into a pipe: on 2026-08-17 a ``| tail -20`` destroyed the
result of a complete run that had already moved the hardware.  A measurement
that touches the robot is not repeated because its output got truncated.

To compare against older runs, AI2 still comes from

    /a200_0553/manipulators/io_and_status_controller/tool_data

with ``manipulators/`` in the path.  The path without that segment silently delivers nothing, and that looks like a dead
topic.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

# The bridge lives in the onrobot-rg6 workspace (rg6_control), this is a tool of this repo, and the deployed copy
# under /usr/local/bin/rg6-grip-bridge is not importable by name (hyphens, no .py).  So the import has to be said
# out loud rather than left to the layout, and it has to work in both places this tool is run: out of the checkout
# on the workstation, and next to the built workspace on the robot.
_BRIDGE_DIRS = (
    Path(__file__).resolve().parents[2] / "onrobot-rg6/src/rg6_control/scripts",  # workspace checkout
    Path.home() / "onrobot-rg6/src/rg6_control/scripts",  # the robot's clone
    Path.home() / "onrobot-rg6/install/rg6_control/lib/rg6_control",  # its install space
)
for _dir in _BRIDGE_DIRS:
    if (_dir / "rg6_grip_bridge.py").is_file():
        sys.path.insert(0, str(_dir))
        break
else:  # no break
    raise SystemExit(
        "rg6_grip_bridge.py found in none of:\n  " + "\n  ".join(str(d) for d in _BRIDGE_DIRS) + "\n"
        "It belongs to the onrobot-rg6 workspace -- clone/build it, or run this tool from the checkout."
    )

from rg6_grip_bridge import Rg6Client, Rg6Error, await_settled  # noqa: E402

#: The full stroke, with extra points near the open stop -- that is where the
#: open question from R19 item 2 sits (model 159.0 mm, caliper ~151 mm).
WIDTHS_MM = [160.0, 151.0, 140.0, 120.0, 100.0, 80.0, 60.0, 40.0, 20.0, 0.0]
#: The RG6 visibly needs time to come to rest; read too early and you measure
#: the travel, not the stop.  2.5 s is NOT enough for that: on 2026-08-19 the
#: reported value kept creeping about 0.9 mm afterwards and only settled after
#: minutes (then quiet to 0.18 mm).  To survey the open stop, use ``--settle
#: 30`` or more; 2.5 s stays the default so a quick functional run does not
#: take ten minutes.
SETTLE_S = 2.5
#: Low enough that an object left in the jaws by accident is not crushed --
#: what is being measured is the stroke, not the force.  The manual (v6.6.2)
#: also notes that the target force degrades width accuracy; for a calibration
#: run use ``--force 25`` (the minimum).
FORCE_N = 40.0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--settle",
        type=float,
        default=SETTLE_S,
        metavar="S",
        help="settle time per point in seconds (default: %(default)s)",
    )
    ap.add_argument(
        "--force", type=float, default=FORCE_N, metavar="N", help="grip force in newton, 25..120 (default: %(default)s)"
    )
    ap.add_argument(
        "--both",
        action="store_true",
        help="after the descending stroke, drive the same one ascending "
        "-- answers whether the reported value depends on the "
        "direction of travel",
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
            print(f"# {width_mm:6.1f} mm ─▶ ERROR {exc}", file=sys.stderr)
            continue
        # Wait for the travel to end (busy edges) FIRST, THEN settle: with a short --settle, half the settle time would
        # fall into the travel.
        try:
            await_settled(client)
        except Rg6Error as exc:
            # Recorded in the row AND on stderr, like the grip failure above: stdout carries the survey, and a
            # run that quietly drops half its points otherwise looks like a complete one.
            rows.append({"commanded_mm": width_mm, "error": str(exc)})
            print(f"# {width_mm:6.1f} mm -> ERROR while settling: {exc}", file=sys.stderr)
            continue
        time.sleep(settle_s)
        try:
            st = client.state()
        except Rg6Error as exc:
            rows.append({"commanded_mm": width_mm, "error": str(exc)})
            print(f"# {width_mm:6.1f} mm -> ERROR while reading back: {exc}", file=sys.stderr)
            continue
        rows.append(
            {
                "commanded_mm": width_mm,
                # Wall clock of the state read -- pins the row to a moment a separately recorded trace can be laid
                # against.
                "t_read": time.time(),
                "device_width_mm": st.width_m * 1000.0,
                "busy": st.busy,
                "grip_detected": st.grip_detected,
                "status": st.status,
                "safety_failed": st.safety_failed,
                # Always None: the width comes from the device, see the module docstring.  The field is kept so runs
                # recorded under the older calibration line up row for row.
                "analog_input2_v": None,
            }
        )
        print(
            f"# {width_mm:6.1f} mm ─▶ {st.width_m * 1000:6.2f} mm (busy={st.busy}, grip={st.grip_detected})",
            file=sys.stderr,
        )

    json.dump(
        {"widths_mm": widths, "settle_s": settle_s, "force_n": force_n, "both_directions": args.both, "rows": rows},
        sys.stdout,
        indent=1,
    )
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
