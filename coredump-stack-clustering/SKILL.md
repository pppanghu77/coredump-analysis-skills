---
name: coredump-stack-clustering
description: >-
  崩溃堆栈聚类分析。针对任意 deb 包（dde-file-manager / dde-dock / dde-control-center 等），
  从 Metabase DB10 下载指定系统版本/日期范围的原始崩溃数据（含堆栈），按自然周下载与分类，
  每周独立闭环：仅对当周最新稳定版本做堆栈聚类分析，跨周互不合并。
  触发词：崩溃聚类分析、堆栈聚类、crash clustering、按周分析崩溃、崩溃数据下载分析。
---

# 崩溃堆栈聚类分析

任意 deb 包的崩溃堆栈聚类分析。每个自然周独立闭环：下载 → 按版本分类 → 仅当周最新稳定版本聚类。
不同周之间互不合并。

## 前置条件

- `accounts.json` 中 Metabase 账号有效
- `python3`, `curl`, `jq` 可用

## 用法

```bash
cd coredump-analysis-skills

# 文管单周分析
python3 coredump-stack-clustering/scripts/run_pipeline.py \
    --package dde-file-manager \
    --sys-version 1075 \
    --start-date 2026-05-25 \
    --end-date 2026-05-31

# 文管多周分析（每周独立闭环，互不合并）
python3 coredump-stack-clustering/scripts/run_pipeline.py \
    --package dde-file-manager \
    --sys-version 1075 \
    --start-date 2026-05-11 \
    --end-date 2026-06-07

# 换个包：dde-dock
python3 coredump-stack-clustering/scripts/run_pipeline.py \
    --package dde-dock \
    --sys-version 1075 \
    --start-date 2026-05-11 \
    --end-date 2026-06-07

# 手动指定聚类目标版本（覆盖自动判定，每周均尝试聚类此版本）
python3 coredump-stack-clustering/scripts/run_pipeline.py \
    --package dde-file-manager \
    --sys-version 1075 \
    --start-date 2026-05-11 \
    --end-date 2026-06-07 \
    --target-version 6.0.62.1-1

# 复用已下载的周数据，跳过下载步骤（调试用）
python3 coredump-stack-clustering/scripts/run_pipeline.py \
    --package dde-file-manager \
    --sys-version 1075 \
    --start-date 2026-05-11 \
    --end-date 2026-06-07 \
    --skip-download
```

> 兼容入口 `bash scripts/run_pipeline.sh ...` 仍可用，等价于 `python3 run_pipeline.py`。

## 执行流程（每周循环）

主入口 `run_pipeline.py` 按周迭代，每周独立完成 3 步：

1. **下载** — 通过 subprocess 调用 `coredump-data-download/scripts/download_metabase_csv.sh`
   从 Metabase DB10 下载本周原始崩溃数据（含 StackInfo），
   文件名 `<package>_ALL_crash_<周日期范围>.csv`
2. **按版本分类** — subprocess 调用 `split_by_version.py` 将本周数据按 Version 列拆分到
   `2_split_by_version/<周日期范围>/`
3. **选取最新稳定版本 + 聚类** — 内部判定（可选手动覆盖），再 subprocess 调用
   `stack_analyzer.py` 仅对目标版本聚类
   - 清洗堆栈帧（去掉线程号、帧号、十六进制地址、偏移量）
   - 基于 Top-N 帧（含函数名+库路径）签名做相似度比较，避免深层噪声导致过度分裂
   - 两阶段聚类：贪心分类（SequenceMatcher 相似度 ≥0.75）+ 隐式合并
   - 跨架构（x86_64 / aarch64）的同一 bug 自动归并

**"最新稳定版本"判定规则**：
排除含 `+` (变体如 `+textindex`)、`.crashN` (测试版)、无 debian 修订号 `-N` 的版本；
剩余版本按语义版本号排序取最大者。

**stable_hash 策略**：
对**完整 cleaned stack 全部帧**做 hash（栈顶帧去地址/偏移后的"函数名+库路径"序列）。
- 不再截断栈顶 top_n，也不再过滤 NOISE_LIBS——`clean_stack_trace` 已统一去除线程号/帧号/
  十六进制地址/偏移，剩余序列本身就是稳定特征。
- 过滤 NOISE_LIBS 会掏空"符号缺失(n/a 占满)的崩溃"整栈，导致完全不同的崩溃塌缩成同一 hash；
  去除过滤后每个崩溃精确对应唯一 hash，趋势统计不失真。
- 跨架构（x86_64 / aarch64）的同一崩溃因库路径不同会得到不同 hash（分架构溯源）。

**跨周 hash 趋势**（`build_hash_trend.py`，pipeline 末尾自动调用）：
扫描所有周的 `analysis_<version>.csv`，按 Crash Hash 聚合各周占比，输出
`_hash_trend_by_week.csv`（按最新一周占比降序，Cleaned Stack 列保留原始换行）。
同一 hash 在单周内若有多行则占比/count 求和合并。亦可单独运行：

```bash
python3 coredump-stack-clustering/scripts/build_hash_trend.py \
    --analysis-root data/workspace_<package>_<日期范围>/3_version_analysis_results
```

## 输出文件

```
data/workspace_<package>_<start>_<end>/
├── 1_download/
│   ├── <package>_ALL_crash_<周1>.csv
│   ├── <package>_ALL_crash_<周2>.csv
│   ├── <package>_summary_<周>.csv   (DB9 崩溃汇总,每周一个,看板崩溃率数据源)
│   └── ...
├── 2_split_by_version/
│   ├── <周1日期范围>/
│   │   ├── version_*.csv
│   │   └── _version_statistics.csv
│   ├── <周2日期范围>/
│   │   └── ...
│   └── ...
├── 3_version_analysis_results/
│   ├── _summary_report.csv         (聚合所有周)
│   ├── _hash_trend_by_week.csv     (跨周 hash 占比趋势，按最新一周降序)
│   ├── <周1日期范围>/
│   │   ├── _week_summary.csv
│   │   └── <latest_stable_version_of_week1>/
│   │       └── analysis_<version>.csv
│   ├── <周2日期范围>/
│   │   └── ...
│   └── ...
```

`analysis_<version>.csv` 列：

| 列 | 含义 |
|----|------|
| Crash Hash | stable_hash（完整 cleaned stack 全部帧的 sha256 前 12 位） |
| Count | 该类型崩溃数 |
| Percentage | 占当周目标版本总数比例 |
| Stack Summary | 样本堆栈前 5 行 |
| Process Stats | Exe 进程频次统计 |
| Full Stack Trace | 样本完整堆栈 |
| Cleaned Stack (No Addr) | 去地址后的堆栈 |
| All Traces (Max 5) | 最多 5 个样本 |
| Notes | 留空供人工标注 |

## 命令行参数

| 参数 | 必填 | 说明 |
|------|------|------|
| `--package NAME` | 是 | 包名 (如 `dde-file-manager`) |
| `--sys-version N` | 是 | 系统版本号 (如 `1075`) |
| `--start-date YYYY-MM-DD` | 是 | 开始日期 |
| `--end-date YYYY-MM-DD` | 是 | 结束日期 |
| `--workspace DIR` | 否 | 工作目录 (默认: `data/workspace_<package>_<日期范围>/`) |
| `--target-version V` | 否 | 手动指定聚类目标版本，覆盖自动判定 |
| `--skip-download` | 否 | 复用 1_download/ 下已有的周数据，跳过下载 |

## 依赖

- `coredump-data-download/scripts/download_metabase_csv.sh` — Metabase DB10 数据下载
- `accounts.json` — Metabase (app@deepin.org) 认证

## 脚本清单

| 脚本 | 作用 |
|------|------|
| `run_pipeline.py` | 主入口，按周循环：下载 → 按版本分类 → 聚类，末尾生成周/全局汇总与跨周趋势 |
| `download_crashes.sh` | Metabase 原始数据下载（被 `run_pipeline.py` 调用） |
| `split_by_version.py` | 按 Version 列拆分当周数据 |
| `stack_analyzer.py` | 堆栈聚类，生成 `analysis_<version>.csv`（含精确 stable_hash） |
| `build_hash_trend.py` | 跨周 hash 占比趋势汇总，生成 `_hash_trend_by_week.csv` |

## 看板可视化

`kanban/` 是只读看板，数据全部来自 pipeline 产出物，**无独立数据源、不可编辑**：

- **hash 趋势/占比** ← `<workspace>/3_version_analysis_results/_hash_trend_by_week.csv`
- **崩溃率时间序列** ← `<workspace>/1_download/<package>_summary_<周>.csv`

启动：

```bash
cd coredump-stack-clustering/kanban && python3 server.py
# → http://127.0.0.1:8765/
```

特性：

- **应用(package)自动发现**：扫描 `data/workspace_*` 目录；一个 package 有多份 workspace 时自动取 end_date 最大者。
- **hash 自动同步**：趋势表每个 hash 自动成一条 issue，按最新周占比降序；severity 按占比自动分档(≥10% P0 / ≥1% P1 / ≥0.1% P2 / 其余 P3)。
- **日期对齐**：trend 与 summary 统一为周尾日 ISO 日期，前端占比趋势图与崩溃率图共享时间轴。
- **实时刷新**：SSE 监控 workspace 的 CSV mtime，pipeline 重跑后看板自动刷新。
- 前端 `kanban/index.html` 零改动，直接消费 `/api/{apps,issues,trend,summary}`。

| 文件 | 作用 |
|------|------|
| `kanban/server.py` | 只读看板服务器(8765 端口),读 workspace 返回 JSON + SSE 推送 |
| `kanban/index.html` | ECharts 前端看板(崩溃率折线 + 各 hash 占比趋势 + 看板列) |
