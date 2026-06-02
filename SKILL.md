---
name: coredump-analysis-skills
description: DDE/UOS 崩溃数据分析工具集，提供从数据下载、筛选去重、源码管理、包管理到崩溃分析的完整流程。
---

# coredump-analysis-skills

DDE/UOS 崩溃数据分析工具集，提供从数据下载、筛选去重、源码管理、包管理到崩溃分析的完整流程。

约定：以下命令示例中的 `$SKILLS_DIR` 表示当前 skill 的实际加载目录。

## ⚠️ 每次分析前必须检查账号配置

**`accounts.json` 是唯一的账号配置入口**，所有需要人工配置的数据都集中在这里。

**每次崩溃分析启动时，系统会自动检查 `accounts.json`**：
- ✅ 必需账号和密码齐全 → 正常执行分析
- ❌ `metabase` / `gerrit` / `shuttle` / `system.sudo_password` 任一缺失或仍是占位符 → 立即中止并提示配置

**accounts.json 文件路径**：
```bash
$SKILLS_DIR/accounts.json
```

**如需更新账号**：
```bash
# 直接编辑账号配置文件
vi "$SKILLS_DIR/accounts.json"
```

**配置项说明**：
| 服务 | 字段 | 说明 |
|------|------|------|
| **Shuttle** | `shuttle.account` | 下载 deb/dbgsym 包，必填 |
| **Gerrit** | `gerrit.account` | 克隆源码仓库，必填；用户需自行将 `~/.ssh/id_rsa.pub` 配置到 Gerrit 的设置-“SSH Keys”里面 |
| **Metabase** | `metabase.account` | 下载崩溃数据，必填 |
| **System** | `system.sudo_password` | 安装调试符号包时需要，必填 |
| **Paths** | `paths.workspace` | 可选的默认工作目录根路径；不填则使用 `$HOME` |

> **提示**：迁移到新机器后、或长时间未使用后，首次分析前务必检查 `accounts.json` 中的账号是否过期或失效。

---

## 目录结构

```
coredump-analysis-skills/
├── accounts.json                          # 账号配置文件（必需，每次分析前检查）
├── run_analysis_agent.sh                   # 一键分析入口脚本
├── package_skills.py                      # 打包技能为 .skill 文件
├── install_skill.py                       # 从 .skill 文件安装技能
├── coredump-data-download/       # 数据下载
├── coredump-data-filter/         # 数据筛选去重
├── coredump-code-management/     # 源码管理
├── coredump-package-management/  # 包管理
├── coredump-crash-analysis/      # 崩溃分析
└── coredump-full-analysis/       # 完整流程
```

补充说明：`coredump-full-analysis/config/` 目录中仅保留运行时仍需要的静态配置文件；账号信息统一只保存在仓库根目录 `accounts.json`。

## Skills 列表

| Skill | 功能 | 触发词示例 |
|-------|------|-----------|
| [coredump-data-download](./coredump-data-download) | 从 Metabase 下载崩溃数据 | 下载崩溃数据、Metabase下载 |
| [coredump-data-filter](./coredump-data-filter) | 崩溃数据去重和统计 | 去重崩溃数据、崩溃数据过滤 |
| [coredump-code-management](./coredump-code-management) | 从 Gerrit 拉取源码并切换版本 | 拉取源码、Gerrit克隆 |
| [coredump-package-management](./coredump-package-management) | 下载 deb 包和调试符号包 | 下载deb包、下载调试包 |
| [coredump-crash-analysis](./coredump-crash-analysis) | 崩溃堆栈分析和定位 | 崩溃分析、堆栈分析、GDB调试 |
| [coredump-full-analysis](./coredump-full-analysis) | 一站式完整分析流程 | 完整崩溃分析、自动化崩溃分析 |

## 默认分析项目清单

**`packages.txt`** 当前启用 24 个默认分析项目。

全量分析时，系统自动读取此文件获取项目列表，逐个执行分析。

**指定项目时**，只分析指定项目，忽略此文件：
```bash
# 全量分析（读取 packages.txt）
bash run_analysis_agent.sh

# 指定单个项目（默认分析所有能下载的崩溃）
bash run_analysis_agent.sh --packages dde-dock

# 指定多个项目
bash run_analysis_agent.sh --packages dde-dock,dde-launcher
```

## 工作目录自动创建

**重要变更**：每次分析自动创建带时间戳的工作目录，无需手动指定或预先创建。

```
~/coredump-workspace-YYYYMMDD_HHMMSS/     # Agent 入口
~/coredump-workspace-YYYYMMDD-HHMMSS/     # 完整流程脚本入口
├── 1.数据下载/
├── 2.数据筛选/
├── 3.代码管理/
├── 4.包管理/
├── 5.崩溃分析/
├── 6.修复补丁/
└── 6.总结报告/
```

- **不指定 `--workspace`** → 自动创建带时间戳的 `~/coredump-workspace-*`
- **如配置 `accounts.json.paths.workspace`** → 自动创建到该目录下的 `coredump-workspace-*`
- **指定 `--workspace /path`** → 使用指定目录

## Agent 使用（⭐推荐）

使用崩溃分析 Agent，一键执行完整分析流程（自动创建时间戳工作目录）。当前默认行为是不传日期时下载并分析所有能取到的崩溃数据：

```bash
cd "$SKILLS_DIR"

# 全量分析：读取 packages.txt 中当前启用的默认项目（现为 24 个），分析所有能下载的崩溃
bash run_analysis_agent.sh

# 分析单个包所有能下载的崩溃 (x86)
bash run_analysis_agent.sh --packages dde-session-ui

# 分析指定日期范围内的崩溃
bash run_analysis_agent.sh --packages dde-session-ui --start-date 2026-03-14 --end-date 2026-04-14

# 分析 arm64 架构所有能下载的崩溃
bash run_analysis_agent.sh --packages dde-session-ui --arch arm64

# 后台运行
bash run_analysis_agent.sh --packages dde-session-ui --background

# 查看帮助
bash run_analysis_agent.sh --help
```

**Agent 特点**：
- ⭐ 一键执行完整分析流程（下载→筛选→源码→包→分析→报告）
- 默认不限制日期，分析所有能下载的崩溃数据
- `--start-date` / `--end-date` 仅作为可选过滤条件，可只传其中一个
- 全量多包顺序执行时，单个包失败会记录失败列表并继续分析后续包
- 支持多架构（x86, x86_64, arm64）
- 支持自定义日期范围、系统版本
- 后台运行模式
- 自动从 `accounts.json` 读取账号
- 账号或密码缺失时立即暂停流程，不做降级继续
- deb/dbgsym 版本匹配支持 `-1`、`+build`、`.1-1` 等 Debian 构建后缀

## 唯一自动化入口

当前仓库仅保留一条 unattended / cron 自动化流程：

```bash
bash run_analysis_cron.sh
```

这条入口会：
- 默认基于当前日期计算最近 7 天窗口
- 若最近 7 天无数据，则自动回退到最近 15 天
- 走 `run_analysis_agent.sh` 主链路
- 固定以 `AUTO_FIX_SUBMIT=false` 纯分析模式运行
- 运行完成后自动执行 workspace 验收

如需手工触发多包或单包分析，仍使用：
- `bash run_analysis_agent.sh ...`
- `bash coredump-full-analysis/scripts/analyze_crash_complete.sh ...`

## 自动提交默认行为

| 入口 | 脚本 | 自动提交默认值 | 如何关闭/开启 | 说明 |
|------|------|----------------|---------------|------|
| Agent 多包入口 | `run_analysis_agent.sh` | 默认开启 | 默认开启；可通过环境变量 `AUTO_FIX_SUBMIT=false` 关闭 | 会把 `--auto-fix-submit` 传给下游完整流程；但只有真实代码修改（源码改动或代码 cherry-pick）才允许提交 Gerrit |
| 手动单包完整流程 | `coredump-full-analysis/scripts/analyze_crash_complete.sh` | 默认关闭 | 显式传 `--auto-fix-submit` 才开启 | 适合人工调试和保守执行；即使开启自动提交，也只有真实代码修改才允许推送 Gerrit |

> 说明：这里的“自动提交”仅指真实代码修改生成的 Gerrit 提交；仅分析文件/说明文档（如 `coredump-analysis-report.md`）不会自动提交。

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

## 快速开始

### 方式1: Agent 一键分析（⭐推荐）

```bash
# 1. ⚠️ 每次分析前检查 accounts.json 是否已填完整
sed -n '1,160p' "$SKILLS_DIR/accounts.json"

# 2. 使用 Agent 执行完整分析（默认所有能下载的数据）
bash run_analysis_agent.sh --packages dde-session-shell

# 3. 如需限制日期，再显式传入日期范围
bash run_analysis_agent.sh --packages dde-session-shell --start-date 2026-03-10 --end-date 2026-04-09

# 4. 如需纯分析自动化，不执行自动修复/提交检查
AUTO_FIX_SUBMIT=false bash run_analysis_agent.sh --packages dde-session-shell --start-date 2026-03-10 --end-date 2026-04-09
```

### 方式2: 手动完整流程（跳过 Agent 直接调用脚本）

补充：`analyze_crash_complete.sh` 当前默认值为：
- `--max-crashes 0`（单版本分析全部去重后的 crash）
- `--addr2line-max-frames 300`
- 如命中自动二次深挖，实际深挖帧数至少扩展到 `600`


```bash
# ⚠️ 每次分析前检查 accounts.json
sed -n '1,160p' "$SKILLS_DIR/accounts.json"

# 执行完整分析（自动创建带时间戳的工作目录，默认所有能下载的数据）
bash coredump-full-analysis/scripts/analyze_crash_complete.sh \
    --package dde-session-shell \
    --sys-version 1070-1075

# 指定日期范围时再添加 --start-date / --end-date
bash coredump-full-analysis/scripts/analyze_crash_complete.sh \
    --package dde-session-shell \
    --start-date 2026-03-10 \
    --end-date 2026-04-09 \
    --sys-version 1070-1075
```

### 方式3: 分步执行

按需使用单个 Skill：

```bash
# 步骤1: 下载崩溃数据
cd coredump-data-download/scripts
./download_metabase_csv.sh --sys-version 1070-1075 dde-dock x86 crash

# 步骤2: 去重筛选
cd coredump-data-filter/scripts
python3 filter_crash_data.py dde-dock

# 步骤3: 克隆源码
cd coredump-code-management/scripts
./download_crash_source.sh ../../filtered_dde-dock_crash_data.csv 2

# 步骤4: 下载调试包
cd coredump-package-management/scripts
python3 scan_and_download.py dde-dock 5.7.16.1

# 步骤5: 崩溃分析
cd coredump-crash-analysis/scripts
python3 analyze_crash_final.py --package dde-dock
```

## 工作流程

```
崩溃数据下载 → 数据去重 → 源码拉取 → 包管理 → 崩溃分析 → 报告生成
     ↓            ↓          ↓          ↓          ↓
  Metabase     堆栈签名    Gerrit     Shuttle     GDB/addr2line
```

## 增强分析与自动二次深挖

当前增强分析默认行为：
- `--addr2line-max-frames` 默认值为 `300`
- 自动二次深挖默认会扩展到至少 `600` 帧
- 自动二次深挖触发条件不再仅限于 uncertain，而是以下任一满足即触发：
  - `fixable == 'uncertain'`
  - 存在明确 app-layer signal（如 `app_layer_symbol`、包内关键 symbol/library）
  - 高频崩溃（`count >= 3`）

报告表现：
- 版本摘要中会显示 `自动二次深挖` 和 `深挖取得增益`
- 单个 crash 条目中会显示 `自动二次深挖` 区块
- 深挖无收益时，会记录 `deep_dive_exhausted`、`deep_dive_no_gain` 等降级原因

参考文档：
- `references/enhanced-analysis.md`
- `references/automatic-deep-dive-policy.md`

## 当前默认行为

- **日期范围**：不传 `--start-date` / `--end-date` 时，不再默认最近 7 天或最近 30 天，而是下载接口当前能返回的全部崩溃数据。
- **多包全量**：`bash run_analysis_agent.sh` 会读取 `packages.txt` 中当前启用的默认项目（现为 24 个）逐个分析；某个包失败不会阻断后续包，最终会列出失败包。
- **报告位置**：每个包的独立报告位于 `<workspace>/5.崩溃分析/<package>/`，包括 `AI_analysis_report.md`、`full_analysis_report.md` 和各版本 `version_*/analysis_report.md`。
- **共享总结**：`<workspace>/6.总结报告/final_conclusion.md` 和 `summary_statistics.json` 是当前包的总结文件，多包顺序分析时会被后续包覆盖；以每个包目录下的报告作为主要产物。
- **账号必填**：`accounts.json` 中 `metabase` / `gerrit` / `shuttle` / `system.sudo_password` 任一缺失时，流程会直接中止。
- **源码失败降级**：源码克隆或版本 tag 不可用时，脚本仍基于已下载和筛选的崩溃数据生成分析报告。
- **参数约定**：Agent 入口文档统一使用 `--packages`；`--package` 仅作为兼容别名保留。
- **自动修复提交**：`run_analysis_agent.sh` 当前默认 `AUTO_FIX_SUBMIT=true`；如需纯分析自动化，可通过环境变量关闭：`AUTO_FIX_SUBMIT=false bash run_analysis_agent.sh ...`。

## 技能打包与安装

将技能打包成分发文件，或从 .skill 文件安装技能。

### 打包技能

```bash
# 列出所有可用技能
python3 package_skills.py --list

# 打包完整套装（推荐）
# 包含 6 个 skills + agent + 打包工具
python3 package_skills.py --bundle

# 打包所有技能（各自独立）
python3 package_skills.py --all

# 打包单个技能
python3 package_skills.py coredump-data-filter
```

### 安装技能

```bash
# 查看 .skill 文件内容
python3 install_skill.py coredump-data-filter.skill --list

# 安装 .skill 文件
python3 install_skill.py coredump-data-filter.skill

# 批量安装目录中的所有 .skill 文件
python3 install_skill.py /path/to/skills/ --batch
```

### 分发文件

| 文件 | 大小 | 说明 |
|------|------|------|
| `coredump-analysis-skills-bundle.skill` | ~172 KB | 完整套装（推荐） |
| `coredump-*.skill` | ~5-98 KB | 各技能独立打包 |

**推荐使用完整套装** (`--bundle`)，包含所有 skills 和 agent，可独立完整运行。

### .skill 文件格式

`.skill` 文件是 ZIP 压缩包，包含技能目录结构：
- SKILL.md（必需）
- scripts/（可选）
- references/（可选）
- agent/（完整套装包含）

### 打包规则

以下文件会被自动排除：`__pycache__`、`.git`、`.pyc`、`.log`、`accounts.json`

## 账号配置补充

**⚠️ `accounts.json` 是唯一的账号配置入口**，所有需要人工配置的数据都集中在这里。

首次使用前配置账号：
```bash
vi "$SKILLS_DIR/accounts.json"
```

账号配置文件路径：
```bash
$SKILLS_DIR/accounts.json
```

**关键配置项**：
- `shuttle.account` — Shuttle 下载账号，必填
- `gerrit.account` — Gerrit 代码仓库账号，必填；用户需自行将 `~/.ssh/id_rsa.pub` 配置到 Gerrit 的设置-“SSH Keys”里面
- `metabase.account` — Metabase 崩溃数据账号，必填
- `system.sudo_password` — 本机 sudo 密码，必填

**自动检查**：每次分析启动时自动检查 `accounts.json`。`metabase` / `gerrit` / `shuttle` / `system.sudo_password` 任一缺失或仍是占位符时，流程立即中止。
