"""GAMIT-Agent 后端工具回归测试。

用项目里已有的真实实验数据当只读 fixture,断言已校准的真值。数据缺失时整组 skip
(而非报错),保证套件在裸机/CI 上仍可运行。

数据目录(只读,勿改):
  FULL16  —— 16 站完整项目(expt=kf16, doy=100)
  MULTIDAY —— 30 天 q-file(expt=knet)
  RX2APR  —— 4 站项目(expt=kfrs, doy=100)
"""
import os

import pytest

# conftest.py 已把 app/backend 加入 sys.path
from tools.diagnose_drops import diagnose_drops
from tools.network_geometry import network_geometry
from tools.qc_report import qc_report
from tools.multiday_std import multiday_std
from tools.rinex_audit import parse_rinex_header
from tools.init_project import build_station_info, _valid_xyz
from tools.gamit_tools import parse_summary, parse_qfile

# ----------------------------------------------------------------- 数据路径常量
# Point GAMIT_EXPERIMENTS at your local experiments directory to run these
# fixture-dependent tests; they are skipped when the data is not present.
_EXP = os.environ.get("GAMIT_EXPERIMENTS", os.path.expanduser("~/GAMITagent/experiments"))
FULL16 = os.path.join(_EXP, "knet_full16_fresh")
MULTIDAY = os.path.join(_EXP, "knet_multiday_std")
RX2APR = os.path.join(_EXP, "knet_rx2apr_fresh")

SDSM_RINEX = os.path.join(FULL16, "rinex", "sdsm1000.23o.gz")
FULL16_QFILE = os.path.join(FULL16, "100", "qkf16a.100")


def _require(path):
    """目录/文件不存在则优雅 skip。"""
    if not os.path.exists(path):
        pytest.skip(f"缺真实数据 fixture: {path}")


# ----------------------------------------------------------------- 1. diagnose_drops
def test_diagnose_drops_gkpg_septentrio():
    _require(FULL16)
    res = diagnose_drops(FULL16, 100)
    assert res.get("n_dropped") == 1, res
    sites = [d["site"] for d in res["dropped"]]
    assert "GKPG" in sites
    gkpg = next(d for d in res["dropped"] if d["site"] == "GKPG")
    # GKPG 是唯一 Septentrio 站,RINEX 头接收机为 "SEPT POLARX5"
    assert "SEPT" in gkpg["receiver"], gkpg["receiver"]
    # the reasons should mention one of "Septentrio" / "No Data" (zeroed out) / "only ... receiver"
    reasons_blob = " ".join(gkpg["reasons"])
    assert ("Septentrio" in reasons_blob
            or "zeroed out" in reasons_blob       # autcln No Data -> "zeroed out after double-difference editing"
            or "only" in reasons_blob), gkpg["reasons"]


# ----------------------------------------------------------------- 2. network_geometry
def test_network_geometry_16_stations_no_explosion():
    _require(FULL16)
    res = network_geometry(FULL16)
    assert "error" not in res, res
    # 回归:只取网内 16 站,不因 lfile 链入全局 apr 数千站而 O(n²) 爆炸
    assert res["n_stations"] == 16, res["n_stations"]
    bl_max = res["baselines_km"]["max"]
    assert 300 < bl_max < 400, bl_max
    # 健康网络仍会给出一条"网形健康"flag(非空)
    assert res["flags"], res


# ----------------------------------------------------------------- 3. qc_report
def test_qc_report_warn_with_one_drop():
    _require(FULL16)
    res = qc_report(FULL16, 100)
    assert res["verdict"] == "warn", res
    assert res["metrics"]["n_dropped"] == 1
    assert res["metrics"]["postfit_nrms"] == pytest.approx(0.186, abs=0.01)


# ----------------------------------------------------------------- 4. multiday_std
def test_multiday_std_30_days_gkpg_high_u():
    _require(MULTIDAY)
    res = multiday_std(MULTIDAY, "knet")
    assert res.get("n_days") == 30, res
    assert "GKPG" in res["stations"]
    gkpg = res["stations"]["GKPG"]
    assert gkpg["std_u_mm"] > 15, gkpg
    assert gkpg["flagged_high_u"] is True
    daej = res["stations"]["DAEJ"]
    assert daej["std_u_mm"] < 5, daej
    assert "GKPG" in res["flagged"]


# ----------------------------------------------------------------- 5. parse_rinex_header
def test_parse_rinex_header_nonempty():
    _require(SDSM_RINEX)
    info = parse_rinex_header(SDSM_RINEX)
    assert info is not None
    assert info.get("rec_type"), info
    assert info.get("ant_type"), info


# ----------------------------------------------------------------- 6. build_station_info
def test_build_station_info_uppercase_receiver():
    _require(SDSM_RINEX)
    text, n = build_station_info({"SDSM": [SDSM_RINEX]})
    assert n == 1, n
    lines = text.splitlines()
    assert lines[0].startswith("*SITE"), lines[0]
    # 回归 SDSM 大小写修复:RINEX 头是 "Trimble NetR9",station.info 须大写
    assert "TRIMBLE NETR9" in text, text


# ----------------------------------------------------------------- 7. gamit_tools
def test_parse_summary_basic_fields():
    _require(FULL16)
    s = parse_summary(FULL16, 100)
    assert "error" not in s, s
    assert s["postfit_nrms"] is not None
    assert s["n_stations"] == 16


def test_parse_qfile_basic_fields():
    _require(FULL16_QFILE)
    q = parse_qfile(FULL16_QFILE)
    assert q["stations"], q
    # 任取一站应有 N/E/U 改正
    sample = next(iter(q["stations"].values()))
    assert sample.get("adj_n") is not None
    assert sample.get("adj_u") is not None


# ----------------------------------------------------------------- 8. _valid_xyz 护栏
def test_valid_xyz_guardrail():
    assert _valid_xyz(0, 0, 0) is False
    assert _valid_xyz(-3120042, 4084614, 3764026) is True


# ----------------------------------------------------------------- 9. GAMIT 说明书 RAG
def test_gamit_help_rag():
    import pytest
    from gamit_rag import gamit_help, _index, list_commands
    if _index() is None:
        pytest.skip("无 gg/help 目录(本机未装 GAMIT)")
    assert len(list_commands()) >= 100              # 应索引上百个命令
    # 命令限定检索:autcln 仰角截止应命中 autcln 的块
    r = gamit_help("elevation cutoff", command="autcln", k=3)
    assert r["n_hits"] >= 1
    assert all(h["command"] == "autcln" for h in r["hits"])
    # sh_* 脚本也被索引:sh_rx2apr 查询首位应是 sh_rx2apr 自身
    r2 = gamit_help("sh_rx2apr pseudorange a priori coordinates", k=3)
    assert r2["hits"] and r2["hits"][0]["command"] == "sh_rx2apr"
