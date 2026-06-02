---
name: coredump-full-analysis
description: 一站式崩溃分析自动化流程。用于对 DDE/UOS 包执行完整崩溃分析，默认下载并分析所有能获取的崩溃数据，可选按日期、系统版本和架构过滤；流程包含数据下载、筛选去重、源码切换、deb/dbgsym 处理、版本级分析、完整报告和总结报告生成。触发词：完整崩溃分析、一站式崩溃分析、全流程崩溃分析、自动化崩溃分析、全量崩溃分析。
---

# Coredump 完整崩溃分析自动化流程

这个 skill 负责 `coredump-full-analysis/` 内的一站式分析脚本。当前脚本默认不限制日期：未传 `--start-date` / `--end-date` 时，会下载接口当前能返回的全部崩溃数据。

约定：以下命令示例中的 `$SKILLS_DIR` 表示当前 skill 的实际加载目录。

## 先做配置检查

账号入口统一为仓库根目录的 `accounts.json`：

```bash
$SKILLS_DIR/accounts.json
```

常用检查命令：

```bash
cd "$SKILLS_DIR"
sed -n '1,160p' accounts.json
```

`coredump-full-analysis/config/` 目录中仅保留运行时仍需要的静态配置文件；账号信息统一只保存在仓库根目录 `accounts.json`。

直接调用 `analyze_crash_complete.sh` 时，脚本会直接检查仓库根目录 `accounts.json`。缺少必需账号或密码时，流程立即停止。

配置说明：

| 配置 | 用途 | 当前行为 |
|------|------|----------|
| `metabase.account` | 下载崩溃 CSV | 必填，缺失即中止 |
| `gerrit.account` | 克隆源码、切换版本 | 必填，缺失即中止 |
| `shuttle.account` | 下载 deb/dbgsym | 必填，缺失即中止 |
| `system.sudo_password` | 安装 deb/dbgsym | 必填，缺失即中止 |
| `paths.workspace` | 默认工作目录根路径 | 可选；不填则使用 `$HOME` |

## 快速开始

一键分析单包所有能下载的崩溃：

```bash
cd "$SKILLS_DIR"

bash coredump-full-analysis/scripts/analyze_crash_complete.sh \
    --package dde-session-shell \
    --sys-version 1070-1075
```

按日期过滤时再显式传入日期：

```bash
bash coredump-full-analysis/scripts/analyze_crash_complete.sh \
    --package dde-session-shell \
    --start-date 2026-03-10 \
    --end-date 2026-04-09 \
    --sys-version 1070-1075
```

只传单侧日期也支持：

```bash
# 从指定日期到最新可下载数据
bash coredump-full-analysis/scripts/analyze_crash_complete.sh \
    --package dde-session-shell \
    --start-date 2026-03-10

# 从最早可下载数据到指定日期
bash coredump-full-analysis/scripts/analyze_crash_complete.sh \
    --package dde-session-shell \
    --end-date 2026-04-09
```

## 推荐入口

| 场景 | 命令 |
|------|------|
| 每7天自动化流程 | 仓库根目录执行 `bash run_analysis_cron.sh`（默认最近7天，无数据自动回退15天） |
| 单包完整流程 | `bash coredump-full-analysis/scripts/analyze_crash_complete.sh --package <pkg>` |
| 仅下载数据 | `bash coredump-full-analysis/scripts/step1_download.sh --package <pkg>` |
| 多包全量 Agent（手工入口） | 仓库根目录执行 `bash run_analysis_agent.sh` |

`run_analysis_agent.sh` 不在本目录内，但会调用本 skill 的完整流程脚本。多包分析建议用 Agent；单包调试建议直接用 `analyze_crash_complete.sh`。

## 日期范围规则

当前这些脚本都已同步为“默认不限制日期”：

- `analyze_crash_complete.sh`
- `step1_download.sh`


日期显示规则：

| 参数 | 数据范围 |
|------|----------|
| 不传 `--start-date` 和 `--end-date` | 全部可下载数据（不按日期过滤） |
| 同时传 `--start-date` 和 `--end-date` | 指定日期范围 |
| 只传 `--start-date` | 从开始日期到最新可下载数据 |
| 只传 `--end-date` | 从最早可下载数据到结束日期 |

## 工作目录

不指定 `--workspace` 时，完整流程脚本自动创建：

```text
~/coredump-workspace-YYYYMMDD-HHMMSS/
├── 1.数据下载/
├── 2.数据筛选/
├── 3.代码管理/
├── 4.包管理/downloads/
├── 5.崩溃分析/
├── 6.修复补丁/
└── 6.总结报告/
```

如果配置了 `accounts.json.paths.workspace`，则自动创建到该目录下，例如 `/data/uos/coredump-workspace-YYYYMMDD-HHMMSS/`。

指定工作目录：

```bash
bash coredump-full-analysis/scripts/analyze_crash_complete.sh \
    --package dde-session-shell \
    --workspace /home/uos/coredump-workspace-manual
```

## 执行流程

`analyze_crash_complete.sh` 当前流程：

1. 检查账号配置和依赖。
2. 创建工作目录。
3. 下载崩溃 CSV。
4. 筛选、去重并生成版本统计。
5. 按版本循环：切换源码、下载包、安装包、分析崩溃。
6. 生成 `full_analysis_report.md` 和 `AI_analysis_report.md`。
7. 基于 `filtered_<package>_crash_data.csv` 更新持久化唯一崩溃基线，产出新增崩溃 diff。
8. 生成 `6.总结报告/final_conclusion.md` 和 `summary_statistics.json`。

运行特性：

- `accounts.json` 中必需账号或密码缺失时，流程立即中止。
- 某版本 deb/dbgsym 不存在时，跳过安装，继续基于崩溃数据生成分析。
- deb/dbgsym 版本匹配支持常见 Debian 构建后缀，例如 `-1`、`+build`、`.1-1`。
- 源码 tag 无精确匹配时，源码脚本会保留当前可用状态；分析仍继续。
- 崩溃数据下载始终按包名（package）查询，不按 Gerrit project 名查询；像 `base/lightdm:lightdm`、`go-lib:golang-github-linuxdeepin-go-lib-dev` 这类映射项，下载阶段必须传右侧包名。
- `analyze_with_fix_mapping.py` 现已兼容可选 `--project` 参数：`--package` 仍决定筛选 CSV/崩溃归属，`--project` 仅用于 Gerrit/修复映射场景，不能反过来替代下载包名。
- `generate_ai_report.py` 自带 `scripts/` 路径注入，调用时不需要额外手工设置 `PYTHONPATH` 才能导入 `package_rules.py`。

## 输出文件

主要产物：

| 路径 | 说明 |
|------|------|
| `<workspace>/1.数据下载/download_*/<package>_X86_crash_*.csv` | 原始崩溃数据 |
| `<workspace>/2.数据筛选/filtered_<package>_crash_data.csv` | 筛选去重后的崩溃数据 |
| `<workspace>/2.数据筛选/<package>_crash_statistics.json` | 统计摘要 |
| `<workspace>/2.数据筛选/<package>_crash_versions.txt` | 待分析版本列表 |
| `<workspace>/2.数据筛选/<package>_crash_baseline_diff.json` | 与历史唯一崩溃基线的增量比对结果 |
| `<workspace>/2.数据筛选/<package>_new_crashes.csv` | 本次发现的新增唯一崩溃 |
| `<workspace>/3.代码管理/<package>/` | 源码仓库 |
| `<workspace>/4.包管理/downloads/` | deb/dbgsym 下载目录；无 sudo 安装能力时可能为空 |
| `<workspace>/5.崩溃分析/<package>/version_*/analysis_report.md` | 版本级分析报告 |
| `<workspace>/5.崩溃分析/<package>/full_analysis_report.md` | 包级完整报告 |
| `<workspace>/5.崩溃分析/<package>/AI_analysis_report.md` | 面向 AI/人工阅读的汇总报告 |
| `<workspace>/6.总结报告/final_conclusion.md` | 当前包最终总结 |
| `<workspace>/6.总结报告/summary_statistics.json` | 当前包总结统计 |
| `<workspace>/6.总结报告/gerrit-web-report/index.html` | 已提交 Gerrit 修复变更的本地网页报告 |
| `<workspace>/6.总结报告/gerrit-web-report/data.json` | Gerrit 网页报告的结构化数据 |
| `<workspace>/6.总结报告/new_crashes_overview.json` | 多包新增唯一崩溃汇总（供周报/自动化比较） |
| `<workspace>/6.总结报告/new_crashes_overview.md` | 多包新增唯一崩溃人类可读汇总 |

注意：`6.总结报告/` 是当前包的总结目录。多包顺序分析时，该目录里的 `final_conclusion.md` 和 `summary_statistics.json` 会被后续包覆盖；长期保留应优先查看每个包目录下的 `AI_analysis_report.md` 和 `full_analysis_report.md`。

## Gerrit 自动提交规则

当前自动提交规则：只有真实代码修改（源码改动或代码 cherry-pick 产生的提交）才允许自动推送 Gerrit。仅分析文件/说明文档（如 `coredump-analysis-report.md`）不会自动提交。

- `run_analysis_agent.sh`：默认开启自动提交，但仍受上述“仅代码修改可提交”约束；如需纯分析自动化，可通过环境变量关闭：`AUTO_FIX_SUBMIT=false bash run_analysis_agent.sh ...`。
- `coredump-full-analysis/scripts/analyze_crash_complete.sh`：默认关闭自动提交，需显式传 `--auto-fix-submit`。

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

补充手工 Gerrit 变更：

```bash
# 默认会自动读取 coredump-full-analysis/config/manual_gerrit_changes.txt
python3 coredump-full-analysis/scripts/reporting/generate_gerrit_web_report.py \
  --workspace /path/to/coredump-workspace

# 也可以额外指定一个或多个清单文件
python3 coredump-full-analysis/scripts/reporting/generate_gerrit_web_report.py \
  --workspace /path/to/coredump-workspace \
  --manual-change-file /path/to/manual_changes.txt \
  --manual-change-url https://gerrit.uniontech.com/c/dde-dock/+/340629
```

手工清单文件格式：

```text
# 每行一个 Gerrit change 链接，空行和 # 注释会被忽略
https://gerrit.uniontech.com/c/dde-session-shell/+/340460
https://gerrit.uniontech.com/c/dde-launcher/+/340716
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

## 分步执行

分步脚本适合调试流程中的单个阶段：

```bash
# 步骤1: 下载数据，默认全部可下载数据
bash coredump-full-analysis/scripts/step1_download.sh \
    --package dde-session-shell \
    --sys-version 1070-1075

# 步骤2: 筛选数据
bash coredump-full-analysis/scripts/step2_filter.sh \
    --package dde-session-shell \
    --workspace <workspace>

# 步骤3: 源码管理
bash coredump-full-analysis/scripts/step3_source.sh \
    --package dde-session-shell \
    --workspace <workspace>

# 步骤4: 包管理
bash coredump-full-analysis/scripts/step4_packages.sh \
    --package dde-session-shell \
    --workspace <workspace>

# 步骤5: 分析
bash coredump-full-analysis/scripts/step5_analyze.sh \
    --package dde-session-shell \
    --workspace <workspace>
```

## 命令行参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--package <name>` | 包名，必需 | 无 |
| `--start-date <date>` | 开始日期，格式 `YYYY-MM-DD` | 不限制 |
| `--end-date <date>` | 结束日期，格式 `YYYY-MM-DD` | 不限制 |
| `--sys-version <ver>` | 系统版本范围 | `1070-1075` |
| `--arch <arch>` | 架构 | `x86` |
| `--workspace <dir>` | 工作目录 | `~/coredump-workspace-YYYYMMDD-HHMMSS` |

## 故障排查

**数据下载为空**

- 不传日期参数，先确认“全部可下载数据”是否为空。
- 检查 `--sys-version`、`--arch`、包名是否正确。
- 检查 Metabase 配置和网络连通性。

**Gerrit 克隆失败**

- 确认 `accounts.json` 中 Gerrit 用户名正确。
- 检查 SSH key：`ls -la ~/.ssh/id_rsa`。
- 确认用户已自行将 `~/.ssh/id_rsa.pub` 配置到 Gerrit 的设置-“SSH Keys”里面。
- 测试连接：`ssh -p 29418 <user>@gerrit.uniontech.com gerrit version`。

**deb/dbgsym 没有下载或没有安装**

- 先确认 `accounts.json` 中 `shuttle.account` 和 `system.sudo_password` 已正确配置。
- 确认 Shuttle/内部包服务账号和网络可用。
- 再检查目标版本的包是否实际存在。

**总结报告为空或被覆盖**

- 无崩溃版本时，`6.总结报告/` 可能只有空统计或报错提示。
- 多包顺序分析时共享总结会被覆盖，优先查看 `<workspace>/5.崩溃分析/<package>/` 下的包级报告。

## 相关文件

- `../accounts.json`：主账号配置。
- `../accounts.json`：唯一账号配置入口。
- `scripts/analyze_crash_complete.sh`：完整单包流程。
- `scripts/step1_download.sh`：数据下载阶段。
- `scripts/generate_full_report.py`：生成包级完整报告。
- `scripts/generate_ai_report.py`：生成 AI 分析报告。
- `scripts/generate_final_report.py`：生成总结报告。
