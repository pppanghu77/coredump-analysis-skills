#!/usr/bin/env python3
"""Verify whether retried packages/versions still remain in retry lists."""
import argparse
import sys
from pathlib import Path


def parse_args():
    parser = argparse.ArgumentParser(description="Verify retry targets after rerun")
    parser.add_argument("--summary-dir", required=True)
    parser.add_argument("--packages", default="", help="Comma separated package list")
    parser.add_argument("--versions-file", help="File with lines: package\\tversion")
    return parser.parse_args()


def load_retry_packages(path):
    result = set()
    if not path.exists():
        return result
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        result.add(line)
    return result


def load_retry_versions(path):
    result = set()
    if not path.exists():
        return result
    lines = path.read_text(encoding="utf-8").splitlines()
    for line in lines[1:]:
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        result.add((parts[0], parts[1]))
    return result


def load_target_versions(path):
    result = []
    if not path:
        return result
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) >= 2:
            result.append((parts[0], parts[1]))
    return result


def main():
    args = parse_args()
    summary_dir = Path(args.summary_dir)
    retry_packages = load_retry_packages(summary_dir / "retry_packages.txt")
    retry_versions = load_retry_versions(summary_dir / "retry_versions.tsv")

    target_packages = [p.strip() for p in args.packages.split(",") if p.strip()]
    target_versions = load_target_versions(args.versions_file)

    remaining_packages = [p for p in target_packages if p in retry_packages]
    remaining_versions = [item for item in target_versions if item in retry_versions]

    if not target_packages and not target_versions:
        print("No verification targets provided.")
        return 0

    print("Retry verification summary:")
    print(f"  target packages: {len(target_packages)}")
    print(f"  target versions: {len(target_versions)}")
    print(f"  remaining packages: {len(remaining_packages)}")
    print(f"  remaining versions: {len(remaining_versions)}")

    if remaining_packages:
        print("Remaining packages:")
        for package in remaining_packages:
            print(f"  - {package}")

    if remaining_versions:
        print("Remaining versions:")
        for package, version in remaining_versions:
            print(f"  - {package}\t{version}")

    if remaining_packages or remaining_versions:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
