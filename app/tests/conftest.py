"""pytest 配置:把 backend 加入 sys.path,供 `from tools.xxx import ...` 工作。

工具间相互 import 形如 `from tools.network_geometry import ...`,因此 import 根必须是
`<repo>/app/backend`(其下有 tools/ 包)。这里把它插到 sys.path 最前。
"""
import os
import sys

_BACKEND = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "backend")
)
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)
