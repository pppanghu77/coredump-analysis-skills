---
name: coredump-analysis
description: >-
  DDE/UOS coredump crash analysis workflow. Run or maintain the crash-analysis
  automation across packages.txt: download crash data, deduplicate, clone source,
  install deb/dbgsym, analyze with GDB/addr2line, generate reports, triage and
  submit real Gerrit fixes. Trigger words: 崩溃分析, coredump分析, 完整分析, 全量分析,
  crash analysis, skill优化, 自动修复, Gerrit候选.
---

# Coredump Crash Analysis (DDE/UOS)

Routing skill for the coredump-analysis-skills project. Keep this file small; load task-specific references only when needed.

## Project Root

Use the actual loaded skill root as `$SKILLS_DIR`; examples must not hardcode machine-specific paths.

```bash
cd "$SKILLS_DIR"
python3 check_skill_sync.py  # after repo-managed doc/reference edits
```

The current repo checkout is the distributable source of truth. Do not sync to or depend on user-private Hermes cache paths.

## Non-Negotiable Rules

1. Metabase crash data download must filter by package name, not Gerrit project name.
2. Crash-analysis Gerrit commit subjects must carry `[coredump-analysis]`.
3. Do not count `coredump-analysis-report.md` commits as real source-code crash fixes.
4. Before broad repo/skill optimization, present a plan and wait for approval.
5. Before full/multi-step analysis runs, present steps, risks, expected outputs, and monitoring.

For `project:pkg1,pkg2` entries in `packages.txt`, the project side is only for source/Gerrit handling; crash-data and deb/dbgsym downloads must use each concrete package token on the right-hand side.

## Main Entrypoints

For account checks, package scope, workspace layout, monitoring, and recovery, load `references/analysis-runbook.md`.

```bash
bash run_analysis_agent.sh --background --progress 180      # packages.txt scope
bash run_analysis_agent.sh --packages dde-dock --background # single package
```

Key defaults: auto-fix-submit enabled; `analyze_crash_complete.sh --max-crashes` defaults to `0`; `analysis.addr2line_max_frames` defaults to `500`, and automatic deep dive raises the effective addr2line depth to at least `600` when triggered.

## First Stops and Pitfalls

Inspect `6.总结报告/` rollups before logs: `analysis_summary_final.md` (human-facing final report), `package_status.tsv`, `version_status.tsv`, `run_manifest.*`, `retry_summary.md`, `auto_fix_overview.*`, `new_crashes_overview.*`.

Remember: empty CSV can be legitimate; shell wrappers need correct `PYTHONPATH`; report-only/Markdown-only commits are not real fixes; Gerrit `no new changes` requires Change-Id lookup.

## Reference Loading

Only route to local reference files that exist in this distributable repo.

Running/monitoring/recovery:
- `references/analysis-runbook.md`
- `references/empty-data-and-fix-mapping-closure.md`
- `references/auto-fix-overview.md`
- `references/unique-crash-baseline.md`

Data-download correctness:
- `references/download-by-package-not-project.md`

Enhanced/root-cause depth:
- `references/enhanced-analysis.md`
- `references/automatic-deep-dive-policy.md`
- `references/analysis-depth-pitfalls.md`
- `references/source-graph-context.md`

Auto-fix/Gerrit:
- `references/fixer-architecture.md`
- `references/auto-fix-branch-and-retry-handling.md`
- `references/gerrit-submission-triage.md`

Package-specific triage and maintenance:
- `references/deepin-update-ui-updater-watcher-triage.md`
- `references/README.md`

If an old cache-only note becomes necessary, add a sanitized project-local copy under `references/`, then update this routing list and `references/README.md`.

## Maintenance Checklist

Keep examples generic with `$SKILLS_DIR`; update references when behavior changes; run relevant checks plus `python3 check_skill_sync.py`.
