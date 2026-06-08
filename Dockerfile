# GAMIT-Agent —— LLM 驱动原生 GAMIT 的 agent(后端 FastAPI+SSE + Leaflet 前端)。
#
# 设计:GAMIT/GLOBK 本体**不打进镜像**(许可证不可分发),由用户用 volume 挂载到 /gg。
# 镜像只装 agent + Python 依赖 + GAMIT 脚本运行所需的系统件(csh / gfortran / wget)。
#
# 构建(在仓库根):docker build -t gamit-agent .
# 运行:
#   docker run --rm -p 8765:8765 \
#     -v /home/<you>/gg:/gg \                         # 已装好的 GAMIT/GLOBK
#     -v /path/to/your/rinex:/data:ro \               # 你的裸 RINEX/数据(只读)
#     -v $PWD/experiments:/opt/gamit-agent/app/experiments \   # 工程产物持久化
#     -e DEEPSEEK_API_KEY=sk-xxx \                    # 或在 UI 的 Settings 填
#     gamit-agent
# 然后浏览器开 http://localhost:8765
#
# ⚠️ 注意:挂载的 /gg 必须与本镜像运行时(linux x86_64 / glibc)二进制兼容。
#    若 gamit/bin 或 kf/bin 因 glibc 差异跑不起来,镜像内含 gfortran+make,
#    agent 的 svpos 自愈会重编 kf 模块;主程序如不兼容则需在兼容环境重编 GAMIT。

FROM python:3.13-slim

# 系统依赖:tcsh(GAMIT 脚本 #!/bin/csh)、gfortran+make(kf 模块如 svpos 自愈编译)、
# wget+gzip+ca-certificates(sh_get_nav 等在线取数据)。
# bc:GAMIT 脚本(sh_link_rinex 等)用 bc 做时间跨度/session 浮点运算,缺了会死循环卡死。
# gawk:部分 GAMIT 脚本依赖 gawk 特性(slim 自带 mawk 不足)。ftp:匿名 FTP 取轨道/导航。
RUN apt-get update && apt-get install -y --no-install-recommends \
        tcsh gfortran make wget gzip ca-certificates bc gawk ftp \
    && ln -sf /bin/tcsh /bin/csh \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/gamit-agent

# 先装依赖(利用层缓存)
COPY requirements-app.txt .
RUN pip install --no-cache-dir -r requirements-app.txt

# 拷贝 agent 代码 + 知识库(knowledge.py 需 skill/references;两者必须同在镜像)
COPY app/ ./app/
COPY skill/ ./skill/

# GAMIT 由挂载提供;把其 bin 加进 PATH,GG_DIR 指向挂载点。
# GAMIT_BROWSE_ROOT=/data:UI 的文件夹浏览器默认从挂载的数据目录起步(否则容器内 $HOME=/root 是空的)。
ENV GG_DIR=/gg \
    PATH="/gg/com:/gg/gamit/bin:/gg/kf/bin:${PATH}" \
    GAMIT_BROWSE_ROOT=/data \
    PYTHONUNBUFFERED=1

# ~/gg 兼容链接:GAMIT 脚本(sh_setup 等)用硬编码的 `~/gg/tables` 定位表文件,
# 容器以 root 运行 → ~/gg=/root/gg,但 gg 挂在 /gg。建 /root/gg -> /gg,
# 使所有表链接(leap.sec/pole/ut1/nbody…)正确解析到挂载点;否则 MAKEXP 找不到 leap.sec 而 fatal。
# (构建期 /gg 为空挂载点,符号链接此刻悬空、运行时随挂载生效。)
RUN ln -sfn /gg /root/gg

EXPOSE 8765
WORKDIR /opt/gamit-agent/app

# 就绪探针:容器起来后 /api/health 返回 200 才算 healthy(镜像已装 wget)
HEALTHCHECK --interval=30s --timeout=4s --start-period=20s --retries=3 \
    CMD wget -qO- http://localhost:8765/api/health || exit 1

CMD ["uvicorn", "backend.server:app", "--host", "0.0.0.0", "--port", "8765"]
