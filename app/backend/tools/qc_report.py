"""qc_report — one-stop QC verdict for a single-day solution (the wrap-up tool of the agent's reporting layer (4)).

Synthesises scattered signals into an operator-readable health verdict:
  postfit nrms / WL and NL fixing rates (parse_summary)
  + silently dropped stations (diagnose_drops)
  + network geometry (network_geometry)
  + "legal but wrong" antenna audit (rinex_audit)
-> verdict: pass / warn / fail + specific reasons + suggested next tools.

Criteria (empirical thresholds, see skill/references/qc.md):
  postfit nrms <=0.25 excellent / <=0.35 acceptable / >0.5 poor; WL >=90%, NL >=80% is healthy.
"""
from tools.gamit_tools import parse_summary
from tools.diagnose_drops import diagnose_drops
from tools.network_geometry import network_geometry
from tools.rinex_audit import audit_project


def qc_report(project_dir, doy, expt=None):
    reasons, warns, suggest = [], [], []
    verdict = "pass"

    s = parse_summary(project_dir, doy)
    if s.get("error"):
        return {"verdict": "fail", "reasons": [f"cannot read summary: {s['error']}"],
                "suggest": ["check_status to inspect GAMIT.fatal"]}

    nrms = s.get("postfit_nrms")
    wl, nl = s.get("wl_fixed_pct"), s.get("nl_fixed_pct")
    if nrms is None:
        verdict = "fail"; reasons.append("summary has no postfit nrms (possibly stale/aborted)")
        suggest.append("check_status to inspect fatal first")
    else:
        if nrms > 0.5:
            verdict = "fail"; reasons.append(f"postfit nrms {nrms} too high (>0.5)")
        elif nrms > 0.35:
            verdict = max(verdict, "warn", key=["pass", "warn", "fail"].index)
            warns.append(f"postfit nrms {nrms} elevated (0.35-0.5)")
    if wl is not None and wl < 90:
        warns.append(f"WL fixing rate {wl}% low (<90%)")
    if nl is not None and nl < 80:
        warns.append(f"NL fixing rate {nl}% low (<80%)")

    # silently dropped stations
    dr = diagnose_drops(project_dir, doy, expt=expt)
    if dr.get("n_dropped", 0) > 0:
        verdict = max(verdict, "warn", key=["pass", "warn", "fail"].index)
        sites = [d["site"] for d in dr.get("dropped", [])]
        warns.append(f"{dr['n_dropped']} station(s) silently dropped: {sites} (network-wide nrms does not reflect this)")
        suggest.append("diagnose_drops to see the rejection cause per station")

    # network geometry
    ng = network_geometry(project_dir)
    geo_flags = [f for f in ng.get("flags", []) if "healthy" not in f]
    if geo_flags:
        verdict = max(verdict, "warn", key=["pass", "warn", "fail"].index)
        warns.extend(geo_flags)

    # "legal but wrong" antenna audit
    au = audit_project(project_dir)
    if au.get("flagged"):
        verdict = max(verdict, "warn", key=["pass", "warn", "fail"].index)
        warns.append(f"stations with questionable antenna metadata: {au['flagged']} (no error raised, but height may be biased)")
        suggest.append("rinex_audit to compare antenna models; multiday_std to inspect multi-day height std")

    return {
        "doy": int(doy), "verdict": verdict,
        "metrics": {"postfit_nrms": nrms, "wl_fixed_pct": wl, "nl_fixed_pct": nl,
                    "n_stations": s.get("n_stations"), "n_dropped": dr.get("n_dropped", 0)},
        "reasons": reasons or ["core metrics within spec"],
        "warnings": warns,
        "suggest": suggest or ["no further action needed"],
        "note": {"pass": "Solution is healthy and usable.", "warn": "Solution is usable but has items to watch, see warnings.",
                 "fail": "Solution is not trustworthy and must be fixed first."}[verdict],
    }
