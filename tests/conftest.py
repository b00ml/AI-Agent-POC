"""pytest 全局配置：把仓库根目录加入 sys.path，保证 tests/unit 可直接 import core。"""

import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)
