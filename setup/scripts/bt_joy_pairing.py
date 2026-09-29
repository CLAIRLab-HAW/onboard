#!/usr/bin/env python3
"""bt_joy_pairing: lets a phone pair with the robot as its Bluetooth joystick, and nothing else.

Echo for Android offers an HID gamepad whose reports land on the same ``joy_linux`` indices as the robot's pad (R62).
What it cannot do on its own is get past BlueZ: the a200 has no screen, so a pairing request waits for an agent that
never answers. This node is that agent, and it is a narrow one:

* **Pairing only inside a window.** ``bt_joy/open_pairing`` (``std_srvs/Trigger``) makes the adapter discoverable and
  pairable for ``window_s`` seconds and answers with the adapter's address as flat JSON, so the app can bond to it
  without a scan. Outside the window the adapter is not pairable at all -- a robot open to pairing at all times would
  take a keyboard from anyone in range, and a gamepad that drives the base. The window is the gate that holds: with a
  ``NoInputNoOutput`` agent the kernel accepts a Just Works pairing without asking it (a200-0553, 2026-09-29: the
  phone paired, the agent heard nothing).
* **Only HID gets through.** ``AuthorizeService`` accepts the HID profile from a paired device, marks it ``Trusted`` so
  its later connections need no agent, and rejects every other service (audio, OBEX, networking).
* **The phone drives through a teleop of its own.** Clearpath's ``joy_node`` reads one device, the Xbox pad
  (``/dev/input/xbox_pad``, robot.yaml). So this node starts a second ``joy_node`` on ``/dev/input/bt_joy`` -- the
  udev name the installer gives a Bluetooth joystick other than a PS4 pad -- and a second ``teleop_twist_joy`` onto
  the same ``joy_teleop/cmd_vel``, both with the generated ``teleop_joy.yaml``'s parameters. ``teleop_twist_joy``
  publishes only while its deadman is held, so the two pads do not fight: whoever holds the deadman drives, and
  twist_mux stops the base 0.5 s after the last command.

``python3-dbus`` and ``python3-gi`` come with Ubuntu 24.04 on the robot (system snapshot); the node runs as the robot
user, which the installer's D-Bus policy lets talk to ``org.bluez``.

Invocation (service clearpath-custom-bt-joy, see installer)::

    bt-joy-pairing --ros-args -r __ns:=/a200_0553 -p window_s:=60

Selftest without ROS or D-Bus (runs on the workstation too)::

    python3 bt_joy_pairing.py --selftest
"""

from __future__ import annotations

import json
import sys
import time

#: The HID profile's service class UUID (Bluetooth assigned number 0x1124), as BlueZ passes it to ``AuthorizeService``.
HID_UUID = "00001124-0000-1000-8000-00805f9b34fb"

#: Where the agent object sits on the system bus; any path this process owns will do.
AGENT_PATH = "/de/clair/bt_joy/agent"

#: The udev symlink of a Bluetooth joystick (installer, managed udev block); the phone's ``joy_node`` reads it.
BT_JOY_DEV = "/dev/input/bt_joy"

#: The node names of the phone's teleop chain, beside Clearpath's ``joy_node`` and ``teleop_twist_joy_node``.
JOY_NODE = "bt_joy_node"
TELEOP_NODE = "bt_teleop_twist_joy_node"

#: Where the phone's teleop publishes: the topic twist_mux already takes the joystick from (generated twist_mux.yaml).
CMD_VEL_REMAP = "cmd_vel:=joy_teleop/cmd_vel"


def pairing_allowed(now_s: float, window_end_s: float) -> bool:
    """Whether a pairing request arriving at ``now_s`` falls inside the window that closes at ``window_end_s``."""
    return now_s < window_end_s


def service_allowed(uuid: str, paired: bool) -> bool:
    """Whether a device may connect to the service ``uuid``: the HID profile, and only from a paired device."""
    return paired and uuid.lower() == HID_UUID


def pairing_reply(address: str, name: str, window_s: float) -> str:
    """The ``Trigger`` message: flat JSON the app reads the adapter address from."""
    return json.dumps({"address": address, "name": name, "window_s": window_s})


def phone_teleop_params(generated: dict) -> dict:
    """Parameters for the phone's teleop chain out of Clearpath's generated ``teleop_joy.yaml``: its ``joy_node`` and
    ``teleop_twist_joy_node`` parameters under this chain's node names, the joystick device set to :data:`BT_JOY_DEV`.
    """
    ((ns, nodes),) = generated.items()
    joy = dict(nodes["joy_node"]["ros__parameters"], dev=BT_JOY_DEV)
    teleop = dict(nodes["teleop_twist_joy_node"]["ros__parameters"])
    return {ns: {JOY_NODE: {"ros__parameters": joy}, TELEOP_NODE: {"ros__parameters": teleop}}}


def selftest() -> int:
    """Pure-Python check of the gating logic."""
    assert pairing_allowed(10.0, 70.0) and not pairing_allowed(70.0, 70.0)
    assert service_allowed(HID_UUID.upper(), paired=True)
    assert not service_allowed(HID_UUID, paired=False)
    assert not service_allowed("0000110b-0000-1000-8000-00805f9b34fb", paired=True)  # A2DP sink
    assert json.loads(pairing_reply("AA:BB:CC:DD:EE:FF", "cpr-a200-0553", 60.0))["address"] == "AA:BB:CC:DD:EE:FF"
    generated = {"ns": {"joy_node": {"ros__parameters": {"dev": "/dev/input/js0"}}, "teleop_twist_joy_node": {}}}
    generated["ns"]["teleop_twist_joy_node"]["ros__parameters"] = {"enable_button": 4}
    assert phone_teleop_params(generated)["ns"][JOY_NODE]["ros__parameters"]["dev"] == BT_JOY_DEV
    print("bt_joy_pairing selftest: OK")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Register the agent, serve ``bt_joy/open_pairing`` and run the GLib loop that carries both."""
    argv = sys.argv if argv is None else argv
    if "--selftest" in argv:
        return selftest()

    import subprocess
    import tempfile

    import dbus
    import dbus.mainloop.glib
    import dbus.service
    import rclpy
    import yaml
    from ament_index_python.packages import get_package_prefix
    from gi.repository import GLib
    from std_srvs.srv import Trigger

    class Rejected(dbus.DBusException):
        _dbus_error_name = "org.bluez.Error.Rejected"

    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    bus = dbus.SystemBus()
    rclpy.init(args=argv)
    node = rclpy.create_node("bt_joy_pairing")
    log = node.get_logger()
    window_s = float(node.declare_parameter("window_s", 60.0).value)
    teleop_config = str(node.declare_parameter("teleop_config", "/etc/clearpath/platform/config/teleop_joy.yaml").value)
    objects = dbus.Interface(bus.get_object("org.bluez", "/"), "org.freedesktop.DBus.ObjectManager").GetManagedObjects()
    adapter_path = next(p for p, ifaces in objects.items() if "org.bluez.Adapter1" in ifaces)
    adapter = dbus.Interface(bus.get_object("org.bluez", adapter_path), "org.freedesktop.DBus.Properties")
    window_end_s = 0.0

    def device_props(path: str) -> dbus.Interface:
        return dbus.Interface(bus.get_object("org.bluez", path), "org.freedesktop.DBus.Properties")

    def name_of(path: str) -> str:
        return str(device_props(path).Get("org.bluez.Device1", "Alias"))

    class Agent(dbus.service.Object):
        def admit(self, device: str) -> None:
            if not pairing_allowed(time.monotonic(), window_end_s):
                log.warning(f"pairing refused, no window open: {name_of(device)}")
                raise Rejected("pairing window closed")
            log.info(f"pairing accepted: {name_of(device)}")

        @dbus.service.method("org.bluez.Agent1", in_signature="o", out_signature="")
        def RequestAuthorization(self, device):  # noqa: N802 - BlueZ's method names
            self.admit(device)

        @dbus.service.method("org.bluez.Agent1", in_signature="ou", out_signature="")
        def RequestConfirmation(self, device, passkey):  # noqa: N802
            self.admit(device)

        @dbus.service.method("org.bluez.Agent1", in_signature="os", out_signature="")
        def AuthorizeService(self, device, uuid):  # noqa: N802
            props = device_props(device)
            if not service_allowed(str(uuid), bool(props.Get("org.bluez.Device1", "Paired"))):
                log.warning(f"service {uuid} refused for {name_of(device)}")
                raise Rejected("only HID from a paired device")
            props.Set("org.bluez.Device1", "Trusted", dbus.Boolean(True))
            log.info(f"HID accepted, trusted from now on: {name_of(device)}")

        # A PIN or passkey needs a keyboard the robot does not have; Just Works is the only method on offer.
        @dbus.service.method("org.bluez.Agent1", in_signature="o", out_signature="s")
        def RequestPinCode(self, device):  # noqa: N802
            raise Rejected("no PIN entry")

        @dbus.service.method("org.bluez.Agent1", in_signature="o", out_signature="u")
        def RequestPasskey(self, device):  # noqa: N802
            raise Rejected("no passkey entry")

        @dbus.service.method("org.bluez.Agent1", in_signature="ouq", out_signature="")
        def DisplayPasskey(self, device, passkey, entered):  # noqa: N802
            pass

        @dbus.service.method("org.bluez.Agent1", in_signature="os", out_signature="")
        def DisplayPinCode(self, device, pincode):  # noqa: N802
            pass

        @dbus.service.method("org.bluez.Agent1", in_signature="", out_signature="")
        def Cancel(self):  # noqa: N802
            pass

        @dbus.service.method("org.bluez.Agent1", in_signature="", out_signature="")
        def Release(self):  # noqa: N802
            pass

    agent = Agent(bus, AGENT_PATH)
    manager = dbus.Interface(bus.get_object("org.bluez", "/org/bluez"), "org.bluez.AgentManager1")
    manager.RegisterAgent(AGENT_PATH, "NoInputNoOutput")
    manager.RequestDefaultAgent(AGENT_PATH)
    # BlueZ makes the adapter pairable as soon as an agent registers (main.conf AlwaysPairable=false); closed until
    # someone asks for a window, so a pairing attempt from outside never even reaches the agent.
    adapter.Set("org.bluez.Adapter1", "Pairable", dbus.Boolean(False))

    def open_pairing(request, response):
        nonlocal window_end_s
        for prop, value in (
            ("Powered", dbus.Boolean(True)),
            ("PairableTimeout", dbus.UInt32(int(window_s))),
            ("DiscoverableTimeout", dbus.UInt32(int(window_s))),
            ("Pairable", dbus.Boolean(True)),
            ("Discoverable", dbus.Boolean(True)),
        ):
            adapter.Set("org.bluez.Adapter1", prop, value)
        window_end_s = time.monotonic() + window_s
        address = str(adapter.Get("org.bluez.Adapter1", "Address"))
        name = str(adapter.Get("org.bluez.Adapter1", "Alias"))
        log.info(f"pairing window open for {window_s:.0f} s as {name} ({address})")
        response.success = True
        response.message = pairing_reply(address, name, window_s)
        return response

    node.create_service(Trigger, "bt_joy/open_pairing", open_pairing)
    log.info(f"agent registered on {adapter_path}; bt_joy/open_pairing opens a {window_s:.0f} s window")

    with open(teleop_config) as f:
        params = phone_teleop_params(yaml.safe_load(f))
    params_file = tempfile.NamedTemporaryFile("w", prefix="bt_joy_", suffix=".yaml", delete=False)
    with params_file:
        yaml.safe_dump(params, params_file)
    chain = (
        ("joy_linux", "joy_linux_node", JOY_NODE, ["-r", "joy:=bt_joy/joy"]),
        ("teleop_twist_joy", "teleop_node", TELEOP_NODE, ["-r", "joy:=bt_joy/joy", "-r", CMD_VEL_REMAP]),
    )
    children = [
        subprocess.Popen(
            [f"{get_package_prefix(pkg)}/lib/{pkg}/{exe}", "--ros-args", "-r", f"__node:={name}"]
            + ["-r", f"__ns:={node.get_namespace()}", "--params-file", params_file.name, *remaps]
        )
        for pkg, exe, name, remaps in chain
    ]
    log.info(f"phone teleop on {BT_JOY_DEV}: {JOY_NODE} + {TELEOP_NODE} -> joy_teleop/cmd_vel")

    loop = GLib.MainLoop()
    exit_code = 0

    def spin() -> bool:
        nonlocal exit_code
        rclpy.spin_once(node, timeout_sec=0.0)
        dead = [c.args[0] for c in children if c.poll() is not None]
        if dead:
            # systemd restarts the unit: a teleop chain without its joy_node or teleop half would look alive and drive
            # nothing.
            log.error(f"exited: {', '.join(dead)}")
            exit_code = 1
        if dead or not rclpy.ok():
            loop.quit()
            return False
        return True

    # One thread for both: dbus-python's handlers run in the GLib loop, and polling the ROS executor from it every
    # 50 ms keeps the service answering well inside any client's timeout.
    GLib.timeout_add(50, spin)
    try:
        loop.run()
    except KeyboardInterrupt:
        pass
    finally:
        for c in children:
            c.terminate()
        for c in children:
            try:
                c.wait(timeout=5)
            except subprocess.TimeoutExpired:
                c.kill()
        manager.UnregisterAgent(AGENT_PATH)
        agent.remove_from_connection()
        node.destroy_node()
        rclpy.try_shutdown()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
