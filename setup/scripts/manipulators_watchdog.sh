#!/usr/bin/env bash
# Watchdog: detects "arm reachable, but the PC-side motion link
# (ur_robot_driver) NOT connected". The health signal is the
# joint_state_broadcaster stream on .../manipulators/joint_states - it publishes
# ONLY when the ros2_control HW interface is activated and reads real arm joints.
# robot_program_running alone is NOT enough as "connected": that is the
# controller-side external control status (via dashboard/RTDE) and stays 'true'
# even when the PC-side motion link is dead - e.g. a stuck reconnect after a
# clearpath-robot.service restart with the arm already powered (the old external
# control instance holds the reverse socket, the new HW activation fails, the JSC
# stays inactive -> topic silent -> the arm goes flat in RViz). It thereby covers
# TWO cases:
#   (a) cold start with a late-powered arm: HW activation failed once (the arm was
#       unpowered), ros2_control does not retry it -> JSC silent.
#   (b) service restart with the arm already powered: the new HW activation fails
#       (socket collision with the old instance) -> JSC silent.
# Recovery: restart the driver (clearpath-manipulators.service) + restart external
# control (resend_robot_program). The arm is NOT powered automatically (no
# power_on/brake_release) - powering is an operator decision (it protects
# maintenance/end of day); with the arm at POWER_OFF no recovery runs (no driver
# loop against an unpowered arm). Protective/safety stops (safety_mode != NORMAL)
# are NOT auto-cleared (they stay manual) - the resend is skipped.
# Invocation: manipulators-watchdog.sh <ROBOT_IP> <TOPIC> <RUN_USER> <RUN_HOME>
#   TOPIC = .../io_and_status_controller/robot_program_running (the namespace is
#   derived from it; dashboard + resend services and the JSC topic sit under the
#   same NS).
set -uo pipefail

ROBOT_IP="${1:?ROBOT_IP missing}"
TOPIC="${2:?TOPIC missing}"
RUN_USER="${3:?RUN_USER missing}"
RUN_HOME="${4:?RUN_HOME missing}"
SERVICE="clearpath-manipulators.service"
DASH_SVC="clearpath-custom-ur-dashboard.service"
COOLDOWN="${WD_COOLDOWN:-180}"          # s: no further recovery for this long after one
JS_TIMEOUT="${WD_JS_TIMEOUT:-25}"      # s: wait for a JSC message (after a manipulators restart the JSC takes up to ~15s -> generous, only >JS_TIMEOUT without a message means the motion link is really dead)
RPR_WAIT="${WD_RPR_WAIT:-15}"           # iterations: confirmation that the JSC streams again after a resend
STATE="/run/manipulators-watchdog.state"
TAG="manipulators-watchdog"
log() { echo "${TAG}: $*"; }

# Derive the namespace from the topic (.../io_and_status_controller/robot_program_running).
NS="${TOPIC%/io_and_status_controller/*}"
DASH_NS="${NS}/dashboard_client"
RESEND_SVC="${NS}/io_and_status_controller/resend_robot_program"
JS_TOPIC="${NS}/joint_states"   # joint_state_broadcaster output; alive only with an active HW interface
PLATFORM_JS_TOPIC="${NS%/manipulators}/platform/joint_states"  # fallback bus (see the health check)
DRY_RUN="${WD_DRY_RUN:-0}"      # 1 = only report what would happen (test)
RPR_TOPIC="${TOPIC}"            # robot_program_running (latched/transient_local!)
RPR_TIMEOUT="${WD_RPR_TIMEOUT:-6}"      # s: wait for the latched value
RESEND_STATE="/run/manipulators-watchdog.resend"
RESEND_COOLDOWN="${WD_RESEND_COOLDOWN:-60}"  # s: do not spam at the timer rate

# Run a ROS command as RUN_USER in the same graph.
ros_cmd() { sudo -u "$RUN_USER" env HOME="$RUN_HOME" bash -lc "source /etc/clearpath/setup.bash && $*"; }

# --- helpers: mode/safety query and trigger calls (all via the dashboard) ---
robot_mode() { ros_cmd "timeout 10 ros2 service call '${DASH_NS}/get_robot_mode' ur_dashboard_msgs/srv/GetRobotMode" 2>&1 | grep -oE 'Robotmode: [A-Z_]+' | head -1; }
safety_mode() { ros_cmd "timeout 10 ros2 service call '${DASH_NS}/get_safety_mode' ur_dashboard_msgs/srv/GetSafetyMode" 2>&1 | grep -oE 'Safetymode: [A-Z_]+' | head -1; }
call_trigger() {  # $1 service path, $2 timeout(s); 0 = success=True
    local svc="$1" t="${2:-12}"
    ros_cmd "timeout ${t} ros2 service call '${svc}' std_srvs/srv/Trigger" 2>&1 | grep -q 'success=True'
}



# --- re-ignite external control (case: RTDE reads, but the motion link is gone) ---
# The JSC already streams as soon as the control box is on - RTDE reading works
# independently of external control. If the arm is powered ONLY AFTER the HW
# activation (typically: the app calls prepare), the external control program sent
# once went nowhere and ros2_control does not repeat it: reading ok, writing dead,
# the arm does not move. The JSC health check does NOT see that - only the
# conjunction "JSC streams AND robot_program_running" is trustworthy. The reaction
# here is deliberately MINIMAL: only resend_robot_program, no driver restart, no
# powering. Gate: only when the operator has already brought the arm to RUNNING and
# no safety fault is pending.
ensure_external_control() {
    ros_cmd "timeout ${RPR_TIMEOUT} ros2 topic echo --once --qos-durability transient_local '${RPR_TOPIC}'" 2>/dev/null \
        | grep -q 'data: true' && return 0
    if [ "$DRY_RUN" = "1" ]; then
        log "DRY_RUN=1 -> external control is not up; would have sent resend_robot_program."
        return 0
    fi
    local rm_now; rm_now="$(robot_mode)"
    if [ "$rm_now" != "Robotmode: RUNNING" ]; then
        return 0   # arm not ready -> do nothing (operator decision)
    fi
    local sm_now; sm_now="$(safety_mode)"
    if [ "$sm_now" != "Safetymode: NORMAL" ]; then
        log "external control is not up, but the safety mode is '${sm_now:-unknown}' -> no resend (manual release needed)."
        return 0
    fi
    local now_r; now_r="$(date +%s)"
    if [ -f "$RESEND_STATE" ]; then
        local last_r; last_r="$(cat "$RESEND_STATE" 2>/dev/null || echo 0)"
        [ -n "$last_r" ] || last_r=0
        if [ "$(( now_r - last_r ))" -lt "$RESEND_COOLDOWN" ]; then
            return 0
        fi
    fi
    echo "$now_r" > "$RESEND_STATE"
    log "the arm is RUNNING and the JSC streams, but external control is not running (robot_program_running != true) -> resend_robot_program. NO driver restart, no powering."
    if call_trigger "${RESEND_SVC}" 20; then
        sleep 3
        if ros_cmd "timeout ${RPR_TIMEOUT} ros2 topic echo --once --qos-durability transient_local '${RPR_TOPIC}'" 2>/dev/null | grep -q 'data: true'; then
            log "external control active again."
        else
            log "resend sent, robot_program_running not true yet - the next run checks again (cooldown ${RESEND_COOLDOWN}s)."
        fi
    else
        log "resend_robot_program failed - the next run checks again (cooldown ${RESEND_COOLDOWN}s)."
    fi
}

# 1) Is the arm reachable at all? No -> deliberately do nothing (the arm is still
#    off; the watchdog should fire ONLY on a late power-up or after a driver
#    failure, not constantly).
if ! ping -c1 -W1 "$ROBOT_IP" >/dev/null 2>&1; then
    exit 0
fi

# 2) Health check: is the PC-side motion link alive? The signal is the JSC stream
#    on .../manipulators/joint_states (real arm joints, available only when the
#    ros2_control HW interface is activated). robot_program_running (true/false) is
#    NOT a sufficient signal (controller side, stays true with a dead PC-side motion
#    link). The grace timeout is generous: after a manipulators restart the JSC
#    takes up to ~15s -> only >JS_TIMEOUT without a message means really dead.
if ros_cmd "timeout ${JS_TIMEOUT} ros2 topic echo --once '${JS_TOPIC}'" >/dev/null 2>&1; then
    ensure_external_control    # the JSC read path is ok - but is the write path up too?
    exit 0
fi
# Fallback: the arm joints can also arrive on the platform bus - namely when the
# stock patch move_arm_joint_states (clearpath-custom-setup.py step 3) no longer
# takes effect after an apt update. Without this branch the watchdog would read
# silence on a PERFECTLY HEALTHY robot and restart the driver permanently at the
# cooldown rate. The health signal is "arm joints arrive" - on whichever bus.
if ros_cmd "timeout ${JS_TIMEOUT} ros2 topic echo --once '${PLATFORM_JS_TOPIC}'" 2>/dev/null \
     | grep -q 'arm_0_shoulder_pan_joint'; then
    log "WARN: arm joints arrive on ${PLATFORM_JS_TOPIC} instead of ${JS_TOPIC} -> the stock patch move_arm_joint_states does NOT take effect (apt update?). The motion link is HEALTHY, no recovery. Check: journalctl -t clearpath-custom-setup -b"
    exit 0
fi

# 3) Check the cooldown (/run is cleared at boot -> fresh per boot).
now="$(date +%s)"
if [ -f "$STATE" ]; then
    last="$(cat "$STATE" 2>/dev/null || echo 0)"
    [ -n "$last" ] || last=0
    if [ "$(( now - last ))" -lt "$COOLDOWN" ]; then
        log "motion link dead (JSC silent), but the last recovery was < ${COOLDOWN}s ago -> waiting."
        exit 0
    fi
fi

log "arm reachable (${ROBOT_IP}), but JSC ${JS_TOPIC} silent (motion link dead) -> recovery: restart ${SERVICE} + restart external control. NO automatic powering of the arm (operator decision)."
echo "$now" > "$STATE"

# 3a) Ensure clearpath-custom-ur-dashboard.service (the mode query and the resend
#     need the dashboard client; independent of manipulators, it stays up).
if [ "$(systemctl is-active "$DASH_SVC" 2>/dev/null)" != "active" ]; then
    log "${DASH_SVC} not active -> starting it."
    systemctl start "$DASH_SVC" || true
    sleep 3
fi

# 3b) Arm switched off on purpose? NO auto recovery and NO auto powering - the
#     watchdog NEVER powers the arm itself (operator decision; it protects
#     maintenance/end of day). It additionally prevents an endless driver restart
#     against an unpowered arm (the HW activation fails anyway -> the JSC would
#     stay silent -> loop).
rm_mode="$(robot_mode)"
if [ "$rm_mode" = "Robotmode: POWER_OFF" ]; then
    log "the arm is POWER_OFF (deliberately unpowered) -> no auto recovery, no powering. Power it up by hand if needed; the watchdog connects the motion link as soon as the arm is on."
    exit 0
fi

# 3c) Restart the driver (blocking). With the SIGINT stop drop-in on
#     clearpath-manipulators.service (see below, WD_MANIP_DROPIN) the old
#     ros2_control_node dies cleanly (the reverse socket is closed in an orderly
#     way) instead of ignoring SIGTERM for up to 90s -> the new controller manager
#     starts against a free socket. TimeoutStartSec of the watchdog service (300s)
#     covers a slow stop plus the recovery.
if [ "$DRY_RUN" = "1" ]; then
    log "DRY_RUN=1 -> would have restarted ${SERVICE} now + resent external control. No intervention."
    exit 0
fi
systemctl restart "$SERVICE" || log "systemctl restart ${SERVICE} did not run cleanly - continuing the recovery anyway."

# 3d) Safety check: a protective/safety stop is NOT auto-cleared (manual only).
#     During a safety stop there is no resend (the operator must release first).
sm="$(safety_mode)"
if [ "$sm" != "Safetymode: NORMAL" ]; then
    log "the safety mode is '${sm:-unknown}' (not NORMAL) -> protective/safety stop. NOT auto-cleared, resend skipped. Manual inspection needed."
    exit 0
fi

# 3e) Restart external control directly (resend_robot_program) - with retries,
#     because the new manipulators CM needs a few seconds until
#     io_and_status_controller is active, and service discovery can be sluggish
#     under rmw_zenoh. A direct call instead of a ros2-service-list poll (the
#     latter is unreliable under rmw_zenoh). If the ur_state_manager runs along,
#     its auto_recover resets in parallel; a double resend is idempotent (the
#     program already runs -> success without effect).
sent=""
for attempt in 1 2 3 4 5 6; do
    if call_trigger "${RESEND_SVC}" 20; then
        log "resend_robot_program sent (attempt ${attempt})."
        sent=1; break
    fi
    log "resend attempt ${attempt} failed; retrying."
    sleep 3
done
if [ -z "$sent" ]; then
    log "resend_robot_program failed after 6 attempts - external control not restarted. Next timer run (cooldown ${COOLDOWN}s)."
    exit 0
fi

# 3f) Verify success: the JSC streams again (real arm joints). More reliable than
#     rpr, because it confirms the PC-side motion link directly (not only the
#     controller-side program). Short - the resend started external control, the
#     JSC becomes active quickly.
ok=""
for _ in $(seq 1 "${RPR_WAIT}"); do
    if ros_cmd "timeout 6 ros2 topic echo --once '${JS_TOPIC}'" >/dev/null 2>&1; then
        ok=1; break
    fi
    sleep 1
done
if [ -n "$ok" ]; then
    log "recovery successful: ${JS_TOPIC} streams again."
else
    log "resend sent, but ${JS_TOPIC} still silent. The next timer run checks again (cooldown ${COOLDOWN}s)."
fi
