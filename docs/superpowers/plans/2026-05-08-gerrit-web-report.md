# Gerrit Web Report Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Gerrit Web Report generator that aggregates submitted coredump fix commits from a workspace, enriches them from Gerrit when possible, and outputs a static local web report plus an optional local server.

**Architecture:** Add one focused Python CLI script under `coredump-full-analysis/scripts/` that owns collection, normalization, optional Gerrit enrichment, JSON output, static page rendering, and local serving. Integrate it into `run_analysis_agent.sh` as a non-fatal post-processing step, and document the new report entry points in the existing skill docs.

**Tech Stack:** Python 3 standard library (`argparse`, `dataclasses`, `json`, `http.server`, `pathlib`, `unittest`, `tempfile`), existing `coredump-crash-analysis/centralized/gerrit_client.py`, Bash, static HTML/CSS/vanilla JavaScript.

---

## Scope Check

The approved spec covers one cohesive feature: generate and view a local Gerrit report for submitted fixes. It has three parts—data aggregation, report rendering/serving, and Agent integration—but they share one data model and one workspace output location, so one implementation plan is appropriate.

## File Structure

- Create: `coredump-full-analysis/scripts/reporting/generate_gerrit_web_report.py`
  - CLI entry point.
  - Defines `GerritFixRecord` and `ReportWarning` dataclasses.
  - Scans workspace result files.
  - Merges records by `commit_hash`.
  - Optionally enriches records through existing `GerritClient`.
  - Writes `data.json` and `index.html`.
  - Optionally serves the output directory on `127.0.0.1`.

- Create: `tests/coredump_full_analysis/test_generate_gerrit_web_report.py`
  - Uses `unittest` and `tempfile`.
  - Imports the script via `importlib.util` because `coredump-full-analysis` contains a hyphen.
  - Tests collection from Gerrit commit JSON, auto-fix JSON, duplicate merge behavior, warning handling, empty report output, and page/data generation.

- Modify: `run_analysis_agent.sh`
  - Add `GENERATE_GERRIT_WEB_REPORT=true` and `SERVE_GERRIT_WEB_REPORT=false` defaults near existing option defaults.
  - Add `--no-gerrit-web-report` and `--serve-gerrit-web-report` to help and argument parsing.
  - Add `generate_gerrit_web_report()` helper after `generate_workspace_reports()`.
  - Call the helper after workspace summary generation in background, progress, and foreground paths.
  - Keep report generation non-fatal.

- Modify: `SKILL.md`
  - Add the Gerrit Web Report output to the root documentation.
  - Add a quick manual command example.

- Modify: `coredump-full-analysis/SKILL.md`
  - Add the output path under “输出文件”.
  - Add a short usage section for manual generation and optional serving.

Do not commit during implementation unless the user explicitly authorizes commits. If commits are authorized, commit after each task using the messages shown in the task checkpoints.

---

### Task 1: Add failing tests for workspace collection and merge behavior

**Files:**
- Create: `tests/coredump_full_analysis/test_generate_gerrit_web_report.py`
- Future implementation target: `coredump-full-analysis/scripts/reporting/generate_gerrit_web_report.py`

- [ ] **Step 1: Create the test file with failing collector tests**

Create `tests/coredump_full_analysis/test_generate_gerrit_web_report.py` with this content:

```python
import importlib.util
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "coredump-full-analysis" / "scripts" / "generate_gerrit_web_report.py"

spec = importlib.util.spec_from_file_location("generate_gerrit_web_report", SCRIPT_PATH)
gerrit_report = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gerrit_report)


class GerritWebReportCollectionTests(unittest.TestCase):
    def write_json(self, path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def test_collects_submitted_commit_json(self):
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            self.write_json(
                workspace / "5.崩溃分析" / "gerrit" / "commit_abc123.json",
                {
                    "commit_hash": "abc123",
                    "branch": "auto-fix/dde-dock/v1_2_3",
                    "target_branch": "develop/eagle",
                    "package": "dde-dock",
                    "version": "1.2.3",
                    "reviewers": ["reviewer@example.com"],
                    "time": "2026-05-08T10:00:00+08:00",
                    "status": "submitted",
                },
            )

            records, warnings = gerrit_report.collect_workspace_records(workspace)

            self.assertEqual([], warnings)
            self.assertEqual(1, len(records))
            record = records[0]
            self.assertEqual("abc123", record.commit_hash)
            self.assertEqual("dde-dock", record.package)
            self.assertEqual("1.2.3", record.version)
            self.assertEqual("develop/eagle", record.target_branch)
            self.assertEqual(["reviewer@example.com"], record.reviewers)
            self.assertEqual("submitted", record.local_status)
            self.assertIn("5.崩溃分析/gerrit/commit_abc123.json", record.source_files)

    def test_collects_submitted_auto_fix_commit_hashes(self):
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            self.write_json(
                workspace / "5.崩溃分析" / "dde-dock" / "version_1_2_3" / "auto_fix_clusters_result.json",
                {
                    "package": "dde-dock",
                    "version": "1.2.3",
                    "target_branch": "origin/develop/eagle",
                    "submitted": True,
                    "commit_hashes": ["abc123", "def456"],
                    "auto_fixed": [
                        {
                            "description": "修复空指针崩溃",
                            "files_changed": ["src/a.cpp", "src/b.cpp"],
                        }
                    ],
                    "clusters": [
                        {
                            "cluster": {
                                "title": "QScreen geometry crash",
                                "signal": "SIGSEGV",
                                "count": 12,
                            }
                        }
                    ],
                },
            )

            records, warnings = gerrit_report.collect_workspace_records(workspace)

            self.assertEqual([], warnings)
            self.assertEqual(["abc123", "def456"], [record.commit_hash for record in records])
            for record in records:
                self.assertEqual("dde-dock", record.package)
                self.assertEqual("1.2.3", record.version)
                self.assertEqual("origin/develop/eagle", record.target_branch)
                self.assertEqual("修复空指针崩溃", record.fix_description)
                self.assertEqual(["src/a.cpp", "src/b.cpp"], record.files_changed)
                self.assertEqual("QScreen geometry crash", record.cluster_title)
                self.assertEqual("SIGSEGV", record.signal)
                self.assertEqual(12, record.crash_count)

    def test_merges_duplicate_commit_sources(self):
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            self.write_json(
                workspace / "5.崩溃分析" / "gerrit" / "commit_abc123.json",
                {
                    "commit_hash": "abc123",
                    "target_branch": "develop/eagle",
                    "package": "dde-dock",
                    "version": "1.2.3",
                    "reviewers": ["reviewer@example.com"],
                    "status": "submitted",
                },
            )
            self.write_json(
                workspace / "5.崩溃分析" / "dde-dock" / "version_1_2_3" / "auto_fix_result.json",
                {
                    "package": "dde-dock",
                    "version": "1.2.3",
                    "submitted": True,
                    "commit_hash": "abc123",
                    "auto_fixed": [
                        {
                            "reason": "cherry-picked known upstream fix",
                            "files_changed": ["src/fix.cpp"],
                        }
                    ],
                },
            )

            records, warnings = gerrit_report.collect_workspace_records(workspace)

            self.assertEqual([], warnings)
            self.assertEqual(1, len(records))
            record = records[0]
            self.assertEqual("abc123", record.commit_hash)
            self.assertEqual("dde-dock", record.package)
            self.assertEqual("1.2.3", record.version)
            self.assertEqual(["reviewer@example.com"], record.reviewers)
            self.assertEqual(["src/fix.cpp"], record.files_changed)
            self.assertEqual(2, len(record.source_files))

    def test_invalid_json_is_warning_not_failure(self):
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            bad_file = workspace / "5.崩溃分析" / "gerrit" / "commit_bad.json"
            bad_file.parent.mkdir(parents=True, exist_ok=True)
            bad_file.write_text("{not-json", encoding="utf-8")

            records, warnings = gerrit_report.collect_workspace_records(workspace)

            self.assertEqual([], records)
            self.assertEqual(1, len(warnings))
            self.assertIn("commit_bad.json", warnings[0].path)
            self.assertIn("JSON", warnings[0].message)

    def test_empty_workspace_returns_empty_records(self):
        with TemporaryDirectory() as tmp:
            records, warnings = gerrit_report.collect_workspace_records(Path(tmp))

            self.assertEqual([], records)
            self.assertEqual([], warnings)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail because the script is missing**

Run:

```bash
python3 -m unittest tests.coredump_full_analysis.test_generate_gerrit_web_report -v
```

Expected: FAIL or ERROR with a message containing `generate_gerrit_web_report.py` or `No such file or directory`.

- [ ] **Step 3: Commit checkpoint if commits are authorized**

Only run this if the user has explicitly authorized commits for this implementation session:

```bash
git add tests/coredump_full_analysis/test_generate_gerrit_web_report.py
git commit -m "test: add Gerrit web report collection tests"
```

---

### Task 2: Implement data model, JSON loading, record collection, and merging

**Files:**
- Create: `coredump-full-analysis/scripts/reporting/generate_gerrit_web_report.py`
- Test: `tests/coredump_full_analysis/test_generate_gerrit_web_report.py`

- [ ] **Step 1: Create the initial script with collection logic**

Create `coredump-full-analysis/scripts/reporting/generate_gerrit_web_report.py` with this content:

```python
#!/usr/bin/env python3
import argparse
import json
import socket
import sys
import webbrowser
from dataclasses import asdict, dataclass, field
from datetime import datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]
CENTRALIZED_DIR = REPO_ROOT / "coredump-crash-analysis" / "centralized"
if str(CENTRALIZED_DIR) not in sys.path:
    sys.path.insert(0, str(CENTRALIZED_DIR))


@dataclass
class ReportWarning:
    path: str
    message: str


@dataclass
class GerritFixRecord:
    commit_hash: str
    package: str = ""
    version: str = ""
    workspace_relative_path: str = ""
    source_file: str = ""
    source_files: List[str] = field(default_factory=list)
    commit_subject: str = ""
    target_branch: str = ""
    fix_description: str = ""
    files_changed: List[str] = field(default_factory=list)
    cluster_title: str = ""
    signal: str = ""
    crash_count: int = 0
    project: str = ""
    change_number: Optional[int] = None
    change_id: str = ""
    gerrit_url: str = ""
    status: str = "Unknown"
    local_status: str = ""
    owner: str = ""
    reviewers: List[str] = field(default_factory=list)
    updated: str = ""
    branch: str = ""
    gerrit_enriched: bool = False
    enrichment_error: str = ""

    def merge(self, other: "GerritFixRecord") -> None:
        for name in [
            "package", "version", "workspace_relative_path", "source_file",
            "commit_subject", "target_branch", "fix_description", "cluster_title",
            "signal", "project", "change_id", "gerrit_url", "status",
            "local_status", "owner", "updated", "branch", "enrichment_error",
        ]:
            if not getattr(self, name) and getattr(other, name):
                setattr(self, name, getattr(other, name))
        if self.change_number is None and other.change_number is not None:
            self.change_number = other.change_number
        if not self.crash_count and other.crash_count:
            self.crash_count = other.crash_count
        self.gerrit_enriched = self.gerrit_enriched or other.gerrit_enriched
        self.source_files = merge_list(self.source_files, other.source_files)
        self.files_changed = merge_list(self.files_changed, other.files_changed)
        self.reviewers = merge_list(self.reviewers, other.reviewers)


def merge_list(left: Iterable[str], right: Iterable[str]) -> List[str]:
    result = []
    seen = set()
    for item in list(left) + list(right):
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result


def relative_path(path: Path, workspace: Path) -> str:
    try:
        return path.relative_to(workspace).as_posix()
    except ValueError:
        return path.as_posix()


def read_json_file(path: Path, workspace: Path) -> Tuple[Optional[Dict[str, Any]], Optional[ReportWarning]]:
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except json.JSONDecodeError as exc:
        return None, ReportWarning(relative_path(path, workspace), f"JSON 解析失败: {exc}")
    except OSError as exc:
        return None, ReportWarning(relative_path(path, workspace), f"文件读取失败: {exc}")


def first_text(*values: Any) -> str:
    for value in values:
        if isinstance(value, str) and value:
            return value
    return ""


def first_int(*values: Any) -> int:
    for value in values:
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)
    return 0


def list_text(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(item) for item in value if item]
    if isinstance(value, str) and value:
        return [value]
    return []


def derive_package_version_from_path(path: Path, workspace: Path) -> Tuple[str, str]:
    parts = path.relative_to(workspace).parts
    if "5.崩溃分析" not in parts:
        return "", ""
    index = parts.index("5.崩溃分析")
    if len(parts) <= index + 2:
        return "", ""
    package = parts[index + 1]
    version_part = parts[index + 2]
    if not version_part.startswith("version_"):
        return package, ""
    return package, version_part.removeprefix("version_").replace("_", ".")


def extract_cluster_context(data: Dict[str, Any]) -> Dict[str, Any]:
    clusters = data.get("clusters")
    if isinstance(clusters, list) and clusters:
        raw_cluster = clusters[0].get("cluster", clusters[0]) if isinstance(clusters[0], dict) else {}
        if isinstance(raw_cluster, dict):
            return {
                "cluster_title": first_text(raw_cluster.get("title"), raw_cluster.get("pattern_name"), raw_cluster.get("app_layer_symbol")),
                "signal": first_text(raw_cluster.get("signal")),
                "crash_count": first_int(raw_cluster.get("count")),
            }
    return {"cluster_title": "", "signal": "", "crash_count": 0}


def extract_auto_fixed_context(data: Dict[str, Any]) -> Dict[str, Any]:
    auto_fixed = data.get("auto_fixed")
    if not isinstance(auto_fixed, list) or not auto_fixed or not isinstance(auto_fixed[0], dict):
        return {"fix_description": "", "files_changed": []}
    first = auto_fixed[0]
    return {
        "fix_description": first_text(first.get("description"), first.get("reason"), first.get("reviewer_note")),
        "files_changed": list_text(first.get("files_changed") or first.get("files")),
    }


def record_from_gerrit_commit_file(path: Path, workspace: Path, data: Dict[str, Any]) -> Optional[GerritFixRecord]:
    commit_hash = first_text(data.get("commit_hash"))
    if not commit_hash:
        return None
    rel = relative_path(path, workspace)
    return GerritFixRecord(
        commit_hash=commit_hash,
        package=first_text(data.get("package")),
        version=first_text(data.get("version")),
        workspace_relative_path=rel,
        source_file=rel,
        source_files=[rel],
        commit_subject=first_text(data.get("subject"), data.get("commit_subject")),
        target_branch=first_text(data.get("target_branch")),
        branch=first_text(data.get("branch")),
        reviewers=list_text(data.get("reviewers")),
        updated=first_text(data.get("time")),
        local_status=first_text(data.get("status")),
    )


def records_from_auto_fix_file(path: Path, workspace: Path, data: Dict[str, Any]) -> List[GerritFixRecord]:
    submitted = data.get("submitted") is True or data.get("fixes_submitted") is True
    if not submitted:
        return []
    package_from_path, version_from_path = derive_package_version_from_path(path, workspace)
    commit_hashes = []
    commit_hashes.extend(list_text(data.get("commit_hashes")))
    commit_hashes.extend(list_text(data.get("commit_hash")))
    if not commit_hashes:
        return []
    rel = relative_path(path, workspace)
    fixed_context = extract_auto_fixed_context(data)
    cluster_context = extract_cluster_context(data)
    return [
        GerritFixRecord(
            commit_hash=commit_hash,
            package=first_text(data.get("package"), package_from_path),
            version=first_text(data.get("version"), version_from_path),
            workspace_relative_path=rel,
            source_file=rel,
            source_files=[rel],
            target_branch=first_text(data.get("target_branch")),
            fix_description=fixed_context["fix_description"],
            files_changed=fixed_context["files_changed"],
            cluster_title=cluster_context["cluster_title"],
            signal=cluster_context["signal"],
            crash_count=cluster_context["crash_count"],
            local_status="submitted",
        )
        for commit_hash in commit_hashes
    ]


def collect_workspace_records(workspace: Path) -> Tuple[List[GerritFixRecord], List[ReportWarning]]:
    records_by_commit: Dict[str, GerritFixRecord] = {}
    warnings: List[ReportWarning] = []
    analysis_root = workspace / "5.崩溃分析"
    if not analysis_root.exists():
        return [], []

    candidate_files = []
    candidate_files.extend(sorted((analysis_root / "gerrit").glob("commit_*.json")))
    for pattern in ["*/version_*/auto_fix_result.json", "*/version_*/auto_fix_clusters_result.json", "*/version_*/deep_auto_fix_result.json"]:
        candidate_files.extend(sorted(analysis_root.glob(pattern)))

    for path in candidate_files:
        data, warning = read_json_file(path, workspace)
        if warning:
            warnings.append(warning)
            continue
        if data is None:
            continue
        if path.parent.name == "gerrit" and path.name.startswith("commit_"):
            new_records = [record_from_gerrit_commit_file(path, workspace, data)]
        else:
            new_records = records_from_auto_fix_file(path, workspace, data)
        for record in [item for item in new_records if item is not None]:
            existing = records_by_commit.get(record.commit_hash)
            if existing:
                existing.merge(record)
            else:
                records_by_commit[record.commit_hash] = record

    return sorted(records_by_commit.values(), key=lambda item: (item.package, item.version, item.commit_hash)), warnings
```

- [ ] **Step 2: Run the collector tests**

Run:

```bash
python3 -m unittest tests.coredump_full_analysis.test_generate_gerrit_web_report -v
```

Expected: PASS for the five collection tests.

- [ ] **Step 3: Commit checkpoint if commits are authorized**

Only run this if the user has explicitly authorized commits for this implementation session:

```bash
git add coredump-full-analysis/scripts/reporting/generate_gerrit_web_report.py tests/coredump_full_analysis/test_generate_gerrit_web_report.py
git commit -m "feat: collect Gerrit web report records"
```

---

### Task 3: Add report payload, safe page rendering, data output, and CLI generation

**Files:**
- Modify: `coredump-full-analysis/scripts/reporting/generate_gerrit_web_report.py`
- Modify: `tests/coredump_full_analysis/test_generate_gerrit_web_report.py`

- [ ] **Step 1: Add failing tests for output files and empty reports**

Append these tests inside `GerritWebReportCollectionTests` before the `if __name__ == "__main__"` block:

```python
    def test_generate_report_writes_data_and_page(self):
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            self.write_json(
                workspace / "5.崩溃分析" / "gerrit" / "commit_abc123.json",
                {
                    "commit_hash": "abc123",
                    "target_branch": "develop/eagle",
                    "package": "dde-dock",
                    "version": "1.2.3",
                    "status": "submitted",
                },
            )

            output_dir = gerrit_report.generate_report(workspace, enrich=False)

            data_path = output_dir / "data.json"
            page_path = output_dir / "index.html"
            self.assertTrue(data_path.exists())
            self.assertTrue(page_path.exists())
            payload = json.loads(data_path.read_text(encoding="utf-8"))
            page = page_path.read_text(encoding="utf-8")
            self.assertEqual(1, payload["summary"]["total_records"])
            self.assertEqual("dde-dock", payload["records"][0]["package"])
            self.assertIn("Gerrit Web Report", page)
            self.assertIn("abc123", page)
            self.assertIn("textContent", page)

    def test_generate_report_writes_empty_report(self):
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            output_dir = gerrit_report.generate_report(workspace, enrich=False)

            payload = json.loads((output_dir / "data.json").read_text(encoding="utf-8"))
            page = (output_dir / "index.html").read_text(encoding="utf-8")
            self.assertEqual(0, payload["summary"]["total_records"])
            self.assertIn("未发现已提交 Gerrit 的修复变更", page)
```

- [ ] **Step 2: Run the tests to verify the new tests fail**

Run:

```bash
python3 -m unittest tests.coredump_full_analysis.test_generate_gerrit_web_report -v
```

Expected: FAIL with `AttributeError: module 'generate_gerrit_web_report' has no attribute 'generate_report'`.

- [ ] **Step 3: Add payload, summary, page, and CLI functions**

Append this code to `coredump-full-analysis/scripts/reporting/generate_gerrit_web_report.py` after `collect_workspace_records()`:

```python

def normalize_status(record: GerritFixRecord) -> str:
    return first_text(record.status, record.local_status, "Unknown")


def build_summary(records: List[GerritFixRecord], warnings: List[ReportWarning], workspace: Path) -> Dict[str, Any]:
    statuses: Dict[str, int] = {}
    projects = set()
    packages = set()
    versions = set()
    latest_updated = ""
    enriched_count = 0
    for record in records:
        status = normalize_status(record)
        statuses[status] = statuses.get(status, 0) + 1
        if record.project:
            projects.add(record.project)
        if record.package:
            packages.add(record.package)
        if record.version:
            versions.add(record.version)
        if record.updated and record.updated > latest_updated:
            latest_updated = record.updated
        if record.gerrit_enriched:
            enriched_count += 1
    return {
        "workspace": str(workspace),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "total_records": len(records),
        "statuses": statuses,
        "project_count": len(projects),
        "package_count": len(packages),
        "version_count": len(versions),
        "latest_updated": latest_updated,
        "gerrit_enriched": enriched_count,
        "gerrit_not_enriched": len(records) - enriched_count,
        "warning_count": len(warnings),
    }


def build_payload(workspace: Path, records: List[GerritFixRecord], warnings: List[ReportWarning]) -> Dict[str, Any]:
    return {
        "summary": build_summary(records, warnings, workspace),
        "records": [asdict(record) for record in records],
        "warnings": [asdict(warning) for warning in warnings],
    }


def write_data_json(payload: Dict[str, Any], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    data_path = output_dir / "data.json"
    data_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return data_path


def json_for_script(payload: Dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")


def render_page(payload: Dict[str, Any]) -> str:
    embedded = json_for_script(payload)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Gerrit Web Report</title>
  <style>
    :root {{ --bg:#f6f8fb; --card:#fff; --text:#172033; --muted:#667085; --line:#d9e2ec; --accent:#2563eb; --danger:#b42318; --ok:#067647; }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; background:var(--bg); color:var(--text); }}
    header, main, .toolbar, .cards {{ padding-left:32px; padding-right:32px; }}
    header {{ padding-top:28px; padding-bottom:12px; }}
    h1 {{ margin:0 0 8px; font-size:28px; }}
    .muted {{ color:var(--muted); font-size:13px; }}
    .cards {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:12px; padding-top:12px; padding-bottom:12px; }}
    .card {{ background:var(--card); border:1px solid var(--line); border-radius:12px; padding:14px; }}
    .card strong {{ display:block; font-size:24px; margin-top:4px; }}
    .toolbar {{ display:grid; grid-template-columns:2fr repeat(4,1fr) auto; gap:10px; padding-top:12px; padding-bottom:12px; align-items:center; }}
    input, select, label {{ font-size:14px; }}
    input, select {{ width:100%; padding:9px 10px; border:1px solid var(--line); border-radius:8px; background:#fff; }}
    main {{ padding-bottom:32px; }}
    table {{ width:100%; border-collapse:collapse; background:var(--card); border:1px solid var(--line); border-radius:12px; overflow:hidden; }}
    th, td {{ padding:10px; border-bottom:1px solid var(--line); text-align:left; vertical-align:top; font-size:13px; }}
    th {{ background:#eef4ff; font-weight:600; }}
    tr.hidden {{ display:none; }}
    .status {{ display:inline-block; padding:2px 8px; border-radius:999px; background:#eef4ff; color:var(--accent); }}
    .status.MERGED {{ background:#ecfdf3; color:var(--ok); }}
    .status.ABANDONED {{ background:#fef3f2; color:var(--danger); }}
    .empty {{ background:var(--card); border:1px solid var(--line); border-radius:12px; padding:24px; text-align:center; }}
    details {{ max-width:420px; }}
    pre {{ white-space:pre-wrap; margin:8px 0 0; color:var(--muted); }}
    a {{ color:var(--accent); }}
  </style>
</head>
<body>
  <header><h1>Gerrit Web Report</h1><div class="muted" id="meta"></div></header>
  <section class="cards" id="cards"></section>
  <section class="toolbar">
    <input id="search" placeholder="搜索 package、project、subject、commit、修复说明">
    <select id="statusFilter"><option value="">全部状态</option></select>
    <select id="packageFilter"><option value="">全部包</option></select>
    <select id="projectFilter"><option value="">全部项目</option></select>
    <select id="branchFilter"><option value="">全部分支</option></select>
    <label><input id="unenrichedFilter" type="checkbox"> 只看未补全</label>
  </section>
  <main>
    <div id="empty" class="empty">未发现已提交 Gerrit 的修复变更</div>
    <table id="table" style="display:none">
      <thead><tr><th>状态</th><th>Package</th><th>Version</th><th>Project</th><th>Subject</th><th>Commit</th><th>Change</th><th>Branch</th><th>Crash</th><th>Files</th><th>Owner/Reviewer</th><th>Updated</th><th>链接</th><th>详情</th></tr></thead>
      <tbody id="tbody"></tbody>
    </table>
  </main>
  <script id="report-data" type="application/json">{embedded}</script>
  <script>
    const payload = JSON.parse(document.getElementById('report-data').textContent);
    const records = payload.records || [];
    const summary = payload.summary || {{}};
    const doc = document;
    const get = (id) => doc.getElementById(id);
    const valueText = (value) => value === null || value === undefined || value === '' ? '-' : String(value);
    const shortCommit = (value) => value ? String(value).slice(0, 8) : '-';
    const blob = (record) => [record.package, record.version, record.project, record.commit_subject, record.commit_hash, record.fix_description, record.cluster_title].join(' ').toLowerCase();

    function appendTextCell(row, value) {{
      const cell = doc.createElement('td');
      cell.textContent = valueText(value);
      row.appendChild(cell);
      return cell;
    }}

    function optionValues(field) {{
      return Array.from(new Set(records.map((record) => record[field]).filter(Boolean))).sort();
    }}

    function fillSelect(id, values) {{
      const select = get(id);
      for (const value of values) {{
        const option = doc.createElement('option');
        option.value = value;
        option.textContent = value;
        select.appendChild(option);
      }}
    }}

    function renderCards() {{
      get('meta').textContent = `Workspace: ${{summary.workspace || '-'}} · 生成时间: ${{summary.generated_at || '-'}} · Warnings: ${{summary.warning_count || 0}}`;
      const statuses = summary.statuses || {{}};
      const cards = [
        ['变更总数', summary.total_records || 0], ['MERGED', statuses.MERGED || statuses.merged || 0],
        ['OPEN', statuses.OPEN || statuses.open || statuses.submitted || 0], ['ABANDONED', statuses.ABANDONED || statuses.abandoned || 0],
        ['Unknown', statuses.Unknown || 0], ['项目数', summary.project_count || 0], ['包数', summary.package_count || 0],
        ['版本数', summary.version_count || 0], ['补全失败', summary.gerrit_not_enriched || 0],
      ];
      const fragment = doc.createDocumentFragment();
      for (const [label, number] of cards) {{
        const card = doc.createElement('div');
        card.className = 'card';
        const labelNode = doc.createElement('span');
        labelNode.className = 'muted';
        labelNode.textContent = label;
        const valueNode = doc.createElement('strong');
        valueNode.textContent = String(number);
        card.append(labelNode, valueNode);
        fragment.appendChild(card);
      }}
      get('cards').replaceChildren(fragment);
    }}

    function detailText(record) {{
      const lines = [];
      if (record.fix_description) lines.push(`修复说明: ${{record.fix_description}}`);
      if (record.cluster_title) lines.push(`崩溃簇: ${{record.cluster_title}}`);
      if (record.files_changed && record.files_changed.length) lines.push(`修改文件:\n- ${{record.files_changed.join('\\n- ')}}`);
      if (record.source_files && record.source_files.length) lines.push(`来源文件:\n- ${{record.source_files.join('\\n- ')}}`);
      if (record.enrichment_error) lines.push(`Gerrit补全错误: ${{record.enrichment_error}}`);
      return lines.join('\\n\\n') || '无更多详情';
    }}

    function renderRows() {{
      const fragment = doc.createDocumentFragment();
      for (const record of records) {{
        const row = doc.createElement('tr');
        const status = record.status || record.local_status || 'Unknown';
        row.dataset.status = status;
        row.dataset.package = record.package || '';
        row.dataset.project = record.project || '';
        row.dataset.branch = record.branch || record.target_branch || '';
        row.dataset.enriched = record.gerrit_enriched ? 'true' : 'false';
        row.dataset.search = blob(record);

        const statusCell = doc.createElement('td');
        const statusBadge = doc.createElement('span');
        statusBadge.className = `status ${{status}}`;
        statusBadge.textContent = status;
        statusCell.appendChild(statusBadge);
        row.appendChild(statusCell);

        appendTextCell(row, record.package);
        appendTextCell(row, record.version);
        appendTextCell(row, record.project);
        appendTextCell(row, record.commit_subject);
        const commitCell = appendTextCell(row, shortCommit(record.commit_hash));
        commitCell.title = record.commit_hash || '';
        appendTextCell(row, record.change_number || '-');
        appendTextCell(row, record.branch || record.target_branch);
        appendTextCell(row, `${{valueText(record.signal)}} / ${{record.crash_count || '-'}}`);
        appendTextCell(row, record.files_changed ? record.files_changed.length : 0);
        appendTextCell(row, record.owner || (record.reviewers || []).join(', '));
        appendTextCell(row, record.updated);

        const linkCell = doc.createElement('td');
        if (record.gerrit_url && /^https?:\/\//.test(record.gerrit_url)) {{
          const link = doc.createElement('a');
          link.href = record.gerrit_url;
          link.textContent = '打开';
          linkCell.appendChild(link);
        }} else {{
          linkCell.textContent = '-';
        }}
        row.appendChild(linkCell);

        const detailCell = doc.createElement('td');
        const details = doc.createElement('details');
        const summaryNode = doc.createElement('summary');
        summaryNode.textContent = '展开';
        const pre = doc.createElement('pre');
        pre.textContent = detailText(record);
        details.append(summaryNode, pre);
        detailCell.appendChild(details);
        row.appendChild(detailCell);

        fragment.appendChild(row);
      }}
      get('tbody').replaceChildren(fragment);
    }}

    function applyFilters() {{
      const query = get('search').value.trim().toLowerCase();
      const status = get('statusFilter').value;
      const packageName = get('packageFilter').value;
      const project = get('projectFilter').value;
      const branch = get('branchFilter').value;
      const onlyUnenriched = get('unenrichedFilter').checked;
      let shown = 0;
      for (const row of get('tbody').children) {{
        const ok = (!query || row.dataset.search.includes(query)) && (!status || row.dataset.status === status) && (!packageName || row.dataset.package === packageName) && (!project || row.dataset.project === project) && (!branch || row.dataset.branch === branch) && (!onlyUnenriched || row.dataset.enriched === 'false');
        row.classList.toggle('hidden', !ok);
        if (ok) shown += 1;
      }}
      get('empty').style.display = shown ? 'none' : 'block';
      get('table').style.display = records.length ? 'table' : 'none';
    }}

    fillSelect('statusFilter', optionValues('status'));
    fillSelect('packageFilter', optionValues('package'));
    fillSelect('projectFilter', optionValues('project'));
    fillSelect('branchFilter', Array.from(new Set(records.map((record) => record.branch || record.target_branch).filter(Boolean))).sort());
    renderCards();
    renderRows();
    for (const id of ['search', 'statusFilter', 'packageFilter', 'projectFilter', 'branchFilter', 'unenrichedFilter']) {{
      get(id).addEventListener('input', applyFilters);
      get(id).addEventListener('change', applyFilters);
    }}
    applyFilters();
  </script>
</body>
</html>
"""


def write_index_page(payload: Dict[str, Any], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    page_path = output_dir / "index.html"
    page_path.write_text(render_page(payload), encoding="utf-8")
    return page_path


def default_output_dir(workspace: Path) -> Path:
    return workspace / "6.总结报告" / "gerrit-web-report"


def enrich_records(records: List[GerritFixRecord]) -> None:
    try:
        from gerrit_client import GerritClient
    except Exception as exc:
        for record in records:
            record.enrichment_error = f"无法加载 GerritClient: {exc}"
        return

    client = GerritClient()
    for record in records:
        try:
            change = client.get_change_by_commit(record.commit_hash, record.project or record.package)
            if not change:
                change = client.get_change_by_commit(record.commit_hash)
            if not change:
                record.enrichment_error = "未查询到 Gerrit change"
                continue
            record.project = first_text(change.get("project"), record.project)
            record.change_number = change.get("change_number") or record.change_number
            record.change_id = first_text(change.get("change_id"), record.change_id)
            record.commit_subject = first_text(change.get("subject"), record.commit_subject)
            record.status = first_text(change.get("status"), record.status, "Unknown")
            record.gerrit_url = first_text(change.get("url"), record.gerrit_url)
            record.branch = first_text(change.get("branch"), record.branch)
            record.owner = first_text(change.get("owner"), record.owner)
            record.updated = first_text(change.get("updated"), record.updated)
            record.gerrit_enriched = True
            record.enrichment_error = ""
        except Exception as exc:
            record.enrichment_error = str(exc)


def generate_report(workspace: Path, output_dir: Optional[Path] = None, enrich: bool = True) -> Path:
    if not workspace.exists():
        raise FileNotFoundError(f"workspace 不存在: {workspace}")
    output_dir = output_dir or default_output_dir(workspace)
    records, warnings = collect_workspace_records(workspace)
    if enrich and records:
        enrich_records(records)
    payload = build_payload(workspace, records, warnings)
    write_data_json(payload, output_dir)
    write_index_page(payload, output_dir)
    return output_dir


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="生成已提交 Gerrit 修复变更的本地网页报告")
    parser.add_argument("--workspace", required=True, help="coredump workspace 路径")
    parser.add_argument("--output-dir", help="输出目录，默认 <workspace>/6.总结报告/gerrit-web-report")
    parser.add_argument("--no-gerrit-enrich", action="store_true", help="只使用本地记录，不查询 Gerrit")
    parser.add_argument("--serve", action="store_true", help="生成后启动本地 HTTP 服务")
    parser.add_argument("--host", default="127.0.0.1", help="本地服务监听地址")
    parser.add_argument("--port", type=int, default=8765, help="本地服务端口")
    parser.add_argument("--open", action="store_true", help="启动服务后尝试打开浏览器")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    workspace = Path(args.workspace).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve() if args.output_dir else None
    try:
        final_output_dir = generate_report(workspace, output_dir, enrich=not args.no_gerrit_enrich)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(f"Gerrit Web Report 已生成: {final_output_dir / 'index.html'}")
    print(f"数据文件: {final_output_dir / 'data.json'}")
    if args.serve:
        return serve_directory(final_output_dir, args.host, args.port, args.open)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run the tests**

Run:

```bash
python3 -m unittest tests.coredump_full_analysis.test_generate_gerrit_web_report -v
```

Expected: PASS for all seven tests.

- [ ] **Step 5: Run the CLI against a temporary empty workspace**

Run:

```bash
tmp_workspace=$(mktemp -d) && python3 coredump-full-analysis/scripts/reporting/generate_gerrit_web_report.py --workspace "$tmp_workspace" --no-gerrit-enrich && test -f "$tmp_workspace/6.总结报告/gerrit-web-report/index.html" && test -f "$tmp_workspace/6.总结报告/gerrit-web-report/data.json"
```

Expected: PASS with output containing `Gerrit Web Report 已生成:`.

- [ ] **Step 6: Commit checkpoint if commits are authorized**

Only run this if the user has explicitly authorized commits for this implementation session:

```bash
git add coredump-full-analysis/scripts/reporting/generate_gerrit_web_report.py tests/coredump_full_analysis/test_generate_gerrit_web_report.py
git commit -m "feat: generate Gerrit web report files"
```

---

### Task 4: Add optional local service behavior and tests

**Files:**
- Modify: `coredump-full-analysis/scripts/reporting/generate_gerrit_web_report.py`
- Modify: `tests/coredump_full_analysis/test_generate_gerrit_web_report.py`

- [ ] **Step 1: Add failing port-check test**

Append this test inside `GerritWebReportCollectionTests`:

```python
    def test_port_available_detects_bound_port(self):
        import socket

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            host, port = sock.getsockname()
            self.assertFalse(gerrit_report.port_available(host, port))
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
python3 -m unittest tests.coredump_full_analysis.test_generate_gerrit_web_report.GerritWebReportCollectionTests.test_port_available_detects_bound_port -v
```

Expected: FAIL with `AttributeError` for `port_available`.

- [ ] **Step 3: Add service helpers**

Insert this code before `parse_args()` in `coredump-full-analysis/scripts/reporting/generate_gerrit_web_report.py`:

```python

def port_available(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
        except OSError:
            return False
    return True


class ReportRequestHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args: Any, directory: Optional[str] = None, **kwargs: Any):
        super().__init__(*args, directory=directory, **kwargs)

    def log_message(self, format: str, *args: Any) -> None:
        sys.stderr.write("[gerrit-web-report] " + format % args + "\n")


def serve_directory(output_dir: Path, host: str, port: int, open_browser: bool) -> int:
    if not port_available(host, port):
        print(f"端口 {port} 已被占用，请使用 --port 指定其他端口", file=sys.stderr)
        return 3
    handler = lambda *args, **kwargs: ReportRequestHandler(*args, directory=str(output_dir), **kwargs)
    server = ThreadingHTTPServer((host, port), handler)
    url = f"http://{host}:{port}/index.html"
    print(f"Gerrit Web Report 服务已启动: {url}")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nGerrit Web Report 服务已停止")
    finally:
        server.server_close()
    return 0
```

- [ ] **Step 4: Run the service helper test**

Run:

```bash
python3 -m unittest tests.coredump_full_analysis.test_generate_gerrit_web_report.GerritWebReportCollectionTests.test_port_available_detects_bound_port -v
```

Expected: PASS.

- [ ] **Step 5: Run all report tests**

Run:

```bash
python3 -m unittest tests.coredump_full_analysis.test_generate_gerrit_web_report -v
```

Expected: PASS for all eight tests.

- [ ] **Step 6: Commit checkpoint if commits are authorized**

Only run this if the user has explicitly authorized commits for this implementation session:

```bash
git add coredump-full-analysis/scripts/reporting/generate_gerrit_web_report.py tests/coredump_full_analysis/test_generate_gerrit_web_report.py
git commit -m "feat: serve Gerrit web report locally"
```

---

### Task 5: Integrate report generation into run_analysis_agent.sh

**Files:**
- Modify: `run_analysis_agent.sh`

- [ ] **Step 1: Add option defaults**

Near the existing default variable section at the top of `run_analysis_agent.sh`, add:

```bash
GENERATE_GERRIT_WEB_REPORT=true
SERVE_GERRIT_WEB_REPORT=false
```

- [ ] **Step 2: Add help text entries**

In `show_help()`, after the existing `--reviewer <email>` line, add:

```text
    --no-gerrit-web-report      禁用分析结束后的 Gerrit 网页报告生成
    --serve-gerrit-web-report   分析结束后启动本地服务查看 Gerrit 网页报告
```

In the examples section, after the auto-fix-submit example, add:

```text

    # 分析完成后启动 Gerrit 网页报告本地服务
    $0 --packages dde-dock --auto-fix-submit --serve-gerrit-web-report
```

In the output files section, add:

```text
    <workspace>/6.总结报告/gerrit-web-report/index.html - Gerrit网页报告
```

- [ ] **Step 3: Add argument parsing cases**

In the `while [[ $# -gt 0 ]]; do case $1 in` block, after the `--reviewer)` case, add:

```bash
        --no-gerrit-web-report)
            GENERATE_GERRIT_WEB_REPORT=false
            shift
            ;;
        --serve-gerrit-web-report)
            SERVE_GERRIT_WEB_REPORT=true
            shift
            ;;
```

- [ ] **Step 4: Print selected report behavior with startup parameters**

After these existing lines:

```bash
echo "  自动修复提交: $AUTO_FIX_SUBMIT"
echo "  自动修复目标分支: $TARGET_BRANCH"
```

add:

```bash
echo "  Gerrit网页报告: $GENERATE_GERRIT_WEB_REPORT"
echo "  Gerrit网页服务: $SERVE_GERRIT_WEB_REPORT"
```

- [ ] **Step 5: Add the non-fatal helper function**

After `generate_workspace_reports()` in `run_analysis_agent.sh`, add:

```bash
generate_gerrit_web_report() {
    if [[ "$GENERATE_GERRIT_WEB_REPORT" != "true" ]]; then
        return 0
    fi

    local report_script="$SKILLS_DIR/coredump-full-analysis/scripts/reporting/generate_gerrit_web_report.py"
    if [[ ! -f "$report_script" ]]; then
        echo -e "${YELLOW}⚠️ 未找到 Gerrit 网页报告脚本: $report_script${NC}"
        return 0
    fi

    local cmd=(python3 "$report_script" --workspace "$WORKSPACE")
    if [[ "$SERVE_GERRIT_WEB_REPORT" == "true" ]]; then
        cmd+=(--serve)
    fi

    echo -e "${YELLOW}生成 Gerrit 网页报告...${NC}"
    if "${cmd[@]}"; then
        echo -e "${GREEN}✅ Gerrit 网页报告已生成: $WORKSPACE/$SUMMARY_DIR_NAME/gerrit-web-report/index.html${NC}"
    else
        echo -e "${YELLOW}⚠️ Gerrit 网页报告生成失败，主分析结果不受影响${NC}"
    fi
}
```

- [ ] **Step 6: Call the helper in background summary path**

In the background mode subshell, replace:

```bash
generate_workspace_reports "" >> "$LOG_DIR/analysis_workspace_summary.log" 2>&1
```

with:

```bash
generate_workspace_reports "" >> "$LOG_DIR/analysis_workspace_summary.log" 2>&1
generate_gerrit_web_report >> "$LOG_DIR/analysis_workspace_summary.log" 2>&1
```

- [ ] **Step 7: Call the helper in progress mode path**

After this existing line in the progress mode final output block:

```bash
generate_workspace_reports ""
```

add:

```bash
generate_gerrit_web_report
```

After the output list item:

```bash
echo "  跨包汇总: $WORKSPACE/$SUMMARY_DIR_NAME/all_packages_summary.md"
```

add:

```bash
echo "  Gerrit网页报告: $WORKSPACE/$SUMMARY_DIR_NAME/gerrit-web-report/index.html"
```

- [ ] **Step 8: Call the helper in foreground sequential path**

After this existing line in foreground mode:

```bash
generate_workspace_reports "$failed_csv"
```

add:

```bash
generate_gerrit_web_report
```

In both foreground success/failure output lists, after the workspace summary line, add:

```bash
echo "Gerrit网页报告: $WORKSPACE/$SUMMARY_DIR_NAME/gerrit-web-report/index.html"
```

- [ ] **Step 9: Verify shell syntax**

Run:

```bash
bash -n run_analysis_agent.sh
```

Expected: command exits 0 with no output.

- [ ] **Step 10: Verify help output includes the new flags**

Run:

```bash
bash run_analysis_agent.sh --help | grep -E -- '--no-gerrit-web-report|--serve-gerrit-web-report|gerrit-web-report/index.html'
```

Expected: output contains all three strings.

- [ ] **Step 11: Commit checkpoint if commits are authorized**

Only run this if the user has explicitly authorized commits for this implementation session:

```bash
git add run_analysis_agent.sh
git commit -m "feat: generate Gerrit web report from agent"
```

---

### Task 6: Update skill documentation

**Files:**
- Modify: `SKILL.md`
- Modify: `coredump-full-analysis/SKILL.md`

- [ ] **Step 1: Update root SKILL.md with report output and manual command**

In `SKILL.md`, add this section after the Agent usage section:

````markdown
## Gerrit 网页报告

分析结束后默认会尝试生成 Gerrit Web Report：

```text
<workspace>/6.总结报告/gerrit-web-report/index.html
<workspace>/6.总结报告/gerrit-web-report/data.json
```

该报告聚合 workspace 中已经提交到 Gerrit 的修复变更，并尽量补全 Gerrit 状态、Change 链接、项目、分支和 reviewer 信息。Gerrit 查询失败时仍会生成本地报告，相关记录会显示为未补全。

手动重新生成：

```bash
python3 coredump-full-analysis/scripts/reporting/generate_gerrit_web_report.py \
  --workspace /path/to/coredump-workspace
```

离线生成，不查询 Gerrit：

```bash
python3 coredump-full-analysis/scripts/reporting/generate_gerrit_web_report.py \
  --workspace /path/to/coredump-workspace \
  --no-gerrit-enrich
```
````

- [ ] **Step 2: Update coredump-full-analysis/SKILL.md output table**

In `coredump-full-analysis/SKILL.md`, add these rows to the “输出文件” table:

```markdown
| `<workspace>/6.总结报告/gerrit-web-report/index.html` | 已提交 Gerrit 修复变更的本地网页报告 |
| `<workspace>/6.总结报告/gerrit-web-report/data.json` | Gerrit 网页报告的结构化数据 |
```

- [ ] **Step 3: Add coredump-full-analysis manual usage section**

In `coredump-full-analysis/SKILL.md`, after the “输出文件” section, add:

````markdown
## Gerrit Web Report

完整分析或 Agent 分析结束后，默认会尝试生成 Gerrit Web Report：

```text
<workspace>/6.总结报告/gerrit-web-report/index.html
```

手动生成：

```bash
python3 coredump-full-analysis/scripts/reporting/generate_gerrit_web_report.py \
  --workspace /path/to/coredump-workspace
```

只使用本地记录、不查询 Gerrit：

```bash
python3 coredump-full-analysis/scripts/reporting/generate_gerrit_web_report.py \
  --workspace /path/to/coredump-workspace \
  --no-gerrit-enrich
```

生成后启动本地服务：

```bash
python3 coredump-full-analysis/scripts/reporting/generate_gerrit_web_report.py \
  --workspace /path/to/coredump-workspace \
  --serve
```

Agent 入口可用参数：

```text
--no-gerrit-web-report      禁用自动生成 Gerrit 网页报告
--serve-gerrit-web-report   分析完成后启动本地服务查看报告
```
````

- [ ] **Step 4: Verify docs mention the new script and output path**

Run:

```bash
grep -R "generate_gerrit_web_report.py\|gerrit-web-report/index.html\|--no-gerrit-web-report" -n SKILL.md coredump-full-analysis/SKILL.md
```

Expected: output contains matches in both files.

- [ ] **Step 5: Commit checkpoint if commits are authorized**

Only run this if the user has explicitly authorized commits for this implementation session:

```bash
git add SKILL.md coredump-full-analysis/SKILL.md
git commit -m "docs: document Gerrit web report"
```

---

### Task 7: End-to-end verification

**Files:**
- Verify: `coredump-full-analysis/scripts/reporting/generate_gerrit_web_report.py`
- Verify: `tests/coredump_full_analysis/test_generate_gerrit_web_report.py`
- Verify: `run_analysis_agent.sh`
- Verify: `SKILL.md`
- Verify: `coredump-full-analysis/SKILL.md`

- [ ] **Step 1: Run all Python unit tests for the new feature**

Run:

```bash
python3 -m unittest tests.coredump_full_analysis.test_generate_gerrit_web_report -v
```

Expected: PASS for all tests.

- [ ] **Step 2: Run shell syntax check**

Run:

```bash
bash -n run_analysis_agent.sh
```

Expected: command exits 0 with no output.

- [ ] **Step 3: Create a realistic temporary workspace**

Run:

```bash
tmp_workspace=$(mktemp -d)
mkdir -p "$tmp_workspace/5.崩溃分析/gerrit"
mkdir -p "$tmp_workspace/5.崩溃分析/dde-dock/version_1_2_3"
printf '%s\n' '{"commit_hash":"abc123def456","branch":"auto-fix/dde-dock/v1_2_3","target_branch":"develop/eagle","package":"dde-dock","version":"1.2.3","reviewers":["reviewer@example.com"],"time":"2026-05-08T10:00:00+08:00","status":"submitted"}' > "$tmp_workspace/5.崩溃分析/gerrit/commit_abc123def456.json"
printf '%s\n' '{"package":"dde-dock","version":"1.2.3","target_branch":"origin/develop/eagle","submitted":true,"commit_hashes":["abc123def456"],"auto_fixed":[{"description":"修复空指针崩溃","files_changed":["src/fix.cpp"]}],"clusters":[{"cluster":{"title":"QScreen geometry crash","signal":"SIGSEGV","count":12}}]}' > "$tmp_workspace/5.崩溃分析/dde-dock/version_1_2_3/auto_fix_clusters_result.json"
python3 coredump-full-analysis/scripts/reporting/generate_gerrit_web_report.py --workspace "$tmp_workspace" --no-gerrit-enrich
```

Expected: output contains `Gerrit Web Report 已生成:`.

- [ ] **Step 4: Verify generated report files and contents**

Run:

```bash
test -f "$tmp_workspace/6.总结报告/gerrit-web-report/index.html"
test -f "$tmp_workspace/6.总结报告/gerrit-web-report/data.json"
grep -q "abc123def456" "$tmp_workspace/6.总结报告/gerrit-web-report/index.html"
grep -q "QScreen geometry crash" "$tmp_workspace/6.总结报告/gerrit-web-report/index.html"
python3 -m json.tool "$tmp_workspace/6.总结报告/gerrit-web-report/data.json" >/dev/null
```

Expected: all commands exit 0.

- [ ] **Step 5: Verify CLI error for missing workspace**

Run:

```bash
python3 coredump-full-analysis/scripts/reporting/generate_gerrit_web_report.py --workspace /tmp/not-a-coredump-workspace-should-not-exist --no-gerrit-enrich
```

Expected: exit code 2 and stderr contains `workspace 不存在:`.

- [ ] **Step 6: Verify optional service detects occupied port**

Run:

```bash
python3 - <<'PY'
import socket
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
with TemporaryDirectory() as tmp:
    workspace = Path(tmp)
    (workspace / '5.崩溃分析').mkdir(parents=True)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
        result = subprocess.run([
            sys.executable,
            'coredump-full-analysis/scripts/reporting/generate_gerrit_web_report.py',
            '--workspace', str(workspace),
            '--no-gerrit-enrich',
            '--serve',
            '--port', str(port),
        ], text=True, capture_output=True)
        assert result.returncode == 3, result
        assert '端口' in result.stderr, result.stderr
PY
```

Expected: command exits 0.

- [ ] **Step 7: Verify git status excludes account changes from planned commit scope**

Run:

```bash
git status --short
```

Expected: output may include pre-existing `M accounts.json`; do not stage `accounts.json` unless the user explicitly instructs it. Expected new/modified implementation files are:

```text
M SKILL.md
M coredump-full-analysis/SKILL.md
M run_analysis_agent.sh
?? coredump-full-analysis/scripts/reporting/generate_gerrit_web_report.py
?? tests/
```

- [ ] **Step 8: Final commit checkpoint if commits are authorized**

Only run this if the user has explicitly authorized commits for this implementation session and previous checkpoints were not committed:

```bash
git add SKILL.md coredump-full-analysis/SKILL.md run_analysis_agent.sh coredump-full-analysis/scripts/reporting/generate_gerrit_web_report.py tests/coredump_full_analysis/test_generate_gerrit_web_report.py
git commit -m "feat: add Gerrit web report"
```

Do not stage `accounts.json`.

---

## Self-Review Checklist

- Spec coverage:
  - Local workspace aggregation: Task 2.
  - Gerrit enrichment with graceful failure: Task 3.
  - Static page and `data.json`: Task 3.
  - Optional local service: Task 4.
  - Agent integration and flags: Task 5.
  - Documentation: Task 6.
  - Verification commands: Task 7.
- Placeholder scan: every task contains concrete files, commands, expected outcomes, and code snippets where code changes are required.
- Type consistency:
  - `GerritFixRecord` fields match the approved spec.
  - Tests and implementation both use `collect_workspace_records()`, `generate_report()`, and `port_available()`.
  - Agent integration uses the spec flags `--no-gerrit-web-report` and `--serve-gerrit-web-report`.
