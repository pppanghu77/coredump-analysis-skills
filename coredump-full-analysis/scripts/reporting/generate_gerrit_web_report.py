#!/usr/bin/env python3
import argparse
import json
import re
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
    record_source: str = "workspace"
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
            "record_source",
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


def read_text_file(path: Path) -> str:
    return path.read_text(encoding="utf-8")


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
    prefix = "version_"
    if not version_part.startswith(prefix):
        return package, ""
    return package, version_part[len(prefix):].replace("_", ".")


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
            record_source="workspace",
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


def parse_manual_change_url(text: str) -> Optional[Dict[str, Any]]:
    match = re.search(r"https?://gerrit\.uniontech\.com/c/([^/\s]+)/\+/(\d+)", text)
    if not match:
        return None
    project = match.group(1)
    change_number = int(match.group(2))
    return {
        "project": project,
        "change_number": change_number,
        "gerrit_url": f"https://gerrit.uniontech.com/c/{project}/+/{change_number}",
    }


def collect_manual_change_specs(manual_change_files: List[Path], manual_change_urls: List[str]) -> Tuple[List[Dict[str, Any]], List[ReportWarning]]:
    specs: List[Dict[str, Any]] = []
    warnings: List[ReportWarning] = []
    seen = set()

    for raw_url in manual_change_urls:
        parsed = parse_manual_change_url(raw_url.strip())
        if not parsed:
            warnings.append(ReportWarning(f"manual:{raw_url}", "无法解析 Gerrit 链接"))
            continue
        key = (parsed["project"], parsed["change_number"])
        if key not in seen:
            seen.add(key)
            specs.append(parsed)

    for path in manual_change_files:
        try:
            content = read_text_file(path)
        except OSError as exc:
            warnings.append(ReportWarning(path.as_posix(), f"文件读取失败: {exc}"))
            continue
        for lineno, line in enumerate(content.splitlines(), start=1):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            parsed = parse_manual_change_url(stripped)
            if not parsed:
                warnings.append(ReportWarning(f"{path.as_posix()}:{lineno}", "无法解析 Gerrit 链接"))
                continue
            key = (parsed["project"], parsed["change_number"])
            if key not in seen:
                seen.add(key)
                specs.append(parsed)

    return specs, warnings


def manual_record_from_spec(spec: Dict[str, Any]) -> GerritFixRecord:
    project = first_text(spec.get("project"))
    change_number = spec.get("change_number")
    return GerritFixRecord(
        commit_hash=f"manual-change-{project}-{change_number}",
        record_source="manual",
        package=project,
        project=project,
        change_number=change_number,
        gerrit_url=first_text(spec.get("gerrit_url")),
        local_status="manual",
    )


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


def collect_manual_records(manual_change_files: List[Path], manual_change_urls: List[str]) -> Tuple[List[GerritFixRecord], List[ReportWarning]]:
    specs, warnings = collect_manual_change_specs(manual_change_files, manual_change_urls)
    records = [manual_record_from_spec(spec) for spec in specs]
    return sorted(records, key=lambda item: (item.project, item.change_number or 0, item.commit_hash)), warnings


def dedupe_records(records: List[GerritFixRecord]) -> List[GerritFixRecord]:
    merged: Dict[str, GerritFixRecord] = {}
    order: List[str] = []
    for record in records:
        key = ""
        if record.project and record.change_number is not None:
            key = f"change:{record.project}:{record.change_number}"
        elif record.commit_hash:
            key = f"commit:{record.commit_hash}"
        else:
            key = f"fallback:{len(order)}"
        existing = merged.get(key)
        if existing:
            existing.merge(record)
        else:
            merged[key] = record
            order.append(key)
    return [merged[key] for key in order]


def normalize_status(record: GerritFixRecord) -> str:
    if record.status and record.status != "Unknown":
        return record.status
    return first_text(record.local_status, record.status, "Unknown")


def build_summary(records: List[GerritFixRecord], warnings: List[ReportWarning], workspace: Path) -> Dict[str, Any]:
    statuses: Dict[str, int] = {}
    projects = set()
    packages = set()
    versions = set()
    source_counts: Dict[str, int] = {}
    latest_updated = ""
    enriched_count = 0
    for record in records:
        status = normalize_status(record)
        statuses[status] = statuses.get(status, 0) + 1
        source = first_text(record.record_source, "unknown")
        source_counts[source] = source_counts.get(source, 0) + 1
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
        "source_counts": source_counts,
        "gerrit_enriched": enriched_count,
        "gerrit_not_enriched": len(records) - enriched_count,
        "warning_count": len(warnings),
    }


def load_all_packages_valid_records(workspace: Path) -> int:
    path = workspace / "6.总结报告" / "all_packages_summary.json"
    if not path.exists():
        return 0
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return 0
    totals = data.get("totals") or {}
    return first_int(totals.get("valid_records"))


def load_workspace_record_coverage(workspace: Path, record: GerritFixRecord) -> int:
    if not record.source_file:
        return first_int(record.crash_count)
    path = workspace / Path(record.source_file)
    if not path.exists():
        return first_int(record.crash_count)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return first_int(record.crash_count)
    return first_int(
        data.get("total_crashes"),
        data.get("total_fixable_crashes"),
        record.crash_count,
    )


def build_actual_effectiveness(records: List[GerritFixRecord], workspace: Path) -> Dict[str, Any]:
    workspace_records = [record for record in records if record.record_source == "workspace"]
    total_valid_records = load_all_packages_valid_records(workspace)
    merged_records = [record for record in workspace_records if normalize_status(record) == "MERGED"]
    new_records = [record for record in workspace_records if normalize_status(record) == "NEW"]
    merged_coverage = sum(load_workspace_record_coverage(workspace, record) for record in merged_records)
    new_coverage = sum(load_workspace_record_coverage(workspace, record) for record in new_records)
    merged_rate = (merged_coverage / total_valid_records * 100.0) if total_valid_records else 0.0
    new_rate = (new_coverage / total_valid_records * 100.0) if total_valid_records else 0.0
    if merged_records:
        accuracy_text = "需结合合入后回归结果人工复核"
    else:
        accuracy_text = "N/A（本次实际自动产出中暂无已合入代码）"
    return {
        "workspace_record_count": len(workspace_records),
        "merged_record_count": len(merged_records),
        "new_record_count": len(new_records),
        "total_valid_records": total_valid_records,
        "merged_coverage": merged_coverage,
        "new_coverage": new_coverage,
        "merged_resolution_rate": round(merged_rate, 2),
        "new_resolution_rate": round(new_rate, 2),
        "analysis_accuracy_text": accuracy_text,
    }


def build_payload(workspace: Path, records: List[GerritFixRecord], warnings: List[ReportWarning]) -> Dict[str, Any]:
    return {
        "summary": {
            **build_summary(records, warnings, workspace),
            "actual_effectiveness": build_actual_effectiveness(records, workspace),
        },
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
    :root {{ --bg:#f6f8fb; --card:#fff; --text:#172033; --muted:#667085; --line:#d9e2ec; --accent:#2563eb; --danger:#b42318; --ok:#067647; --manual:#7c3aed; }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; background:var(--bg); color:var(--text); }}
    header, main, .toolbar, .cards {{ padding-left:32px; padding-right:32px; }}
    header {{ padding-top:28px; padding-bottom:12px; }}
    h1 {{ margin:0 0 8px; font-size:28px; }}
    .muted {{ color:var(--muted); font-size:13px; }}
    .cards {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:12px; padding-top:12px; padding-bottom:12px; }}
    .card {{ background:var(--card); border:1px solid var(--line); border-radius:12px; padding:14px; }}
    .card strong {{ display:block; font-size:24px; margin-top:4px; }}
    .panel {{ background:var(--card); border:1px solid var(--line); border-radius:12px; padding:16px 18px; margin:0 32px 12px; }}
    .panel h2 {{ margin:0 0 8px; font-size:18px; }}
    .panel p {{ margin:8px 0; line-height:1.6; font-size:14px; }}
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
    .source {{ display:inline-block; padding:2px 8px; border-radius:999px; background:#f5f3ff; color:var(--manual); }}
    .empty {{ background:var(--card); border:1px solid var(--line); border-radius:12px; padding:24px; text-align:center; }}
    details {{ max-width:420px; }}
    pre {{ white-space:pre-wrap; margin:8px 0 0; color:var(--muted); }}
    a {{ color:var(--accent); }}
  </style>
</head>
<body>
  <header><h1>Gerrit Web Report</h1><div class="muted" id="meta"></div></header>
  <section class="cards" id="cards"></section>
  <section class="panel" id="actual-effectiveness" style="display:none">
    <h2>本次实际情况</h2>
    <div id="actual-effectiveness-body"></div>
  </section>
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
      <thead><tr><th>状态</th><th>来源</th><th>Package</th><th>Version</th><th>Project</th><th>Subject</th><th>Commit</th><th>Change</th><th>Branch</th><th>Crash</th><th>Files</th><th>Owner/Reviewer</th><th>Updated</th><th>链接</th><th>详情</th></tr></thead>
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
    const rowStatus = (record) => record.status && record.status !== 'Unknown' ? record.status : (record.local_status || record.status || 'Unknown');
    const blob = (record) => [record.package, record.version, record.project, record.commit_subject, record.commit_hash, record.fix_description, record.cluster_title, record.record_source, record.change_number].join(' ').toLowerCase();

    function appendTextCell(row, value) {{
      const cell = doc.createElement('td');
      cell.textContent = valueText(value);
      row.appendChild(cell);
      return cell;
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
        ['Unknown', statuses.Unknown || 0], ['手工补充', (summary.source_counts || {{}}).manual || 0], ['自动采集', (summary.source_counts || {{}}).workspace || 0], ['项目数', summary.project_count || 0], ['包数', summary.package_count || 0],
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

    function renderActualEffectiveness() {{
      const block = summary.actual_effectiveness || null;
      if (!block) return;
      const panel = get('actual-effectiveness');
      const body = get('actual-effectiveness-body');
      const paragraphs = [];
      paragraphs.push(`本次统计仅包含 workspace 实际自动产出的提交，不包含手工补充记录。本次实际自动产出 ${{block.workspace_record_count || 0}} 条 Gerrit 变更，其中已合入 ${{block.merged_record_count || 0}} 条，待合入（NEW）${{block.new_record_count || 0}} 条。`);
      paragraphs.push(`按“已合入代码才计入已解决崩溃”的严格口径，当前已解决崩溃数为 ${{block.merged_coverage || 0}}，占全部 ${{block.total_valid_records || 0}} 条崩溃数据的 ${{(block.merged_resolution_rate || 0).toFixed(2)}}%。`);
      if ((block.new_record_count || 0) > 0) {{
        paragraphs.push(`当前待合入变更可覆盖 ${{block.new_coverage || 0}} 条崩溃记录，占全部崩溃数据的 ${{(block.new_resolution_rate || 0).toFixed(2)}}%。`);
      }}
      paragraphs.push(`崩溃分析正确率：${{block.analysis_accuracy_text || 'N/A'}}。`);
      body.replaceChildren(...paragraphs.map((text) => {{
        const p = doc.createElement('p');
        p.textContent = text;
        return p;
      }}));
      panel.style.display = 'block';
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
        const status = rowStatus(record);
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

        const sourceCell = doc.createElement('td');
        const sourceBadge = doc.createElement('span');
        sourceBadge.className = 'source';
        sourceBadge.textContent = record.record_source || 'workspace';
        sourceCell.appendChild(sourceBadge);
        row.appendChild(sourceCell);

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
        if (record.gerrit_url && (record.gerrit_url.startsWith('http://') || record.gerrit_url.startsWith('https://'))) {{
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

    fillSelect('statusFilter', Array.from(new Set(records.map(rowStatus))).sort());
    fillSelect('packageFilter', Array.from(new Set(records.map((record) => record.package).filter(Boolean))).sort());
    fillSelect('projectFilter', Array.from(new Set(records.map((record) => record.project).filter(Boolean))).sort());
    fillSelect('branchFilter', Array.from(new Set(records.map((record) => record.branch || record.target_branch).filter(Boolean))).sort());
    renderCards();
    renderActualEffectiveness();
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


def default_manual_change_file() -> Path:
    return REPO_ROOT / "coredump-full-analysis" / "config" / "manual_gerrit_changes.txt"


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
            if record.record_source == "manual" and record.change_number is not None:
                change = client.get_change_by_number(record.change_number, record.project or record.package)
            else:
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
            record.reviewers = merge_list(record.reviewers, list_text(change.get("reviewers")))
            record.updated = first_text(change.get("updated"), record.updated)
            record.commit_hash = first_text(change.get("revision"), record.commit_hash)
            record.gerrit_enriched = True
            record.enrichment_error = ""
        except Exception as exc:
            record.enrichment_error = str(exc)


def generate_report(
    workspace: Path,
    output_dir: Optional[Path] = None,
    enrich: bool = True,
    manual_change_files: Optional[List[Path]] = None,
    manual_change_urls: Optional[List[str]] = None,
) -> Path:
    if not workspace.exists():
        raise FileNotFoundError(f"workspace 不存在: {workspace}")
    output_dir = output_dir or default_output_dir(workspace)
    manual_change_files = manual_change_files or []
    manual_change_urls = manual_change_urls or []
    records, warnings = collect_workspace_records(workspace)
    manual_records, manual_warnings = collect_manual_records(manual_change_files, manual_change_urls)
    records.extend(manual_records)
    warnings.extend(manual_warnings)
    if enrich and records:
        enrich_records(records)
    records = dedupe_records(records)
    records.sort(key=lambda item: (item.project or item.package, item.change_number or 0, item.version, item.commit_hash))
    payload = build_payload(workspace, records, warnings)
    write_data_json(payload, output_dir)
    write_index_page(payload, output_dir)
    return output_dir


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


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="生成已提交 Gerrit 修复变更的本地网页报告")
    parser.add_argument("--workspace", required=True, help="coredump workspace 路径")
    parser.add_argument("--output-dir", help="输出目录，默认 <workspace>/6.总结报告/gerrit-web-report")
    parser.add_argument("--no-gerrit-enrich", action="store_true", help="只使用本地记录，不查询 Gerrit")
    parser.add_argument("--manual-change-file", action="append", default=[], help="额外 Gerrit 提交清单文件，每行一个 Gerrit change 链接")
    parser.add_argument("--manual-change-url", action="append", default=[], help="额外 Gerrit change 链接，可多次传入")
    parser.add_argument("--serve", action="store_true", help="生成后启动本地 HTTP 服务")
    parser.add_argument("--host", default="127.0.0.1", help="本地服务监听地址")
    parser.add_argument("--port", type=int, default=8765, help="本地服务端口")
    parser.add_argument("--open", action="store_true", help="启动服务后尝试打开浏览器")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    workspace = Path(args.workspace).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve() if args.output_dir else None
    manual_change_files = [Path(item).expanduser().resolve() for item in args.manual_change_file]
    default_manual_file = default_manual_change_file()
    if default_manual_file.exists() and default_manual_file not in manual_change_files:
        manual_change_files.append(default_manual_file)
    try:
        final_output_dir = generate_report(
            workspace,
            output_dir,
            enrich=not args.no_gerrit_enrich,
            manual_change_files=manual_change_files,
            manual_change_urls=args.manual_change_url,
        )
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
