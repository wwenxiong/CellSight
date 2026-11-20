# -*- coding: utf-8 -*-
"""pytest 配置：把项目根目录加入 sys.path，保证 `import app.*` 可用。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
