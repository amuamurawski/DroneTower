"""Print a character range of a file.

    python tools/slice.py main.<hash>.js 2044200 2047200

Companion to ctx.py: once a match offset is known, this dumps the surrounding
region without re-running the regex.
"""

from __future__ import annotations

import sys


def main() -> None:
    if len(sys.argv) != 4:
        sys.exit(__doc__)

    content = open(sys.argv[1], encoding="utf-8", errors="replace").read()
    print(content[int(sys.argv[2]) : int(sys.argv[3])])


if __name__ == "__main__":
    main()
