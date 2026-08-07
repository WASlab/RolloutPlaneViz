from __future__ import annotations

import argparse

import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8057)
    args = parser.parse_args()
    uvicorn.run("rolloutplane_viz.app:app", host=args.host, port=args.port)


if __name__ == "__main__":
    main()
