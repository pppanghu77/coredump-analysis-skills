---
name: dde-filemanager-crash-analysis
description: >-
  dde-file-manager 崩溃数据收集与分析。从 Metabase DB10 下载指定系统版本/日期范围的
  原始崩溃数据（含堆栈），按周分割下载，进行堆栈聚类分析，生成按版本和领域归类的分析报告。
  触发词：文管崩溃分析、dde-file-manager 崩溃、文件管理器崩溃、崩溃数据下载。
---

# dde-file-manager 崩溃分析

一键完成文管崩溃数据下载 → 分类 → 堆栈分析流程。

## 前置条件

- `accounts.json` 中 Metabase 账号有效
- `curl`, `jq`, `python3` 可用

## 用法

```bash
cd coredump-analysis-skills

# 单周分析
bash dde-filemanager-crash-analysis/scripts/run_pipeline.sh \
    --sys-version 1075 \
    --start-date 2026-05-25 \
    --end-date 2026-05-31

# 多周分析（自动按自然周分割下载）
bash dde-filemanager-crash-analysis/scripts/run_pipeline.sh \
    --sys-version 1075 \
    --start-date 2026-05-01 \
    --end-date 2026-06-08
```

## 执行流程

1. **数据下载** — 调用 `download_metabase_csv.sh` 从 Metabase DB10 下载原始崩溃数据（含 StackInfo），按自然周分割，文件名标注数据时间范围
2. **按版本分类** — `split_by_version.py` 将数据按 Version 列拆分
3. **堆栈分析** — `stack_analyzer.py` 对每个版本进行堆栈聚类，生成按领域的崩溃分类统计

## 输出文件

```
data/workspace_<ts>/
├── 1_download/
│   └── dde-file-manager_ALL_crash_<日期范围>.csv
├── 2_split_by_version/
│   └── version_*.csv
└── 3_version_analysis_results/
    ├── _summary_report.csv
    └── <version>/
        ├── analysis_<version>.csv
        └── analysis_<version>_keyword_stats.csv
```

## 依赖

- `coredump-data-download/scripts/download_metabase_csv.sh` — Metabase DB10 数据下载
- `accounts.json` — Metabase (app@deepin.org) 认证
