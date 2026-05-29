#!/usr/bin/env python3
"""Validate retry-closure artifacts for a coredump analysis workspace."""
import argparse
import json
import sys
from pathlib import Path


SUMMARY_DIR_NAME = "6.总结报告"


def parse_args():
    parser = argparse.ArgumentParser(description="Validate workspace retry closure artifacts")
    parser.add_argument("--workspace", required=True)
    return parser.parse_args()


def read_text(path):
    return path.read_text(encoding="utf-8") if path.exists() else ""


def read_json(path):
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def parse_retry_packages(path):
    packages = []
    for line in read_text(path).splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        packages.append(line)
    return packages


def parse_retry_versions(path):
    versions = []
    lines = read_text(path).splitlines()
    if not lines:
        return versions
    for line in lines[1:]:
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) < 7:
            continue
        versions.append({
            "package": parts[0],
            "version": parts[1],
            "failed_steps": parts[2],
            "retry_strategy": parts[3],
            "last_message": parts[4],
            "command": parts[5],
            "step_command": parts[6],
        })
    return versions


def require(path, errors):
    if not path.exists():
        errors.append(f"missing file: {path}")


def validate_scripts_contain(path, needle, errors):
    content = read_text(path)
    if needle not in content:
        errors.append(f"{path.name} missing marker: {needle}")


def main():
    args = parse_args()
    workspace = Path(args.workspace)
    summary_dir = workspace / SUMMARY_DIR_NAME
    errors = []
    warnings = []

    required_files = [
        summary_dir / "run_context.json",
        summary_dir / "run_manifest.json",
        summary_dir / "run_manifest.md",
        summary_dir / "retry_packages.txt",
        summary_dir / "retry_versions.tsv",
        summary_dir / "retry_versions.md",
        summary_dir / "retry_commands.sh",
        summary_dir / "retry_versions.sh",
        summary_dir / "retry_failed_steps.sh",
        summary_dir / "retry_summary.md",
        summary_dir / "package_status.tsv",
        summary_dir / "version_status.tsv",
    ]
    for path in required_files:
        require(path, errors)

    run_context = read_json(summary_dir / "run_context.json")
    manifest = read_json(summary_dir / "run_manifest.json")
    retry_packages = parse_retry_packages(summary_dir / "retry_packages.txt")
    retry_versions = parse_retry_versions(summary_dir / "retry_versions.tsv")

    if run_context is None:
        errors.append("run_context.json is missing or invalid JSON")
    if manifest is None:
        errors.append("run_manifest.json is missing or invalid JSON")

    if run_context and str(workspace) != run_context.get("workspace", ""):
        errors.append("run_context workspace mismatch")
    if manifest and str(workspace) != manifest.get("workspace", ""):
        errors.append("run_manifest workspace mismatch")

    manifest_packages = set()
    if manifest:
        manifest_packages = {entry.get("package", "") for entry in manifest.get("packages", []) if entry.get("package")}

    for package in retry_packages:
        if manifest_packages and package not in manifest_packages:
            warnings.append(f"retry package not found in manifest packages: {package}")

    for item in retry_versions:
        if manifest_packages and item["package"] not in manifest_packages:
            warnings.append(f"retry version package not found in manifest packages: {item['package']}")
        if item["retry_strategy"] not in {"analysis_only", "package_then_analysis", "full_version_rerun"}:
            errors.append(f"invalid retry_strategy for {item['package']} {item['version']}: {item['retry_strategy']}")
        if not item["command"]:
            errors.append(f"missing command for {item['package']} {item['version']}")
        if not item["step_command"]:
            errors.append(f"missing step_command for {item['package']} {item['version']}")

    validate_scripts_contain(summary_dir / "retry_commands.sh", "generate_workspace_summary.py", errors)
    validate_scripts_contain(summary_dir / "retry_versions.sh", "verify_retry_targets.py", errors)
    validate_scripts_contain(summary_dir / "retry_failed_steps.sh", "run_retry_step.sh", errors)

    retry_summary = read_text(summary_dir / "retry_summary.md")
    if retry_summary and "重跑摘要" not in retry_summary:
        errors.append("retry_summary.md missing title")

    print("Workspace retry-closure validation")
    print(f"  workspace: {workspace}")
    print(f"  retry packages: {len(retry_packages)}")
    print(f"  retry versions: {len(retry_versions)}")
    print(f"  warnings: {len(warnings)}")
    print(f"  errors: {len(errors)}")

    if warnings:
        print("\nWarnings:")
        for item in warnings:
            print(f"  - {item}")

    if errors:
        print("\nErrors:")
        for item in errors:
            print(f"  - {item}")
        return 1

    print("\nOK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
