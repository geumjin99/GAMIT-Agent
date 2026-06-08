"""stations — produce station GeoJSON for the front-end map (lat/lon + metadata + audit/std status).

Coordinate source priority: post-solution geodetic coordinates from the q-file > geocentric
XYZ from lfile/apr > APPROX POSITION from the RINEX header.
Marker colour is determined by status: ok (green) / antenna_mismatch (red) / high_std (yellow) / unsolved (grey).
"""
import math
import re
from pathlib import Path

from tools.gamit_tools import parse_qfile

# WGS84
_A = 6378137.0
_F = 1 / 298.257223563
_E2 = _F * (2 - _F)
_B = _A * (1 - _F)
_EP2 = (_A ** 2 - _B ** 2) / _B ** 2


def ecef_to_geodetic(x, y, z):
    """ECEF (m) -> (lat_deg, lon_deg, h_m). Bowring closed-form solution -- using the
    **geodetic latitude**, avoiding a known bug where feeding the geocentric latitude
    into the ellipsoid radius formula biased the height by ~65 m."""
    lon = math.atan2(y, x)
    p = math.hypot(x, y)
    theta = math.atan2(z * _A, p * _B)
    lat = math.atan2(z + _EP2 * _B * math.sin(theta) ** 3,
                     p - _E2 * _A * math.cos(theta) ** 3)
    N = _A / math.sqrt(1 - _E2 * math.sin(lat) ** 2)
    h = p / math.cos(lat) - N
    return math.degrees(lat), math.degrees(lon), h


def geocentric_to_geodetic(lat_gc_deg, lon_deg, radius_km):
    """q-file GEOC LAT (geocentric latitude) + RADIUS (geocentric radius) -> geodetic (lat,lon,h).
    Must convert to ECEF first and then to geodetic; otherwise treating the geocentric latitude
    directly as the geodetic latitude biases it by ~0.19 deg and the height by tens of thousands of metres."""
    latc = math.radians(lat_gc_deg)
    lon = math.radians(lon_deg)
    r = radius_km * 1000.0
    x = r * math.cos(latc) * math.cos(lon)
    y = r * math.cos(latc) * math.sin(lon)
    z = r * math.sin(latc)
    return ecef_to_geodetic(x, y, z)


def parse_lfile_xyz(lfile_path):
    """lfile/apr -> {STN: (X,Y,Z)}. Station names look like ALBH_GPS; take the first 4 characters."""
    out = {}
    if not Path(lfile_path).is_file():
        return out
    for line in Path(lfile_path).read_text(errors="replace").splitlines():
        if line.startswith(("#", "+", "*", "-")) or not line.strip():
            continue
        toks = line.split()
        if len(toks) < 4:
            continue
        name = toks[0]
        stn = name.split("_")[0][:4].upper()
        try:
            x, y, z = float(toks[1]), float(toks[2]), float(toks[3])
        except ValueError:
            continue
        out.setdefault(stn, (x, y, z))   # keep first occurrence
    return out


def _coords_from_qfile(project_dir, expt):
    """Obtain per-station geodetic lat/lon from any available q-file (post-solution, best)."""
    qs = sorted(Path(project_dir).rglob(f"q{expt}a.*"),
                key=lambda p: p.name)
    for qp in qs:
        if qp.suffix.lstrip(".").isdigit():
            q = parse_qfile(qp)
            coords = {}
            for stn, d in q["stations"].items():
                # the q-file gives geocentric latitude + geocentric radius -> must convert to geodetic
                if d.get("lat") is not None and d.get("radius_km"):
                    coords[stn] = geocentric_to_geodetic(d["lat"], d["lon"], d["radius_km"])
            if coords:
                return coords
    return {}


def stations_geojson(project_dir, expt=None, audit_report=None, std_report=None):
    """Aggregate station coordinates + status -> GeoJSON FeatureCollection."""
    project = Path(project_dir)
    coords = {}
    if expt:
        coords = _coords_from_qfile(project_dir, expt)
    if not coords:
        # fall back to lfile/apr
        for cand in ["tables/lfile.", "tables/lfile", "lfile."]:
            xyz = parse_lfile_xyz(project / cand)
            if xyz:
                coords = {s: ecef_to_geodetic(*v) for s, v in xyz.items()}
                break

    audit_flagged = set((audit_report or {}).get("flagged", []))
    std_flagged = set((std_report or {}).get("flagged", []))
    audit_stations = (audit_report or {}).get("stations", {})
    std_stations = (std_report or {}).get("stations", {})

    feats = []
    for stn, (lat, lon, h) in sorted(coords.items()):
        if stn in audit_flagged:
            status = "antenna_mismatch"
        elif stn in std_flagged:
            status = "high_std"
        else:
            status = "ok"
        props = {
            "station": stn, "status": status,
            "height_m": round(h, 3) if h is not None else None,
            "audit_findings": audit_stations.get(stn, {}).get("findings", []),
            "std_u_mm": std_stations.get(stn, {}).get("std_u_mm"),
        }
        feats.append({"type": "Feature",
                      "geometry": {"type": "Point", "coordinates": [round(lon, 6), round(lat, 6)]},
                      "properties": props})
    return {"type": "FeatureCollection", "features": feats,
            "meta": {"project": str(project), "expt": expt, "n": len(feats)}}
