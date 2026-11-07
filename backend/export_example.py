"""Regenerate the downloadable example bundle from the current fixed executor."""
import argparse
from pathlib import Path

from backend.bundle import build_bundle
from backend.template import load_template


def main():
    parser = argparse.ArgumentParser(description="Export the clearly labelled TeamBlocks demo template")
    parser.add_argument("--output", default="artifacts/teamblocks-demo.zip")
    args = parser.parse_args()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(build_bundle(load_template()))
    print(f"Demo template exported: {output.resolve()}")


if __name__ == "__main__":
    main()
