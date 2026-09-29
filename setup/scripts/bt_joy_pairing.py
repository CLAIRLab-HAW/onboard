#!/usr/bin/env python3
"""bt_joy_pairing: lets a phone pair with the robot as its Bluetooth joystick, and nothing else.

Echo for Android offers an HID gamepad whose reports land on the same ``joy_linux`` indices as the robot's pad (R62).
What it cannot do on its own is get past BlueZ: the a200 has no screen, so a pairing request waits for an agent that
never answers. This node is that agent, and it is a narrow one:

* **Pairing only inside a window.** ``bt_joy/open_pairing`` (``std_srvs/Trigger``) makes the adapter discoverable and
  pairable for ``window_s`` seconds and answers with the adapter's address as flat JSON, so the app can bond to it
  without a scan. Outside the window every pairing request is rejected -- a robot open to pairing at all times would
  take a keyboard from anyone in range, and a gamepad that drives the base.
* **Only HID gets through.** ``AuthorizeService`` accepts the HID profile from a paired device and rejects every other
  service (audio, OBEX, networking).
* **Paired once, trusted after.** A device that paired inside the window is marked ``Trusted``, so BlueZ accepts its
  later HID connections without asking the agent: the phone reconnects by itself whenever the app offers the gamepad.

Once the phone is connected, BlueZ creates an input device and the robot's own ``joy_node`` reads it -- as long as it
becomes ``/dev/input/js0``, i.e. no other pad is connected first (``joy_node`` reads ``js0`` only; robot.yaml).

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


def pairing_allowed(now_s: float, window_end_s: float) -> bool:
    """Whether a pairing request arriving at ``now_s`` falls inside the window that closes at ``window_end_s``."""
    return now_s < window_end_s


def service_allowed(uuid: str, paired: bool) -> bool:
    """Whether a device may connect to the service ``uuid``: the HID profile, and only from a paired device."""
    return paired and uuid.lower() == HID_UUID


def pairing_reply(address: str, name: str, window_s: float) -> str:
    """The ``Trigger`` message: flat JSON the app reads the adapter address from."""
    return json.dumps({"address": address, "name": name, "window_s": window_s})


def selftest() -> int:
    """Pure-Python check of the gating logic."""
    assert pairing_allowed(10.0, 70.0) and not pairing_allowed(70.0, 70.0)
    assert service_allowed(HID_UUID.upper(), paired=True)
    assert not service_allowed(HID_UUID, paired=False)
    assert not service_allowed("0000110b-0000-1000-8000-00805f9b34fb", paired=True)  # A2DP sink
    assert json.loads(pairing_reply("AA:BB:CC:DD:EE:FF", "cpr-a200-0553", 60.0))["address"] == "AA:BB:CC:DD:EE:FF"
    print("bt_joy_pairing selftest: OK")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Register the agent, serve ``bt_joy/open_pairing`` and run the GLib loop that carries both."""
    argv = sys.argv if argv is None else argv
    if "--selftest" in argv:
        return selftest()

    import dbus
    import dbus.mainloop.glib
    import dbus.service
    import rclpy
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
    objects = dbus.Interface(bus.get_object("org.bluez", "/"), "org.freedesktop.DBus.ObjectManager").GetManagedObjects()
    adapter_path = next(p for p, ifaces in objects.items() if "org.bluez.Adapter1" in ifaces)
    adapter = dbus.Interface(bus.get_object("org.bluez", adapter_path), "org.freedesktop.DBus.Properties")
    window_end_s = 0.0
    # Devices that asked to pair inside the window; they are trusted once the bond stands.
    admitted: set[str] = set()

    def device_props(path: str) -> dbus.Interface:
        return dbus.Interface(bus.get_object("org.bluez", path), "org.freedesktop.DBus.Properties")

    def name_of(path: str) -> str:
        return str(device_props(path).Get("org.bluez.Device1", "Alias"))

    class Agent(dbus.service.Object):
        def admit(self, device: str) -> None:
            if not pairing_allowed(time.monotonic(), window_end_s):
                log.warning(f"pairing refused, no window open: {name_of(device)}")
                raise Rejected("pairing window closed")
            admitted.add(str(device))
            log.info(f"pairing accepted: {name_of(device)}")

        @dbus.service.method("org.bluez.Agent1", in_signature="o", out_signature="")
        def RequestAuthorization(self, device):  # noqa: N802 - BlueZ's method names
            self.admit(device)

        @dbus.service.method("org.bluez.Agent1", in_signature="ou", out_signature="")
        def RequestConfirmation(self, device, passkey):  # noqa: N802
            self.admit(device)

        @dbus.service.method("org.bluez.Agent1", in_signature="os", out_signature="")
        def AuthorizeService(self, device, uuid):  # noqa: N802
            paired = bool(device_props(device).Get("org.bluez.Device1", "Paired"))
            if not service_allowed(str(uuid), paired):
                log.warning(f"service {uuid} refused for {name_of(device)}")
                raise Rejected("only HID from a paired device")

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

    def on_device_changed(interface, changed, invalidated, path=None):
        if interface == "org.bluez.Device1" and changed.get("Paired") and path in admitted:
            admitted.discard(path)
            device_props(path).Set("org.bluez.Device1", "Trusted", dbus.Boolean(True))
            log.info(f"paired and trusted: {name_of(path)}")

    bus.add_signal_receiver(
        on_device_changed, "PropertiesChanged", "org.freedesktop.DBus.Properties", "org.bluez", path_keyword="path"
    )
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

    loop = GLib.MainLoop()

    def spin() -> bool:
        rclpy.spin_once(node, timeout_sec=0.0)
        if not rclpy.ok():
            loop.quit()
        return rclpy.ok()

    # One thread for both: dbus-python's handlers run in the GLib loop, and polling the ROS executor from it every
    # 50 ms keeps the service answering well inside any client's timeout.
    GLib.timeout_add(50, spin)
    try:
        loop.run()
    except KeyboardInterrupt:
        pass
    finally:
        manager.UnregisterAgent(AGENT_PATH)
        agent.remove_from_connection()
        node.destroy_node()
        rclpy.try_shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
