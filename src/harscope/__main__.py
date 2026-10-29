"""允许通过 ``python -m harscope`` 直接调用命令行。"""

from __future__ import annotations

import sys

from .cli import main

if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
