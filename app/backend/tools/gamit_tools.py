"""GAMIT 确定性工具:浏览项目、跑 sh_gamit、解析 summary/q-file/状态。

LLM 只负责编排这些工具;每个工具本身是可单测的纯逻辑(除 run_sh_gamit 真调外部命令)。
解析器对照真实产物校准(experiments/na01/100/)。
"""
import os
import re
import subprocess
from pathlib import Path

GG = os.environ.get("GG_DIR", str(Path.home() / "gg"))


# ----------------------------------------------------------------- 文件浏览
def list_project(project_dir, sub="."):
    root = Path(project_dir).resolve()
    p = (root / sub).resolve()
    if not str(p).startswith(str(root)) or not p.exists():
        return f"ERROR: path not found or outside project: {sub}"
    if p.is_file():
        return f"{sub} 是文件 ({p.stat().st_size} bytes)"
    out = []
    for c in sorted(p.iterdir()):
        out.append(c.name + ("/" if c.is_dir() else f" ({c.stat().st_size}B)"))
    return f"{sub}/ 内容:\n" + "\n".join(out)


def read_file(project_dir, relpath, max_bytes=6000, tail=False):
    root = Path(project_dir).resolve()
    p = (root / relpath).resolve()
    if not str(p).startswith(str(root)) or not p.is_file():
        return f"ERROR: file not found: {relpath}"
    data = p.read_text(errors="replace")
    if len(data) > max_bytes:
        data = (data[-max_bytes:] if tail else data[:max_bytes]) + \
               f"\n... (截断,共 {len(data)} bytes,{'尾部' if tail else '头部'})"
    return f"--- {relpath} ---\n{data}"


# ----------------------------------------------------------------- 状态/诊断
def check_status(project_dir, doy, netext=""):
    """读日目录的 GAMIT.fatal / sh_gamit.log,判断运行结果。先读 fatal(纪律)。"""
    day = Path(project_dir) / f"{int(doy):03d}{netext}"
    res = {"day_dir": str(day), "exists": day.is_dir(), "fatal": None,
           "normal_stop": None, "log_tail": None}
    if not day.is_dir():
        res["error"] = f"日目录不存在: {day}"
        return res
    fatal = day / "GAMIT.fatal"
    if fatal.is_file() and fatal.stat().st_size > 0:
        res["fatal"] = fatal.read_text(errors="replace").strip()
    log = day / "sh_gamit.log"
    if not log.is_file():
        log = Path(project_dir) / "sh_gamit.log"
    if log.is_file():
        tail = log.read_text(errors="replace").splitlines()[-8:]
        res["log_tail"] = "\n".join(tail)
        res["normal_stop"] = any("Normal stop" in l or "Finished at" in l for l in tail)
    return res


# ----------------------------------------------------------------- summary 解析
def parse_summary(project_dir, doy=None, summary_path=None):
    """解析 sh_gamit_<doy>.summary → QC 指标。对照 na01 真实格式校准。"""
    if summary_path is None:
        if doy is None:
            return {"error": "需要 doy 或 summary_path"}
        cands = list(Path(project_dir).rglob(f"sh_gamit_{int(doy):03d}.summary"))
        if not cands:
            return {"error": f"未找到 sh_gamit_{int(doy):03d}.summary"}
        summary_path = cands[0]
    text = Path(summary_path).read_text(errors="replace")
    out = {"summary_path": str(summary_path), "postfit_nrms": None,
           "prefit_nrms": None, "wl_fixed_pct": None, "nl_fixed_pct": None,
           "n_stations": None, "site_rms": {}, "stale_warning": None}

    # 最后一组 prefit/postfit nrms(取所有,用最后一条)
    nrms = re.findall(r"Prefit nrms:\s*([\d.E+-]+)\s+Postfit nrms:\s*([\d.E+-]+)", text)
    if nrms:
        out["prefit_nrms"] = float(nrms[-1][0])
        out["postfit_nrms"] = float(nrms[-1][1])
    m = re.search(r"WL fixed\s+([\d.]+)%\s+NL fixed\s+([\d.]+)%", text)
    if m:
        out["wl_fixed_pct"] = float(m.group(1))
        out["nl_fixed_pct"] = float(m.group(2))
    m = re.search(r"Number of stations used\s+(\d+)", text)
    if m:
        out["n_stations"] = int(m.group(1))
    for site, rms in re.findall(r"RMS\s+\d+\s+([A-Z0-9]{4})\s+([\d.]+)", text):
        if site != "ALL":
            out["site_rms"][site] = float(rms)
    return out


# ----------------------------------------------------------------- q-file 解析
_DMS = re.compile(r"([NSEW])(\d+):(\d+):([\d.]+)")


def _dms_to_deg(s):
    m = _DMS.search(s)
    if not m:
        return None
    sign = -1 if m.group(1) in ("S", "W") else 1
    return sign * (int(m.group(2)) + int(m.group(3)) / 60 + float(m.group(4)) / 3600)


def parse_qfile(qfile_path):
    """解析 q-file 坐标段 → 每站 {lat,lon,radius_km, adj_n,adj_e,adj_u (m), postfit_*}。

    取 'GEOC LAT/GEOC LONG/RADIUS' 行的 a priori、Adjust(m)、Postfit;
    Adjust 的 LAT/LONG/RADIUS ≈ N/E/U 改正(m),供多天 std。
    """
    text = Path(qfile_path).read_text(errors="replace")
    stns = {}
    for line in text.splitlines():
        m = re.match(r"\s*\d+\*([A-Z0-9]{4})\s+(GEOC LAT|GEOC LONG|RADIUS)\s+\S+\s+"
                     r"(\S+)\s+(-?[\d.]+)\s+(-?[\d.]+)\s+(-?[\d.]+)\s+(\S+)", line)
        if not m:
            continue
        site, comp, apriori, adjust, formal, fract, postfit = m.groups()
        d = stns.setdefault(site, {})
        adj = float(adjust)
        if comp == "GEOC LAT":
            d["adj_n"] = adj
            d["lat"] = _dms_to_deg(postfit)
            d["formal_n"] = float(formal)
        elif comp == "GEOC LONG":
            d["adj_e"] = adj
            d["lon"] = _dms_to_deg(postfit)
            d["formal_e"] = float(formal)
        elif comp == "RADIUS":
            d["adj_u"] = adj
            try:
                d["radius_km"] = float(postfit)
            except ValueError:
                pass
            d["formal_u"] = float(formal)
    return {"qfile": str(qfile_path), "stations": stns}


# ----------------------------------------------------------------- 跑 sh_gamit
def run_sh_gamit(project_dir, year, doy, expt, orbit="igsf",
                 extra_opts="-nopngs -copt x k ao -dopt c", noftp=False,
                 timeout=900):
    """从项目目录调用原生 sh_gamit。返回 {returncode, log_tail, fatal, summary}。

    单天:sh_gamit -expt <e> -d <yr> <doy> -orbit <o> <extra>
    """
    project = Path(project_dir).resolve()
    env = dict(os.environ)
    # 确保 GAMIT 命令在 PATH(用户 profile 已配,subprocess 兜底补上)
    for d in (f"{GG}/com", f"{GG}/gamit/bin", f"{GG}/kf/bin"):
        if d not in env.get("PATH", ""):
            env["PATH"] = d + ":" + env.get("PATH", "")
    cmd = f"sh_gamit -expt {expt} -d {year} {int(doy)} -orbit {orbit} {extra_opts}"
    if noftp:
        cmd += " -noftp"
    # 注意:csh 不支持 bash 的 `2>&1` 重定向语法,故不在 shell 里重定向,
    # 改用 capture_output 抓 stdout+stderr,再由 Python 写入 sh_gamit.log。
    try:
        proc = subprocess.run(["csh", "-c", cmd], cwd=str(project), env=env,
                              timeout=timeout, capture_output=True, text=True)
        rc = proc.returncode
    except subprocess.TimeoutExpired:
        return {"error": f"sh_gamit 超时(>{timeout}s)", "returncode": -1}
    try:
        (project / "sh_gamit.log").write_text((proc.stdout or "") + (proc.stderr or ""))
    except Exception:
        pass
    status = check_status(project_dir, doy)
    summary = parse_summary(project_dir, doy) if status.get("fatal") is None else None
    return {"returncode": rc, "cmd": cmd, "fatal": status.get("fatal"),
            "log_tail": status.get("log_tail"), "normal_stop": status.get("normal_stop"),
            "summary": summary}
