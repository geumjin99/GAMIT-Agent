"""init_project — initialise a runnable GAMIT project from a pile of raw RINEX (automating "the hardest first step for beginners").

The biggest hurdle GAMIT poses to newcomers is hand-writing the full set of control files
(station.info / sestbl. / sittbl. / process.defaults / sites.defaults / apr). This tool
automates that step using GAMIT's own sh_setup / sh_upd_stnfo / sh_rx2apr: given a RINEX
directory + experiment name + year, it produces a project with a complete tables/ that can be
run directly with run_sh_gamit.

Workflow (mirroring sh_gamit's internal conventions):
1. Create <project>/{rinex,tables}; decompress/normalise the RINEX names into rinex/ (ssssddd0.yyo); also collect navigation-file candidates.
2. Lay down process.defaults / sites.defaults / sestbl. / sittbl. / autcln.cmd from gg/tables,
   editing aprf (frame) + the expt name.
3. sh_setup links in apr coordinates / EOP / nutation-luni-solar tables, etc. (frame consistency: IGb20 <-> igb20_comb.apr <-> sittbl.IGb20).
4. Build station.info from the RINEX headers (build_station_info, not relying on the uncompiled mstinf; covers all stations to avoid class-A fatals).
5. Stations not in the global apr (non-IGS private networks) -> sh_rx2apr pseudorange point positioning supplies a priori coordinates, **validated and merged into aprf**.
   Front-loaded self-healing: (1) detect/auto-compile svpos/svdiff (the kf module is often a broken link); (2) brdc local-first fallback chain
   (already in the project -> .Nn shipped with the source data -> sh_get_nav online from SOPAC); (3) a 0,0,0 degenerate-coordinate guardrail.
"""
import os
import re
import gzip
import shutil
import subprocess
from pathlib import Path

from tools.rinex_audit import parse_rinex_header, detect_segments

GG = os.environ.get("GG_DIR", str(Path.home() / "gg"))
GG_TABLES = f"{GG}/tables"

# station.info header (GAMIT new format; column alignment matches the gg template)
_STINFO_HEADER = ("*SITE  Station Name      Session Start      Session Stop       "
                  "Ant Ht   HtCod  Ant N    Ant E    Receiver Type         Vers"
                  "                  SwVer  Receiver SN           Antenna Type     "
                  "Dome   Antenna SN")


# character start position of each header column (computed precisely from the _STINFO_HEADER labels;
# GAMIT reads by fixed columns, so strict alignment is mandatory)
def _col(label):
    return _STINFO_HEADER.find(label)


_COLS = {
    "site": 1, "name": None, "start": None, "stop": None, "antht": None,
    "htcod": None, "antn": None, "ante": None, "rectype": None, "vers": None,
    "swver": None, "recsn": None, "anttype": None, "dome": None, "antsn": None,
}


def _stinfo_line(site, name, seg, is_last):
    """Construct one station.info line at the exact header column positions (fixed-column format,
    so that GAMIT can parse it correctly)."""
    (sy, sd), (ey, ed), info = seg["start"], seg["end"], seg["info"]
    ant_h = info.get("ant_delta", (0, 0, 0))[0]
    # normalise receiver/antenna names to upper case: rcvant.dat is all upper case per IGS convention,
    # while RINEX headers occasionally use mixed case (e.g. SDSM's "Trimble NetR9" -> "TRIMBLE NETR9");
    # otherwise MAKEXP/read_rcvant raises a class-D fatal.
    rec_type = info.get("rec_type", "UNKNOWN")[:20].upper()
    rec_vers = (info.get("rec_vers", "") or "")[:20]
    rec_sn = (info.get("rec_sn", "") or "0000")[:20]
    ant_type = info.get("ant_type", "UNKNOWN")[:16].upper()
    ant_dome = ((info.get("ant_dome", "") or "NONE")[:4]).upper()
    ant_sn = (info.get("ant_sn", "") or "0000")
    m = re.match(r"(\d+\.\d+)", rec_vers)
    swver = m.group(1)[:5] if m else "0.00"
    start = f"{sy:4d} {sd:>3d}  0  0  0"
    stop = "9999 999  0  0  0" if is_last else f"{ey:4d} {ed:>3d} 23 59  0"
    # write each field into the exact column position of a space-filled buffer
    placements = [
        (_col("*SITE") + 1, site[:4]),
        (_col("Station Name"), name[:16]),
        (_col("Session Start"), start),
        (_col("Session Stop"), stop),
        (_col("Ant Ht"), f"{ant_h:7.4f}"),
        (_col("HtCod"), "DHARP"),
        (_col("Ant N"), "0.0000"),
        (_col("Ant E"), "0.0000"),
        (_col("Receiver Type"), rec_type),
        (_col("Vers"), rec_vers),
        (_col("SwVer"), swver),
        (_col("Receiver SN"), rec_sn),
        (_col("Antenna Type"), ant_type),
        (_col("Dome"), ant_dome),
        (_col("Antenna SN"), ant_sn),
    ]
    width = max(c + len(str(t)) for c, t in placements) + 1
    buf = [" "] * width
    for col, text in placements:
        text = str(text)
        buf[col:col + len(text)] = list(text)
    return "".join(buf).rstrip()


def build_station_info(rinex_by_site):
    """Build station.info from the RINEX headers (not relying on the uncompiled mstinf).
    rinex_by_site: {SITE4: [rinex_path, ...]}. Detect equipment-change segments and emit one line per segment."""
    lines = [_STINFO_HEADER]
    n_sites = 0
    for site in sorted(rinex_by_site):
        records = []
        for rp in rinex_by_site[site]:
            info = parse_rinex_header(rp)
            if not info:
                continue
            m = re.search(r"(\d{3})\d?\.(\d{2})[oO]", Path(rp).name)
            if not m:
                continue
            doy = int(m.group(1)); yy = int(m.group(2))
            year = 2000 + yy if yy < 80 else 1900 + yy
            records.append((year, doy, info))
        if not records:
            continue
        records.sort()
        segs = detect_segments(records)
        for i, seg in enumerate(segs):
            lines.append(_stinfo_line(site.upper(), site.upper(), seg, i == len(segs) - 1))
        n_sites += 1
    return "\n".join(lines) + "\n", n_sites


def _env():
    env = dict(os.environ)
    for d in (f"{GG}/com", f"{GG}/gamit/bin", f"{GG}/kf/bin"):
        if d not in env.get("PATH", ""):
            env["PATH"] = d + ":" + env["PATH"]
    return env


def _csh(cmd, cwd, env, timeout=600):
    return subprocess.run(["csh", "-c", cmd], cwd=str(cwd), env=env,
                          capture_output=True, text=True, timeout=timeout)


_RINEX_RE = re.compile(r"^([a-zA-Z0-9]{4})(\d{3})\d?\.(\d{2})[oO](\.gz|\.Z)?$")
# broadcast ephemeris: merged brdcDDD0.YYn or per-station ssssDDD0.YYn (.gz/.Z optional)
_NAV_RE = re.compile(r"^([a-zA-Z0-9]{4})(\d{3})\d?\.(\d{2})[nNgGpP](\.gz|\.Z)?$")


def _check_and_build_svpos(env):
    """sh_rx2apr point positioning depends on svpos/svdiff from kf/svpos. On this machine the
    kf/ module is often not compiled (kf/bin is mostly broken links, while gamit/bin and the
    GLOBK core are fine) -- in that case sh_rx2apr silently outputs 0,0,0. Detect it; if the
    links are broken and the source is present, auto-fix with make. Returns (ok, msg)."""
    bindir = Path(GG) / "kf" / "bin"
    need = ["svpos", "svdiff"]
    # exists() returns False for a broken symlink, which is exactly how we detect "not compiled"
    missing = [b for b in need if not (bindir / b).exists()]
    if not missing:
        return True, "svpos/svdiff already compiled"
    src = Path(GG) / "kf" / "svpos"
    if not (src / "Makefile").is_file():
        return False, f"{missing} missing and no {src}/Makefile; cannot auto-compile; please build the GAMIT kf module manually"
    r = _csh(f"make {' '.join(need)}", src, env, timeout=300)
    still = [b for b in need if not (bindir / b).exists()]
    if still:
        return False, f"auto-compilation of {still} failed rc={r.returncode}: {(r.stderr or r.stdout or '')[-300:]}"
    return True, "auto-compilation of svpos/svdiff completed"


def _decompress_to(src, dst):
    """Copy and decompress a .gz/.Z/plain-text RINEX/nav file to dst."""
    src = Path(src)
    if src.name.endswith(".gz"):
        with gzip.open(src, "rb") as fi, open(dst, "wb") as fo:
            shutil.copyfileobj(fi, fo)
    elif src.name.endswith(".Z"):
        r = subprocess.run(["zcat", str(src)], capture_output=True, timeout=60)
        Path(dst).write_bytes(r.stdout)
    else:
        shutil.copyfile(src, dst)


def _ensure_brdc(proj, nav_candidates, yy, ddd, year, env):
    """Prepare a usable broadcast ephemeris for sh_rx2apr; return the nav file Path or None.
    Fallback chain (local first):
      (1) project/brdc/brdcDDD0.YYn already present -> use it;
      (2) navigation file in the source data (CORS raw .o files often ship with a .n alongside)
          -> prefer brdc*, otherwise any station .YYn; decompress and use;
      (3) fetch online with sh_get_nav (anonymous SOPAC, the preferred source) -> place into brdc/;
      (4) on failure return None (the caller skips and warns; a CDDIS download could be chained next)."""
    brdc = proj / "brdc"
    brdc.mkdir(exist_ok=True)
    target = brdc / f"brdc{ddd}0.{yy}n"
    # (1)
    if target.is_file() and target.stat().st_size > 1000:
        return target
    # (2): among candidates prefer the merged brdc, otherwise any station .YYn
    cands = sorted(nav_candidates,
                   key=lambda p: (not Path(p).name.lower().startswith("brdc"), Path(p).name))
    for c in cands:
        m = _NAV_RE.match(Path(c).name)
        if m and m.group(3) == yy:
            try:
                _decompress_to(c, target)
                if target.stat().st_size > 1000:
                    return target
            except Exception:
                continue
    # (3): sh_get_nav online (SOPAC)
    r = _csh(f"sh_get_nav -archive sopac -yr {year} -doy {ddd}", brdc, env, timeout=180)
    got = next((p for p in brdc.glob(f"brdc{ddd}0.{yy}n*")), None)
    if got and got != target:
        if got.name.endswith((".gz", ".Z")):
            _decompress_to(got, target)
        else:
            got.rename(target)
    if target.is_file() and target.stat().st_size > 1000:
        return target
    return None


def _valid_xyz(x, y, z):
    """sh_rx2apr guardrail: coordinates must be non-zero and have a magnitude near the Earth's
    surface (reject degenerate values such as 0,0,0)."""
    try:
        x, y, z = float(x), float(y), float(z)
    except (TypeError, ValueError):
        return False
    r = (x * x + y * y + z * z) ** 0.5
    return r > 6.0e6 and r < 6.6e6


def _stage_rinex(src_files, rinex_dir):
    """Decompress/copy the RINEX into rinex/, normalised to ssssddd0.yyo (lower-case station name).
    Returns (staged file names, station set)."""
    staged, sites = [], set()
    for src in src_files:
        src = Path(src)
        m = _RINEX_RE.match(src.name)
        if not m:
            continue
        site, doy, yy = m.group(1).lower(), m.group(2), m.group(3)
        out = Path(rinex_dir) / f"{site}{doy}0.{yy}o"
        if src.name.endswith(".gz"):
            with gzip.open(src, "rb") as fi, open(out, "wb") as fo:
                shutil.copyfileobj(fi, fo)
        elif src.name.endswith(".Z"):
            r = subprocess.run(["zcat", str(src)], capture_output=True, timeout=60)
            out.write_bytes(r.stdout)
        else:
            shutil.copyfile(src, out)
        staged.append(out.name)
        sites.add(site[:4])
    return staged, sites


def _seed_control_files(tables, expt, aprf, sittbl_variant="sittbl.IGb20"):
    """Lay down the minimal control-file set from gg/tables, editing the expt name + aprf."""
    copied = []
    # process.defaults
    pd_src = Path(GG_TABLES) / "process.defaults"
    pd = Path(tables) / "process.defaults"
    if pd_src.is_file():
        txt = pd_src.read_text()
        txt = re.sub(r"set aprf\s*=\s*\S+", f"set aprf = {aprf}", txt)
        pd.write_text(txt)
        copied.append("process.defaults")
    # sites.defaults: write a clean version keeping only all_sites (local RINEX stations used
    # automatically), without copying the example ftp stations from the gg template (brus/graz/sofi)
    # -- otherwise GAMIT would try to process them with no entry -> fatal.
    sd = (f"# generated by gamit-agent init_project for expt '{expt}'\n"
          f"# all stations under local rinex/ processed automatically; xstinfo = use our own station.info, do not auto-edit\n"
          f" all_sites {expt} xstinfo\n")
    (Path(tables) / "sites.defaults").write_text(sd)
    copied.append("sites.defaults")
    # copy sestbl. / autcln.cmd as-is; use the sittbl variant consistent with the frame
    for name, dst in [("sestbl.", "sestbl."), ("autcln.cmd", "autcln.cmd"),
                      (sittbl_variant, "sittbl.")]:
        s = Path(GG_TABLES) / name
        if s.is_file():
            shutil.copyfile(s, Path(tables) / dst)
            copied.append(dst)
    return copied


def init_project(project_dir, expt, year, rinex_src, doy=None,
                 apr="igb20_comb.apr", frame="IGb20", series="usno", run_setup=True):
    """Initialise a GAMIT project from raw RINEX.

    rinex_src: a RINEX directory, or a list of RINEX file paths.
    Returns {project, expt, rinex: [...], sites: [...], tables: [...], station_info_n,
          missing_apr: [...], steps: [...], ready: bool, error?}
    """
    proj = Path(project_dir).resolve()
    rinex_dir = proj / "rinex"
    tables = proj / "tables"
    rinex_dir.mkdir(parents=True, exist_ok=True)
    tables.mkdir(parents=True, exist_ok=True)
    env = _env()
    steps = []

    # 1. collect source RINEX (also collect navigation-file candidates, for sh_rx2apr's brdc local-first)
    nav_candidates = []
    if isinstance(rinex_src, (list, tuple)):
        all_src = [Path(p) for p in rinex_src]
        src_files = [p for p in all_src if _RINEX_RE.match(p.name)]
        nav_candidates = [p for p in all_src if _NAV_RE.match(p.name)]
    else:
        s = Path(rinex_src)
        if s.is_dir():
            entries = list(s.iterdir())
            src_files = [p for p in entries if _RINEX_RE.match(p.name)]
            nav_candidates = [p for p in entries if _NAV_RE.match(p.name)]
        else:
            src_files = []
    if not src_files:
        return {"error": f"no recognisable RINEX found (ssssddd[f].yyo[.gz/.Z]): {rinex_src}"}
    staged, sites = _stage_rinex(src_files, rinex_dir)
    if not staged:
        return {"error": "RINEX names do not match ssssddd0.yyo and cannot be recognised"}
    steps.append(f"staged {len(staged)} RINEX, {len(sites)} station(s)")

    # 2. lay down control files
    sittbl_variant = f"sittbl.{frame}" if (Path(GG_TABLES) / f"sittbl.{frame}").is_file() else "sittbl."
    copied = _seed_control_files(tables, expt, apr, sittbl_variant)
    steps.append("laid down control files: " + ", ".join(copied))

    # 3. sh_setup links in apr/eop/nutation-luni-solar tables
    if run_setup:
        yy = int(year)
        cmd = f"sh_setup -yr {yy} -expt {expt} -apr {apr} -series {series}"
        r = _csh(cmd, proj, env)
        steps.append(f"sh_setup rc={r.returncode}")

    # 4. station.info <- RINEX headers (self-built, not relying on the uncompiled mstinf)
    rinex_by_site = {}
    for n in staged:
        rinex_by_site.setdefault(n[:4], []).append(str(rinex_dir / n))
    si_text, si_n = build_station_info(rinex_by_site)
    (tables / "station.info").write_text(si_text)
    steps.append(f"station.info <- self-built from RINEX headers, {si_n} station(s)")

    # count the stations covered by station.info
    si = tables / "station.info"
    si_sites = set()
    if si.is_file():
        for ln in si.read_text(errors="replace").splitlines():
            if ln.startswith(" ") and not ln.startswith("*"):
                si_sites.add(ln[1:5].strip().upper())

    # 5. stations not in the global apr -> sh_rx2apr supplies a priori coordinates
    apr_path = tables / apr
    if not apr_path.is_file():
        apr_path = Path(GG_TABLES) / apr
    apr_sites = set()
    if apr_path.is_file():
        for ln in apr_path.read_text(errors="replace").splitlines():
            m = re.match(r"\s*([A-Z0-9]{4})_\w+", ln)
            if m:
                apr_sites.add(m.group(1).upper())
    missing = sorted(s.upper() for s in sites if s.upper() not in apr_sites)
    rx2apr = {"requested": missing, "solved": [], "rejected": [], "brdc": None, "svpos": None}
    # target apr to write to (prefer the in-project one; sh_setup usually already copies one into tables)
    aprf_path = tables / apr if (tables / apr).is_file() else (Path(GG_TABLES) / apr)
    if missing:
        # front-load: ensure the point-positioning programs svpos/svdiff are compiled (the kf module is often a broken link on this machine -> otherwise it silently outputs 0,0,0)
        ok_sv, msg_sv = _check_and_build_svpos(env)
        rx2apr["svpos"] = msg_sv
        # determine the target day (take the DOY/YY of the first staged file) and prepare the broadcast ephemeris for sh_rx2apr
        m0 = _RINEX_RE.match(staged[0])
        ddd, yy = m0.group(2), m0.group(3)
        nav = _ensure_brdc(proj, nav_candidates, yy, ddd, int(year), env)
        rx2apr["brdc"] = str(nav) if nav else None
        if not ok_sv or nav is None:
            steps.append(f"sh_rx2apr skipped: svpos={msg_sv}; brdc={'ready' if nav else 'unavailable'}; "
                         f"a priori coordinates missing for non-IGS stations {missing}, manual entry required")
        else:
            nav_rel = f"../brdc/{nav.name}"
            new_lines = []
            for ms in missing:
                rfile = next((n for n in staged if n[:4].lower() == ms.lower()), None)
                if not rfile:
                    continue
                _csh(f"sh_rx2apr -site ../rinex/{rfile} -nav {nav_rel} -apr {apr}",
                     tables, env, timeout=300)
                # parse {site}.apr and validate the coordinates against the guardrail (reject degenerate 0,0,0)
                ap = tables / f"{ms.lower()}.apr"
                line = None
                if ap.is_file():
                    for ln in ap.read_text(errors="replace").splitlines():
                        parts = ln.split()
                        if len(parts) >= 4 and parts[0].upper().startswith(ms):
                            if _valid_xyz(parts[1], parts[2], parts[3]):
                                line = ln.rstrip()
                            break
                if line:
                    new_lines.append(line)
                    rx2apr["solved"].append(ms)
                else:
                    rx2apr["rejected"].append(ms)
            # merge into the target apr (GAMIT reads aprf when building the lfile) -- fixes the earlier bug where orphan {site}.apr files had no effect
            if new_lines and aprf_path.is_file():
                with open(aprf_path, "a") as fo:
                    fo.write("\n" + "\n".join(new_lines) + "\n")
            steps.append(f"sh_rx2apr a priori: solved {rx2apr['solved']}"
                         + (f", rejected (anomalous coordinates) {rx2apr['rejected']}" if rx2apr["rejected"] else "")
                         + f" -> merged into {aprf_path.name}")

    # ready requires every non-IGS station to have its coordinates supplied (otherwise GAMIT fails for lack of a priori)
    unresolved = [s for s in missing if s not in rx2apr["solved"]]
    ready = (si.is_file() and len(si_sites) >= len(sites)
             and (tables / "process.defaults").is_file() and not unresolved)
    return {
        "project": str(proj), "expt": expt, "year": int(year),
        "rinex": staged, "sites": sorted(sites),
        "tables": [p.name for p in tables.iterdir()],
        "station_info_n": len(si_sites),
        "missing_apr": missing,
        "rx2apr": rx2apr,
        "unresolved_apr": unresolved,
        "steps": steps,
        "ready": bool(ready),
        "hint": ("ready=True means run_sh_gamit can be run directly." if ready else
                 f"ready=False: non-IGS stations {unresolved} lack trustworthy a priori coordinates (svpos not compiled / brdc unavailable / "
                 f"point-positioning anomaly rejected by the guardrail); verify manually before running, see the rx2apr field."),
    }
