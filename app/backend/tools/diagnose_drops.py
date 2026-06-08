"""diagnose_drops — diagnose stations silently dropped by GAMIT/autcln (graceful degradation -> active diagnosis).

When GAMIT encounters a bad station it often does **not** raise a fatal; instead it
removes the station from the solution and keeps running (NoPrefit/NoPostfit, all-zero
adjustments). The network-wide summary then looks fine while in fact stations are
missing and quality is degraded. This tool scans the logs to find the dropped
stations, gathers the evidence (autcln rejection cause / number of observations /
MAKEX warnings / receiver-antenna metadata), and returns a **ranked list of candidate
causes**, turning "silent degradation" into "evidence-backed active diagnosis".

Typical case (knet 16-station from scratch): GKPG (the only Septentrio/SEPCHOKE_B3E6
station) is rejected by autcln with `C R GKPG No Data`; the remaining 15 valid stations
still give nrms 0.186 -- not fatal, but it should be flagged.
"""
import gzip
import re
from pathlib import Path

GG = __import__("os").environ.get("GG_DIR", str(Path.home() / "gg"))


def _read_maybe_gz(p):
    try:
        if str(p).endswith(".gz"):
            with gzip.open(p, "rt", errors="replace") as f:
                return f.read()
        return Path(p).read_text(errors="replace")
    except Exception:
        return ""


def _station_meta(day, project_dir):
    """Read the receiver/antenna of each station from station.info (locating columns
    dynamically from the header to avoid fixed-column slicing misalignment).
    Returns {SITE: {rec, ant}}."""
    meta = {}
    for si in (day / "station.info", Path(project_dir) / "tables" / "station.info"):
        if not si.is_file():
            continue
        lines = si.read_text(errors="replace").splitlines()
        hdr = next((l for l in lines if l.lstrip().startswith("*SITE")), "")
        # start column of each field (fall back to empirical values if not found)
        rc = hdr.find("Receiver Type"); vc = hdr.find("Vers", rc if rc > 0 else 0)
        ac = hdr.find("Antenna Type"); dc = hdr.find("Dome", ac if ac > 0 else 0)
        for ln in lines:
            if ln.startswith(" ") and not ln.lstrip().startswith("*"):
                site = ln[1:5].strip().upper()
                rec = ln[rc:vc].strip() if rc > 0 and vc > rc else ""
                ant = ln[ac:dc].strip() if ac > 0 and dc > ac else ""
                meta.setdefault(site, {"rec": rec, "ant": ant})
        if meta:
            break
    return meta


def diagnose_drops(project_dir, doy, expt=None):
    """-> {n_dropped, dropped:[{site,evidence,reasons,receiver,antenna}], n_stations_kept, note}."""
    day = Path(project_dir) / f"{int(doy):03d}"
    if not day.is_dir():
        return {"error": f"day directory not found {day}"}

    summary = next(iter(day.glob("sh_gamit_*.summary")), None)
    stext = summary.read_text(errors="replace") if summary else ""
    # dropped stations: "<SITE> NoPrefit/NoPostfit" in the summary
    dropped = sorted(set(re.findall(r"\b([A-Z0-9]{4})\s+No(?:Prefit|Postfit)\b", stext)))

    autcln_out = _read_maybe_gz(next(iter(day.glob("autcln.out*")), ""))
    prefit_sum = _read_maybe_gz(next(iter(day.glob("autcln.prefit.sum*")), ""))
    warn = ""
    for w in (day.glob("*.warning")):
        warn += _read_maybe_gz(w)
    log = _read_maybe_gz(Path(project_dir) / "sh_gamit.log")

    meta = _station_meta(day, project_dir)
    kept = sorted(set(meta) - set(dropped))  # actual station set (station.info) minus dropped stations
    # count receiver brands in the network (to flag outliers)
    brands = {}
    for s, m in meta.items():
        b = (m["rec"].split() or [""])[0].upper()
        brands[b] = brands.get(b, 0) + 1

    out = []
    for site in dropped:
        ev, reasons = [], []
        m = meta.get(site, {})
        rec, ant = m.get("rec", ""), m.get("ant", "")

        # autcln rejection cause
        for pat, why in [
            (rf"\bR {site} No Data\b", "autcln found no usable data for the station (zeroed out after double-difference editing)"),
            (rf"Removing {site}.*missing satellite", "autcln: missing common-view satellites, removed from the reference stations"),
            (rf"{site}.*too few", "too few observations"),
        ]:
            mm = re.search(pat, autcln_out)
            if mm:
                ev.append(mm.group(0).strip())
                reasons.append(why)

        # number of observations: obs count where the station first appears in prefit.sum
        pm = re.search(rf"^ {site}\s+([\d.]+)\s+(\d+)", prefit_sum, re.M)
        if pm:
            ev.append(f"autcln.prefit.sum: rms={pm.group(1)} obs={pm.group(2)}")
            if int(pm.group(2)) < 500:
                reasons.append(f"too few raw observations ({pm.group(2)})")

        # antenna phase-center model missing?
        antmod = Path(GG) / "tables" / "antmod.dat"
        if ant and antmod.is_file():
            if ant.split()[0] not in antmod.read_text(errors="replace"):
                reasons.append(f"antenna phase-center model missing: {ant} not in antmod.dat")

        # receiver brand outlier (unique in the network)
        b = (rec.split() or [""])[0].upper()
        if b and brands.get(b, 0) == 1 and len(meta) > 2:
            reasons.append(f"only {b} receiver (all others in the network are other brands) -> suspected RINEX observable-code/signal incompatibility")

        # meaningful MAKEX/MODEL warnings (filter out routine noise such as "Begin processing"/"Started")
        for wm in re.findall(rf"WARNING.*{site}.*", warn + log):
            if re.search(r"zero|few|delet|no data|missing|reject|short|empty|bias", wm, re.I):
                ev.append(wm.strip()[:120])
            if len([e for e in ev if e.startswith("WARNING")]) >= 2:
                break

        if not reasons:
            reasons.append("no clear cause identified; manual inspection of autcln.out / RINEX observable types is recommended")
        out.append({"site": site, "receiver": rec, "antenna": ant,
                    "evidence": ev[:6], "reasons": reasons})

    note = ("No stations were dropped." if not dropped else
            f"{len(dropped)} station(s) silently dropped by GAMIT; {len(kept)} valid station(s) still yield a solution; "
            "the network-wide summary raises no error, so use this to judge whether the result is acceptable or needs fixing.")
    return {"doy": int(doy), "n_dropped": len(dropped), "dropped": out,
            "n_stations_kept": len(kept), "note": note}
