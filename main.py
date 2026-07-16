from __future__ import annotations

import sys

from video_agent.cli import main as cli_main


def main() -> int:
    argv = sys.argv[1:]
    if argv and argv[0].startswith("-"):
        argv = ["generate_video", *argv]
    return cli_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
