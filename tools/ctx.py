"""Print context around regex matches in a minified bundle.

    python tools/ctx.py main.<hash>.js 'apiDomain' 400 3000 1

Arguments: file, pattern, chars before, chars after, max matches. Written for the
Angular bundle inside the DroneTower APK, where grep's line-oriented output is
useless because the whole file is one line.
"""

from __future__ import annotations

import re
import sys


def main() -> None:
    if len(sys.argv) < 3:
        sys.exit(__doc__)

    path, pattern = sys.argv[1], sys.argv[2]
    before = int(sys.argv[3]) if len(sys.argv) > 3 else 200
    after = int(sys.argv[4]) if len(sys.argv) > 4 else 2000
    limit = int(sys.argv[5]) if len(sys.argv) > 5 else 5

    content = open(path, encoding="utf-8", errors="replace").read()

    for index, match in enumerate(re.finditer(pattern, content)):
        if index >= limit:
            break
        print(f"\n===== MATCH {index} @ offset {match.start()} =====")
        print(content[max(0, match.start() - before) : match.start() + after])


if __name__ == "__main__":
    main()
