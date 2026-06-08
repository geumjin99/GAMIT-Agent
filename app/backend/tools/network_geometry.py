"""network_geometry — quick network-geometry health check (feeds the "asymmetric network geometry" error class).

A nine-year operational record shows that changes in the participating station set/distribution
cause systematic height drift of the reference stations (hidden, with no error raised).
This tool computes baseline lengths, network span, nearest-neighbour distances and geometric
outliers from the station coordinates, yielding network-shape health signals: overly long
baselines (beyond the range where a regional solution applies), isolated stations (nearest
neighbour too far -> weak constraint), and an elongated network (north-south / east-west
asymmetry). Deterministic, no network access; coordinates are taken from lfile/apr (geocentric XYZ).
"""
import math
from pathlib import Path

from tools.stations import parse_lfile_xyz, ecef_to_geodetic


def _baseline_km(a, b):
    return math.dist(a, b) / 1000.0


def _project_sites(proj):
    """Stations actually in the project network (read from station.info); lfile often links
    in thousands of stations from the global apr and cannot be used directly."""
    si = proj / "tables" / "station.info"
    out = set()
    if si.is_file():
        for ln in si.read_text(errors="replace").splitlines():
            if ln.startswith(" ") and not ln.lstrip().startswith("*"):
                out.add(ln[1:5].strip().upper())
    return out


def network_geometry(project_dir, long_baseline_km=500.0, isolated_km=200.0):
    """-> {n_stations, baselines{min,max,mean,longest_pair}, span_km, centroid, flags, per_station}.
    long_baseline_km: baseline warning threshold for a regional loose solution;
    isolated_km: nearest-neighbour warning threshold (exceeding it = isolated station)."""
    proj = Path(project_dir)
    lfile = next((p for p in (proj / "tables" / "lfile.",
                              proj / "tables" / "igb20_comb.apr") if p.is_file()), None)
    if not lfile:
        return {"error": "tables/lfile. or apr not found; cannot obtain coordinates"}
    all_xyz = parse_lfile_xyz(str(lfile))
    # keep only stations inside the project network (otherwise lfile's global apr brings an O(n^2) blow-up over thousands of stations)
    net = _project_sites(proj)
    xyz = {s: all_xyz[s] for s in net if s in all_xyz} if net else all_xyz
    if len(xyz) < 2:
        return {"error": f"too few locatable stations in the network ({len(xyz)}); station.info has {len(net)} stations, lfile matched {len(xyz)}",
                "n_stations": len(xyz)}

    sites = sorted(xyz)
    geo = {s: ecef_to_geodetic(*xyz[s]) for s in sites}  # (lat,lon,h)

    # pairwise baselines
    pairs = []
    for i in range(len(sites)):
        for j in range(i + 1, len(sites)):
            d = _baseline_km(xyz[sites[i]], xyz[sites[j]])
            pairs.append((sites[i], sites[j], d))
    dists = [p[2] for p in pairs]
    longest = max(pairs, key=lambda p: p[2])

    # nearest neighbour per station (to flag isolation)
    per = {}
    for s in sites:
        nn = min((d for a, b, d in pairs if s in (a, b)), default=0.0)
        per[s] = {"lat": round(geo[s][0], 5), "lon": round(geo[s][1], 5),
                  "h_m": round(geo[s][2], 2), "nearest_km": round(nn, 2),
                  "isolated": nn > isolated_km}

    lats = [geo[s][0] for s in sites]
    lons = [geo[s][1] for s in sites]
    # span (rough km: 1 deg lat ~= 111km, 1 deg lon ~= 111*cos(lat))
    mlat = sum(lats) / len(lats)
    ns_km = (max(lats) - min(lats)) * 111.0
    ew_km = (max(lons) - min(lons)) * 111.0 * math.cos(math.radians(mlat))

    flags = []
    long_bl = [(a, b, round(d, 1)) for a, b, d in pairs if d > long_baseline_km]
    if long_bl:
        flags.append(f"{len(long_bl)} baseline(s) > {long_baseline_km}km (beyond the usual range of a regional loose solution; long-baseline ambiguities are hard to fix)")
    iso = [s for s in sites if per[s]["isolated"]]
    if iso:
        flags.append(f"isolated station(s) {iso} (nearest neighbour > {isolated_km}km, weak geometric constraint)")
    aspect = (max(ns_km, ew_km) / max(min(ns_km, ew_km), 1e-6))
    if aspect > 3:
        flags.append(f"elongated network (aspect ratio {aspect:.1f}:1), geometric asymmetry -> height drifts more easily with network shape")

    return {
        "n_stations": len(sites),
        "baselines_km": {"min": round(min(dists), 1), "max": round(max(dists), 1),
                         "mean": round(sum(dists) / len(dists), 1),
                         "longest_pair": [longest[0], longest[1], round(longest[2], 1)]},
        "span_km": {"ns": round(ns_km, 1), "ew": round(ew_km, 1), "aspect": round(aspect, 2)},
        "centroid": {"lat": round(mlat, 4), "lon": round(sum(lons) / len(lons), 4)},
        "flags": flags or ["network shape healthy: no long baselines / isolated stations / severe asymmetry"],
        "per_station": per,
    }
