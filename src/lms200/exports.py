"""Self-describing JSON, CSV, and ASCII PCD exports in metres."""

import csv
import io
import json
from typing import Any

from .protocol.measurements import Scan


def export_scan(scan: Scan, kind: str, metadata: dict[str, Any]) -> tuple[str, str]:
    common = {
        **metadata,
        "timestamp": scan.timestamp,
        "sequence": scan.sequence,
        "field_of_view": scan.field_of_view,
        "resolution": scan.resolution,
        "starting_angle": scan.starting_angle,
        "unit": scan.unit,
        "measuring_mode": scan.measuring_mode,
        "coordinate_unit": "m",
    }
    if kind == "json":
        return json.dumps(
            {"metadata": common, "scan": scan.to_dict()}, indent=2, allow_nan=False
        ), "application/json"
    if kind == "csv":
        output = io.StringIO(newline="")
        output.write("# metadata=" + json.dumps(common, separators=(",", ":")) + "\n")
        writer = csv.writer(output)
        writer.writerow(
            [
                "sequence",
                "timestamp",
                "angle_deg",
                "raw_word",
                "distance_raw",
                "distance_m",
                "x_m",
                "y_m",
                "flags",
            ]
        )
        for point in scan.points:
            writer.writerow(
                [
                    scan.sequence,
                    scan.timestamp,
                    point.angle_deg,
                    point.raw,
                    point.distance_raw,
                    point.distance_m,
                    point.x,
                    point.y,
                    "|".join(point.flags),
                ]
            )
        return output.getvalue(), "text/csv"
    if kind == "pcd":
        # PCD supports NaN for invalid points; valid field allows explicit filtering.
        lines = [
            "# .PCD v0.7 - Point Cloud Data file format",
            "# metadata=" + json.dumps(common, separators=(",", ":")),
            "VERSION 0.7",
            "FIELDS x y z raw valid",
            "SIZE 4 4 4 4 1",
            "TYPE F F F U U",
            "COUNT 1 1 1 1 1",
            f"WIDTH {scan.count}",
            "HEIGHT 1",
            "VIEWPOINT 0 0 0 1 0 0 0",
            f"POINTS {scan.count}",
            "DATA ascii",
        ]
        for point in scan.points:
            if point.x is None or point.y is None:
                lines.append(f"nan nan nan {point.raw} 0")
            else:
                lines.append(f"{point.x:.6f} {point.y:.6f} 0 {point.raw} 1")
        return "\n".join(lines) + "\n", "application/octet-stream"
    raise ValueError("Export format must be json, csv, or pcd")
