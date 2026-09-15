from __future__ import annotations

import argparse

import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the local-only Author Agent web UI.")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    uvicorn.run("author_agent.web:app", host="127.0.0.1", port=args.port, reload=False)
