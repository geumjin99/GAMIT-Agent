"""multiday_std — multi-day, per-station coordinate standard deviation (blind spot 2).

Lesson from real projects: single-day nrms is a "process" metric; what really exposes
problems such as a "legal but wrong antenna" is the **multi-day per-station coordinate
scatter** (height std). This tool collects the per-station N/E/U adjustments from
multiple-day q-files and computes the std (mm) per station; high-std stations serve as a
signal of metadata problems (then handed to rinex_audit for localisation).

Note: a q-file is a loosely constrained single-day solution, so the absolute height drifts
with the network shape (which is exactly what globk_frame fixes); hence this std is a
"relative scatter signal", sufficient to flag anomalies, while absolute height accuracy
requires a GLOBK frame solution.
"""
import statistics
from pathlib import Path

from tools.gamit_tools import parse_qfile


def _find_qfiles(project_dir, expt, doys=None):
    """Find q<expt>a.<doy>. When doys=None take all of them. Returns {doy:int -> path}."""
    root = Path(project_dir)
    out = {}
    for p in root.rglob(f"q{expt}a.*"):
        suf = p.suffix.lstrip(".")
        if suf.isdigit():
            doy = int(suf)
            if doys is None or doy in set(doys):
                out[doy] = p
    return dict(sorted(out.items()))


def multiday_std(project_dir, expt, doys=None, high_std_mm=15.0):
    """-> per-station multi-day N/E/U std (mm) + anomaly flag. high_std_mm: height-std warning threshold."""
    qfiles = _find_qfiles(project_dir, expt, doys)
    if not qfiles:
        return {"error": f"q{expt}a.<doy> files not found", "n_days": 0}

    # collect per-station, per-day N/E/U adjustments (m)
    series = {}   # stn -> {"n":[], "e":[], "u":[], "days":[]}
    for doy, qp in qfiles.items():
        q = parse_qfile(qp)
        for stn, d in q["stations"].items():
            s = series.setdefault(stn, {"n": [], "e": [], "u": [], "days": []})
            if d.get("adj_n") is not None:
                s["n"].append(d["adj_n"]); s["e"].append(d.get("adj_e", 0.0))
                s["u"].append(d.get("adj_u", 0.0)); s["days"].append(doy)

    report = {"n_days": len(qfiles), "doys": list(qfiles.keys()),
              "stations": {}, "flagged": []}
    for stn, s in sorted(series.items()):
        n = len(s["u"])
        def std_mm(vals):
            return round(statistics.pstdev(vals) * 1000, 2) if len(vals) > 1 else 0.0
        std_u, std_n, std_e = std_mm(s["u"]), std_mm(s["n"]), std_mm(s["e"])
        flagged = std_u >= high_std_mm
        report["stations"][stn] = {
            "n_days": n, "std_n_mm": std_n, "std_e_mm": std_e, "std_u_mm": std_u,
            "flagged_high_u": flagged,
        }
        if flagged:
            report["flagged"].append(stn)
    return report
