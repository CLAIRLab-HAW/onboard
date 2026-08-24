"""Topic- und Frame-Namen der Navigationsschicht -- die einzige Quelle.

ROS-frei.  Die Launch-Dateien in ../../launch/ importieren von hier; ein Test haelt fest, dass sie die Werte nicht ein
zweites Mal formulieren.
"""

from __future__ import annotations

#: Namespace des a200-0553.  Der ganze Graph haengt daran.
NAMESPACE = "a200_0553"

#: Der Frame, den robot.yaml fuer den lidar3d-Eintrag erzeugt und den der
#: Treiber in jede PointCloud2 schreibt.  Weichen die beiden voneinander ab,
#: findet tf2 die Wolke nicht und meldet es nicht.
LIDAR_FRAME = "lidar3d_0_laser"

#: Wurzel-Link des URDF (robot-contract-Profil: frames.base_link).
BASE_FRAME = "base_link"

#: tf2 broadcastet auf die ABSOLUTEN Namen; der Node-Namespace greift dort
#: nicht.  Ohne diese Remaps publiziert ein Knoten global, waehrend der Rest
#: des Graphen auf /a200_0553/tf lauscht -- eine leere TF-Kette ohne Fehler.
TF_REMAPS = [("/tf", "tf"), ("/tf_static", "tf_static")]


def points_topic() -> str:
    """Rohe Punktwolke des RS16 (sensor_msgs/PointCloud2)."""
    return f"/{NAMESPACE}/sensors/lidar3d_0/points"


def scan_topic() -> str:
    """Aus der Wolke abgeleiteter 2D-Scan (sensor_msgs/LaserScan).

    AMCL und slam_toolbox lesen AUSSCHLIESSLICH LaserScan -- eine PointCloud2 koennen beide nicht verarbeiten.  Dieser
    Knoten ist deshalb kein Komfort, sondern Voraussetzung.
    """
    return f"/{NAMESPACE}/sensors/lidar3d_0/scan"


def cmd_vel_topic() -> str:
    """Nav2s Fahrbefehl.

    Das ist der Eingang 'external' des twist_mux (Prioritaet 1, die niedrigste) -- Joystick, RC und interaktiver Marker
    uebersteuern Nav2 also jederzeit.  Typ ist geometry_msgs/TwistStamped, nicht Twist.
    """
    return f"/{NAMESPACE}/cmd_vel"


def pointcloud_to_laserscan_params() -> dict:
    """Parameter des pointcloud_to_laserscan-Knotens.

    Das Hoehenband ist RELATIV ZU base_link (target_frame) und muss die Fahrebene enthalten -- ein Band ueber oder unter
    ihr liefert lauter `inf` und sieht wie ein kaputter Treiber aus.
    """
    return {
        "target_frame": BASE_FRAME,
        "transform_tolerance": 0.05,
        # Band um die Fahrebene: alles zwischen 10 cm unter und 50 cm ueber base_link.  base_link liegt 13,228 cm ueber
        # dem Boden (das URDF setzt base_footprint mit z=-0.13228 darunter), das Band beginnt also knapp ueber dem
        # Boden.
        "min_height": -0.10,
        "max_height": 0.50,
        "angle_min": -3.141592653589793,
        "angle_max": 3.141592653589793,
        "angle_increment": 0.0087,  # 0,5 Grad -> 720 Strahlen
        "scan_time": 0.1,  # RS16 dreht mit 10 Hz
        # Unter 20 cm sieht der Sensor sein eigenes Gehaeuse; diese Punkte wuerden in der Costmap zu einem Hindernisring
        # um den Roboter.
        "range_min": 0.2,
        "range_max": 100.0,
        "use_inf": True,
        "inf_epsilon": 1.0,
    }
