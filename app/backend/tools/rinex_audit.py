"""rinex_audit — RINEX header <-> station.info metadata audit (blind spot 1, pure logic, unit-testable).

Value: GAMIT does not raise an error for an antenna model that is "legal but wrong", yet it
quietly biases the height (in a real project, 8 stations went from height std 44 -> 11 mm).
This tool scans the as-measured antenna/receiver in the RINEX observation headers and compares
them, period by period, against station.info, flagging stations where station.info disagrees
with the hardware ground truth -- exactly the kind of "no-error" problem that costs experts
the most time and is the most valuable to catch.

Reference/benchmark: an operational header-scanning script (header parsing and equipment-change
detection ported from it). Milestone: on the 16 Korean stations, using the original
(uncorrected) station.info, independently reproduce the 8 antenna errors found manually in Phase-5.
"""
import os
import re
import sys
import gzip
import subprocess
from collections import defaultdict


def _open_rinex(filepath):
    """Open a RINEX observation file, transparently supporting .gz / .Z (unix compress).
    Returns a text-line iterable source."""
    fp = str(filepath)
    if fp.endswith(".gz"):
        return gzip.open(fp, "rt", errors="replace")
    if fp.endswith(".Z"):
        # unix compress: decompress to memory via zcat/gunzip (the gzip module does not handle .Z)
        try:
            out = subprocess.run(["zcat", fp], capture_output=True, text=True, timeout=30)
            import io
            return io.StringIO(out.stdout)
        except Exception:
            return open(fp, "r", errors="replace")
    return open(fp, "r", errors="replace")


# ---------------------------------------------------------------- RINEX header parsing
def parse_rinex_header(filepath):
    """Extract receiver/antenna/approximate coordinates/antenna height from the RINEX
    observation file header. Ported from scan_rinex_headers.py."""
    info = {}
    try:
        with _open_rinex(filepath) as f:
            for line in f:
                if "END OF HEADER" in line:
                    break
                if "REC # / TYPE / VERS" in line:
                    info["rec_sn"] = line[0:20].strip()
                    info["rec_type"] = line[20:40].strip()
                    info["rec_vers"] = line[40:60].strip()
                elif "ANT # / TYPE" in line:
                    info["ant_sn"] = line[0:20].strip()
                    info["ant_type"] = line[20:36].strip()
                    info["ant_dome"] = line[36:40].strip()
                elif "APPROX POSITION XYZ" in line:
                    try:
                        info["approx_xyz"] = (float(line[0:14]), float(line[14:28]),
                                              float(line[28:42]))
                    except ValueError:
                        pass
                elif "ANTENNA: DELTA H/E/N" in line:
                    try:
                        info["ant_delta"] = (float(line[0:14]), float(line[14:28]),
                                             float(line[28:42]))
                    except ValueError:
                        pass
    except Exception as e:
        print(f"  read error {filepath}: {e}", file=sys.stderr)
        return None
    return info or None


def detect_segments(records):
    """records=[(year,doy,info),...], already sorted -> segments split at equipment changes.
    Returns [{start:(y,d), end:(y,d), info:{...}}]. Ported from scan_rinex_headers.detect_changes."""
    if not records:
        return []
    segs, cur_key, seg_start, seg_info = [], None, None, None
    prev_y = prev_d = None
    for year, doy, info in records:
        key = (info.get("rec_type", ""), info.get("rec_vers", ""), info.get("rec_sn", ""),
               info.get("ant_type", ""), info.get("ant_dome", ""), info.get("ant_sn", ""))
        if key != cur_key:
            if cur_key is not None:
                segs.append({"start": seg_start, "end": (prev_y, prev_d), "info": seg_info})
            cur_key, seg_start, seg_info = key, (year, doy), info
        prev_y, prev_d = year, doy
    if cur_key is not None:
        segs.append({"start": seg_start, "end": (prev_y, prev_d), "info": seg_info})
    return segs


# ------------------------------------------------------------ station.info parsing
# standard GAMIT column offsets (fallback when the *SITE header is not found)
_DEFAULT_OFFSETS = {"start": 25, "stop": 44, "rec_type": 97, "ant_type": 170,
                    "dome": 187, "ant_sn": 194}


def _header_offsets(header_line):
    o = {}
    for key, label in (("start", "Session Start"), ("stop", "Session Stop"),
                       ("rec_type", "Receiver Type"), ("ant_type", "Antenna Type"),
                       ("dome", "Dome"), ("ant_sn", "Antenna SN")):
        idx = header_line.find(label)
        if idx >= 0:
            o[key] = idx
    return o or None


def _ydoy(region):
    """Extract (year, doy) from the 'Session Start/Stop' column region."""
    toks = region.split()
    if len(toks) >= 2:
        try:
            return (int(toks[0]), int(toks[1]))
        except ValueError:
            return None
    return None


def parse_station_info(path):
    """-> {STN: [{start:(y,d), stop:(y,d), ant_type, dome, rec_type, raw}]}. Dynamic column offsets."""
    entries = defaultdict(list)
    offsets = _DEFAULT_OFFSETS
    with open(path, errors="replace") as f:
        lines = f.readlines()
    for line in lines:
        if line.startswith("*SITE"):
            got = _header_offsets(line)
            if got and "ant_type" in got:
                offsets = {**_DEFAULT_OFFSETS, **got}
            continue
        if line.startswith("*") or line.startswith("#") or not line.strip():
            continue
        stn = line[1:5].strip().upper()
        if not stn:
            continue
        o = offsets
        ant_type = line[o["ant_type"]:o["dome"]].strip() if len(line) > o["ant_type"] else ""
        dome = line[o["dome"]:o["ant_sn"]].strip() if len(line) > o["dome"] else ""
        rec_type = line[o["rec_type"]:o["ant_type"]].strip() if len(line) > o["rec_type"] else ""
        entries[stn].append({
            "start": _ydoy(line[o["start"]:o["stop"]]),
            "stop": _ydoy(line[o["stop"]:o["rec_type"]]),
            "ant_type": ant_type, "dome": dome, "rec_type": rec_type,
            "raw": line.rstrip("\n"),
        })
    return dict(entries)


# ----------------------------------------------------------------------- comparison
def _ydoy_num(t):
    return t[0] * 1000 + t[1] if t else None


def _overlaps(a_start, a_end, b_start, b_stop):
    """Whether the RINEX segment [a_start,a_end] overlaps in time with the station.info
    entry [b_start,b_stop]."""
    a0, a1 = _ydoy_num(a_start), _ydoy_num(a_end)
    b0 = _ydoy_num(b_start) or 0
    b1 = _ydoy_num(b_stop) if b_stop and b_stop[0] < 9999 else 9_999_999
    if a0 is None or a1 is None:
        return False
    return a0 <= b1 and a1 >= b0


def audit_station(stn, rinex_segs, stinfo_entries):
    """Compare a single station. Returns a list of findings (empty = station OK)."""
    findings = []
    for seg in rinex_segs:
        r_ant = seg["info"].get("ant_type", "")
        r_dome = seg["info"].get("ant_dome", "")
        if not r_ant:
            continue
        covering = [e for e in stinfo_entries
                    if _overlaps(seg["start"], seg["end"], e["start"], e["stop"])]
        span = f"{seg['start'][0]}/{seg['start'][1]:03d}-{seg['end'][0]}/{seg['end'][1]:03d}"
        if not covering:
            findings.append({
                "station": stn, "type": "MISSING_PERIOD", "severity": "high",
                "rinex_span": span, "rinex_ant": f"{r_ant} {r_dome}",
                "stinfo_ant": "(no entry covering this period)",
                "detail": f"RINEX shows {r_ant} {r_dome} installed during {span}, but station.info has no entry for this period",
            })
            continue
        # if any covering entry matches the antenna model, treat as OK; otherwise report a mismatch against the first one
        if not any(e["ant_type"] == r_ant for e in covering):
            e = covering[0]
            findings.append({
                "station": stn,
                "type": "ANTENNA_MISMATCH",
                "severity": "high",
                "rinex_span": span,
                "rinex_ant": f"{r_ant} {r_dome}",
                "stinfo_ant": f"{e['ant_type']} {e['dome']}",
                "detail": f"{span}: RINEX antenna {r_ant} {r_dome} != station.info {e['ant_type']} {e['dome']}",
            })
        elif r_dome and not any(e["dome"] == r_dome for e in covering
                                if e["ant_type"] == r_ant):
            e = next(e for e in covering if e["ant_type"] == r_ant)
            findings.append({
                "station": stn, "type": "DOME_MISMATCH", "severity": "low",
                "rinex_span": span, "rinex_ant": f"{r_ant} {r_dome}",
                "stinfo_ant": f"{e['ant_type']} {e['dome']}",
                "detail": f"{span}: antenna model matches but radome {r_dome} != station.info {e['dome']}",
            })
    return findings


def scan_rinex_dir(rinex_dir):
    """Scan a standard GAMIT rinex/ directory (ssssddd[f].yyo) -> {STN: [(year,doy,info)]}.
    For the agent to use directly on ordinary projects (the multi-year HDD layout of the
    milestone uses a separate milestone script)."""
    import os as _os
    recs = defaultdict(list)
    d = str(rinex_dir)
    if not _os.path.isdir(d):
        return {}
    pat = re.compile(r"^([a-zA-Z0-9]{4})(\d{3})\d?\.(\d{2})[oO](\.gz|\.Z)?$")
    for fn in _os.listdir(d):
        m = pat.match(fn)
        if not m:
            continue
        stn = m.group(1).upper()
        doy = int(m.group(2))
        yy = int(m.group(3))
        year = 2000 + yy if yy < 80 else 1900 + yy
        info = parse_rinex_header(_os.path.join(d, fn))
        if info:
            recs[stn].append((year, doy, info))
    for s in recs:
        recs[s].sort()
    return dict(recs)


def audit_project(project_dir, stinfo_rel="tables/station.info", rinex_rel="rinex"):
    """Project-level audit: scan project/rinex/ and compare against project/tables/station.info."""
    import os as _os
    proj = str(project_dir)
    stinfo = _os.path.join(proj, stinfo_rel)
    if not _os.path.isfile(stinfo):
        return {"error": f"station.info not found: {stinfo}"}
    recs = scan_rinex_dir(_os.path.join(proj, rinex_rel))
    if not recs:
        return {"error": f"no parseable RINEX in rinex directory: {_os.path.join(proj, rinex_rel)}"}
    return run_audit(recs, stinfo)


def run_audit(records_by_station, stinfo_path):
    """Core audit: given the per-station RINEX header records + the station.info path -> structured report."""
    stinfo = parse_station_info(stinfo_path)
    report = {"stations": {}, "flagged": [], "findings": []}
    for stn in sorted(records_by_station.keys()):
        segs = detect_segments(records_by_station[stn])
        f = audit_station(stn, segs, stinfo.get(stn, []))
        report["stations"][stn] = {
            "rinex_periods": [
                {"span": f"{s['start'][0]}/{s['start'][1]:03d}-{s['end'][0]}/{s['end'][1]:03d}",
                 "ant": f"{s['info'].get('ant_type','')} {s['info'].get('ant_dome','')}".strip(),
                 "rec": s["info"].get("rec_type", "")}
                for s in segs],
            "stinfo_n": len(stinfo.get(stn, [])),
            "findings": f,
        }
        if f:
            report["flagged"].append(stn)
            report["findings"].extend(f)
    return report
