"""python -m recap_shorts.app [--port N] [--host H] [--work DIR] — 기본 http://127.0.0.1:8020"""
import argparse

import uvicorn

from .server import create_app


def main() -> None:
    ap = argparse.ArgumentParser(prog="python -m recap_shorts.app")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8020)
    ap.add_argument("--work", default=None, help="작업 폴더 (기본 work/ 또는 RECAP_WORK_ROOT)")
    a = ap.parse_args()
    uvicorn.run(create_app(work_root=a.work), host=a.host, port=a.port, log_level="info")


if __name__ == "__main__":
    main()
