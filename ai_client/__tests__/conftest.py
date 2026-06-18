"""让测试能 `import orchestrate`（ai_client 目录加入 sys.path）。

只测 orchestrate 的核心编排函数（依赖注入 caller），不触发 providers→httpx 的延迟 import，
故无需装 httpx 即可跑：`cd .harness/ai_client && python3 -m pytest __tests__ -q`。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
