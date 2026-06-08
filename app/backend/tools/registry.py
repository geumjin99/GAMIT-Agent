"""Tool registry: expose the deterministic tools to the LLM agent (name -> callable + a description for the system prompt).

A toolkit bound to the project_dir context: .run(action, args) dispatches,
and .descriptions is injected into the system prompt.
"""
import json

from tools import gamit_tools as gt
from tools import rinex_audit as ra
from tools import multiday_std as ms
from tools import stations as st
from tools import globk_frame as gf
from tools import init_project as ip
from tools import diagnose_drops as dd
from tools import network_geometry as ng
from tools import qc_report as qr
import gamit_rag as grag


TOOL_DESCRIPTIONS = """
init_project: initialise a runnable GAMIT project from a pile of raw RINEX (auto-generate station.info/sites.defaults/process.defaults/sestbl/sittbl + link in apr/eop). Use when the user has only RINEX and the project has no tables/ yet. Args: {"expt":"abcd","year":2023,"rinex_src":"<RINEX directory or file list>","apr":"igb20_comb.apr","frame":"IGb20"}
list_project: list the contents of a project directory/subdirectory. Args: {"sub": "relative path, default '.'"}
read_file: read a file inside the project (truncated). Args: {"relpath": "relative path, e.g. '100/GAMIT.fatal'", "tail": false}
check_status: read a given day's GAMIT.fatal / sh_gamit.log to judge the run result (inspect fatal first). Args: {"doy": 100}
parse_summary: parse a given day's sh_gamit_<doy>.summary -> nrms/WL/NL/number of stations. Args: {"doy": 100}
parse_qfile: parse a given day's q-file for per-station coordinates and N/E/U adjustments. Args: {"doy": 100}
run_sh_gamit: actually run native sh_gamit for a single-day solution. Args: {"year":2023,"doy":100,"expt":"na01","orbit":"igsf","extra_opts":"-nopngs -copt x k ao -dopt c","noftp":false}
rinex_audit: audit RINEX header <-> station.info and report "legal but wrong" antennas (the kind that bias height with no error raised). Args: {} (scans project/rinex/ against tables/station.info)
multiday_std: multi-day per-station coordinate std (mm); high-std stations = a signal of metadata problems. Args: {"expt":"na01","doys":null}
globk_frame: GLOBK multi-station Helmert frame solution (fixes loose-solution height drift/bimodality). Args: {"expt":"knet","frame_sites":["DAEJ",...]} (heavy, optional)
diagnose_drops: diagnose stations silently dropped by GAMIT/autcln (NoPrefit/NoPostfit) -> evidence + ranked candidate causes. Mandatory when a solution is produced but the station count is lower than expected. Args: {"doy": 100}
network_geometry: quick network-geometry health check (baseline length/network span/isolated stations/elongated asymmetry) -> feeds hidden problems such as "height drifts with network shape". Args: {} (reads the in-network stations of tables/lfile.)
qc_report: one-stop QC verdict for a single-day solution (synthesises nrms/WL/NL + silently dropped stations + network shape + antenna audit) -> verdict pass/warn/fail + reasons + suggested tools. Use when producing a report. Args: {"doy": 100}
gamit_help: search the official GAMIT/GLOBK manuals (135 .hlp + sh_* scripts, local BM25). Query it when unsure of a command's options/usage; do not make them up from memory. Args: {"query":"how to set the autcln elevation cutoff","command":"autcln (optional, restrict to a command)","k":5}
finish: provide the final QC/diagnostic report and stop. Args: {"summary":"...","status":"pass|fail|need_human","details":{...}}
"""


class GamitToolkit:
    def __init__(self, project_dir):
        self.project_dir = str(project_dir)
        self.descriptions = TOOL_DESCRIPTIONS

    def _qfile_for(self, doy):
        from pathlib import Path
        for p in Path(self.project_dir).rglob(f"q*a.{int(doy):03d}"):
            return str(p)
        return None

    def run(self, action, args):
        pd = self.project_dir
        try:
            if action == "init_project":
                return _fmt(ip.init_project(
                    pd, args["expt"], args["year"], args["rinex_src"],
                    apr=args.get("apr", "igb20_comb.apr"),
                    frame=args.get("frame", "IGb20")))
            if action == "list_project":
                return gt.list_project(pd, args.get("sub", "."))
            if action == "read_file":
                return gt.read_file(pd, args.get("relpath", ""), tail=args.get("tail", False))
            if action == "check_status":
                return _fmt(gt.check_status(pd, args["doy"]))
            if action == "parse_summary":
                return _fmt(gt.parse_summary(pd, args.get("doy")))
            if action == "parse_qfile":
                qf = self._qfile_for(args["doy"])
                if not qf:
                    return f"ERROR: no q-file found for doy {args.get('doy')}"
                return _fmt(gt.parse_qfile(qf))
            if action == "run_sh_gamit":
                return _fmt(gt.run_sh_gamit(
                    pd, args["year"], args["doy"], args["expt"],
                    orbit=args.get("orbit", "igsf"),
                    extra_opts=args.get("extra_opts", "-nopngs -copt x k ao -dopt c"),
                    noftp=args.get("noftp", False)))
            if action == "rinex_audit":
                return _fmt(ra.audit_project(pd, rinex_rel=args.get("rinex_rel", "rinex")))
            if action == "multiday_std":
                return _fmt(ms.multiday_std(pd, args.get("expt"), args.get("doys")))
            if action == "globk_frame":
                return _fmt(gf.globk_frame(pd, args.get("expt"),
                                          frame_sites=args.get("frame_sites")))
            if action == "diagnose_drops":
                return _fmt(dd.diagnose_drops(pd, args["doy"], expt=args.get("expt")))
            if action == "network_geometry":
                return _fmt(ng.network_geometry(pd))
            if action == "qc_report":
                return _fmt(qr.qc_report(pd, args["doy"], expt=args.get("expt")))
            if action == "gamit_help":
                return _fmt(grag.gamit_help(args.get("query", ""),
                                            k=args.get("k", 5), command=args.get("command")))
            if action == "stations_geojson":
                return _fmt(st.stations_geojson(pd, expt=args.get("expt")))
            return f"ERROR: unknown tool '{action}'"
        except KeyError as e:
            return f"ERROR: missing argument {e}"
        except Exception as e:
            return f"ERROR: tool {action} failed: {e}"


def _fmt(obj):
    if isinstance(obj, str):
        return obj
    return json.dumps(obj, ensure_ascii=False, indent=1, default=str)
