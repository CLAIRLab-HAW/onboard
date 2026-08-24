"""Topic- und Frame-Namen sind Vertraege, keine Schreibweisen.

Der Graph dieses Roboters ist durchgaengig namespaced; tf2 broadcastet aber
auf die ABSOLUTEN Namen /tf und /tf_static, wo der Node-Namespace nicht
greift.  Fehlt der Remap, publiziert ein Knoten global, waehrend alle anderen
auf /a200_0553/tf lauschen -- und es gibt keine Fehlermeldung, nur eine leere
TF-Kette.  Genau das ist im Mock schon einmal passiert (scripts/mock, Kommentar
am robot_state_publisher).

Braucht weder ROS noch Docker.
"""

from husky_navigation import wiring


def test_the_points_topic_follows_the_clearpath_convention():
    assert wiring.points_topic() == "/a200_0553/sensors/lidar3d_0/points"


def test_the_scan_topic_sits_beside_the_points_topic():
    assert wiring.scan_topic() == "/a200_0553/sensors/lidar3d_0/scan"


def test_the_driver_template_publishes_on_the_wired_points_topic():
    """Treibervorlage und Verdrahtung duerfen nicht auseinanderlaufen."""
    import yaml
    from husky_navigation import rslidar_config as rc

    template = yaml.safe_load(rc.TEMPLATE_PATH.read_text(encoding="utf-8"))
    assert (
        template["lidar"][0]["ros"]["ros_send_point_cloud_topic"]
        == wiring.points_topic()
    )


def test_the_driver_template_uses_the_wired_frame():
    import yaml
    from husky_navigation import rslidar_config as rc

    template = yaml.safe_load(rc.TEMPLATE_PATH.read_text(encoding="utf-8"))
    assert template["lidar"][0]["ros"]["ros_frame_id"] == wiring.LIDAR_FRAME


def test_tf_is_remapped_into_the_namespace():
    assert ("/tf", "tf") in wiring.TF_REMAPS
    assert ("/tf_static", "tf_static") in wiring.TF_REMAPS


def test_the_scan_is_projected_into_the_base_frame():
    params = wiring.pointcloud_to_laserscan_params()
    assert params["target_frame"] == wiring.BASE_FRAME


def test_the_scan_band_brackets_the_driving_plane():
    """Ein Band, das die Fahrebene nicht enthaelt, liefert lauter inf --
    und das sieht aus wie ein kaputter Treiber."""
    params = wiring.pointcloud_to_laserscan_params()
    assert params["min_height"] < 0.0 < params["max_height"]


def test_the_scan_range_starts_beyond_the_robot_itself():
    params = wiring.pointcloud_to_laserscan_params()
    assert params["range_min"] >= 0.2, (
        "Unter 20 cm sieht der RS16 sich selbst -- diese Punkte wuerden zu "
        "einem Hindernisring rund um den Roboter in der Costmap."
    )


def test_cmd_vel_goes_to_the_twist_mux_external_input():
    assert wiring.cmd_vel_topic() == "/a200_0553/cmd_vel"
