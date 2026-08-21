"""Erzeugt die synthetische Karte, gegen die der Mock zuerst faehrt.

Eine von Hand gemalte pgm waere ein binaeres Artefakt ohne nachvollziehbare
Herkunft -- man saehe ihr nicht an, wie gross der Raum ist und wo die Wand
steht.  Ein Generator sagt es.

Diese Karte ersetzt KEINE Kartierung.  Sie ist das Geruest, an dem Planer und
Controller gemessen werden, solange es noch keine RS16-Aufnahme gibt.

ROS-frei.
"""
from __future__ import annotations

from pathlib import Path

FREE = 254        # weiss  -> befahrbar
OCCUPIED = 0      # schwarz -> Wand


def write_empty_room(out_stem: str | Path, *, width_m: float = 10.0,
                     height_m: float = 10.0,
                     resolution: float = 0.05) -> tuple[Path, Path]:
    """Schreibt <stem>.pgm und <stem>.yaml: freier Raum mit Wand ringsum.

    Rueckgabe: (pgm_path, yaml_path).
    """
    stem = Path(out_stem)
    cols = int(round(width_m / resolution))
    rows = int(round(height_m / resolution))

    rowbytes = []
    for r in range(rows):
        if r == 0 or r == rows - 1:
            rowbytes.append(bytes([OCCUPIED] * cols))
        else:
            rowbytes.append(bytes([OCCUPIED]) + bytes([FREE] * (cols - 2))
                            + bytes([OCCUPIED]))

    pgm = stem.with_suffix(".pgm")
    pgm.parent.mkdir(parents=True, exist_ok=True)
    with pgm.open("wb") as fh:
        fh.write(f"P5\n# erzeugt von husky_navigation.make_map\n"
                 f"{cols} {rows}\n255\n".encode("ascii"))
        for row in rowbytes:
            fh.write(row)

    yaml_path = stem.with_suffix(".yaml")
    yaml_path.write_text(
        f"# Synthetischer leerer Raum, {width_m} x {height_m} m.\n"
        f"# Erzeugt mit husky_navigation.make_map.write_empty_room -- nicht\n"
        f"# von Hand bearbeiten, sondern neu erzeugen.\n"
        f"# origin setzt den Ursprung in die MITTE des Raumes, damit der\n"
        f"# Roboter bei Kartenstart auf (0,0) mittig steht.\n"
        f"image: {pgm.name}\n"
        f"mode: trinary\n"
        f"resolution: {resolution}\n"
        f"origin: [{-width_m / 2:.3f}, {-height_m / 2:.3f}, 0.0]\n"
        f"negate: 0\n"
        f"occupied_thresh: 0.65\n"
        f"free_thresh: 0.25\n",
        encoding="utf-8")

    return pgm, yaml_path
