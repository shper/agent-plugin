"""让测试能 `import orchestrate`（ai_client 目录加入 sys.path）。

ai_client 纯标准库、无三方依赖，整套测试 `cd .harness/ai_client && python3 -m pytest __tests__ -q` 直跑。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
