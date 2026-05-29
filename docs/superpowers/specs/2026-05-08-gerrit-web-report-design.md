# Gerrit Web Report 设计

## 背景

`coredump-analysis-skills` 当前已经能在崩溃分析流程中自动生成修复提交并提交到 Gerrit，但已提交的修复变更分散在 workspace 的分析产物中，不便于集中查看、筛选和追踪状态。

本需求要把已经提交到 Gerrit 的修复变更聚合成一个本地网页。网页既能作为静态 HTML 归档，也能通过可选本地服务查看。

## 目标

- 从本地 workspace 聚合已提交到 Gerrit 的修复记录。
- 使用 Gerrit 查询补全 change number、状态、链接、项目等信息。
- 生成可直接打开的静态 HTML 报告。
- 同时输出结构化 `data.json`，便于本地服务和后续工具复用。
- 提供可选本地 HTTP 服务查看报告。
- 集成到 Agent 分析流程结束阶段，默认自动生成静态报告。
- Gerrit 查询失败时仍生成报告，并标记未补全记录。

## 非目标

- 不引入 React、Vite、Node.js 或其他前端构建链。
- 第一版不实现复杂后台刷新、用户登录、权限管理或跨 workspace 聚合服务。
- 不改变现有崩溃分析、自动修复、Gerrit 提交流程的核心行为。
- 不因为网页报告生成失败而让主分析流程失败。

## 推荐方案

采用“静态 HTML 为主 + 可选本地服务”的方案。

新增统一数据聚合器，默认生成静态 HTML 和数据 JSON；本地服务读取同一份输出目录。这样既能满足直接打开和归档，也能支持本地交互查看，并避免维护两套数据规则。

## 数据来源

### 主数据源

优先扫描：

```text
<workspace>/5.崩溃分析/gerrit/commit_*.json
```

这是 `submit_to_gerrit.sh` 已经写出的 Gerrit 提交记录目录，语义最直接。

### 自动修复结果

兼容扫描：

```text
<workspace>/5.崩溃分析/<package>/version_*/auto_fix_result.json
<workspace>/5.崩溃分析/<package>/version_*/auto_fix_clusters_result.json
<workspace>/5.崩溃分析/<package>/version_*/deep_auto_fix_result.json
```

这些文件中可能包含：

- `submitted: true`
- `fixes_submitted: true`
- `commit_hash`
- `commit_hashes`
- `auto_fixed`
- `clusters`
- `package`
- `version`
- `target_branch`

### 辅助上下文

扫描：

```text
<workspace>/5.崩溃分析/<package>/version_*/analysis.json
```

用于补齐崩溃簇标题、信号、出现次数、分析报告路径等上下文。

## 统一数据模型

每条记录归一为 `GerritFixRecord`。

本地上下文字段：

- `package`
- `version`
- `workspace_relative_path`
- `source_file`
- `source_files`
- `commit_hash`
- `commit_subject`
- `target_branch`
- `fix_description`
- `files_changed`
- `cluster_title`
- `signal`
- `crash_count`

Gerrit 补全字段：

- `project`
- `change_number`
- `change_id`
- `gerrit_url`
- `status`
- `owner`
- `reviewers`
- `updated`
- `branch`

补全状态字段：

- `gerrit_enriched`
- `enrichment_error`

## 去重和合并规则

同一个 `commit_hash` 只展示一条主记录。

如果同一个 commit 从多个文件被扫描到：

- 优先采用 Gerrit 目录下 `commit_*.json` 的提交信息。
- 自动修复结果补充 package、version、files、cluster。
- `analysis.json` 补充 crash context。
- 合并后的 `source_files` 保留所有来源，便于追踪。

## Gerrit 查询规则

默认使用现有 `GerritClient` 按 commit hash 查询 Gerrit：

- 查询成功：补全 change number、status、URL、project 等信息。
- 查询失败：记录 `gerrit_enriched=false` 和 `enrichment_error`，网页仍生成。
- 支持 `--no-gerrit-enrich` 跳过 Gerrit 查询，只使用本地记录。

## 输出结构

默认输出目录：

```text
<workspace>/6.总结报告/gerrit-web-report/
├── index.html
└── data.json
```

`index.html` 可直接用浏览器打开。为了保证离线打开稳定，HTML 内嵌一份 JSON 数据，同时额外写出 `data.json` 供调试、本地服务和后续工具复用。

## 网页结构

页面使用纯 HTML + CSS + 原生 JavaScript。

页面区域：

1. 标题区
   - 报告名称
   - workspace 路径
   - 生成时间
   - Gerrit 补全成功/失败数量

2. 统计卡片
   - Gerrit 变更总数
   - Open / Merged / Abandoned / Unknown 数量
   - 涉及项目数
   - 涉及包数
   - 涉及版本数
   - 最近更新时间

3. 筛选区
   - 关键字搜索
   - 状态筛选
   - package 筛选
   - project 筛选
   - branch 筛选
   - 只看未补全 Gerrit 信息

4. 主表格
   - 状态
   - package
   - version
   - project
   - Gerrit subject
   - commit hash
   - change number
   - branch
   - crash signal
   - crash count
   - 修改文件数
   - reviewer / owner
   - updated
   - Gerrit 链接

5. 详情展开
   - 修复说明
   - 崩溃簇标题
   - 修改文件列表
   - source files
   - Gerrit 补全错误
   - analysis report 相对路径

## 命令入口

新增脚本：

```text
coredump-full-analysis/scripts/reporting/generate_gerrit_web_report.py
```

推荐用法：

```bash
python3 coredump-full-analysis/scripts/reporting/generate_gerrit_web_report.py \
  --workspace /path/to/coredump-workspace
```

参数：

```text
--workspace <path>          必填，指定 coredump workspace
--output-dir <path>         可选，默认 <workspace>/6.总结报告/gerrit-web-report
--no-gerrit-enrich          可选，只使用本地记录，不查询 Gerrit
--serve                     可选，生成后启动本地 HTTP 服务
--host 127.0.0.1            可选，本地服务监听地址
--port 8765                 可选，本地服务端口
--open                      可选，启动服务后尝试打开浏览器
```

本地服务只负责托管 `index.html` 和 `data.json`。第一版不实现复杂后台状态刷新。

## Agent 集成

在 `run_analysis_agent.sh` 结束阶段自动调用报告生成脚本。

建议行为：

- 如果 workspace 存在，则尝试生成 Gerrit Web Report。
- 生成失败不影响主分析流程退出码。
- 控制台输出报告路径。
- 如果没有任何 Gerrit 提交记录，也生成空报告。

新增参数：

```text
--no-gerrit-web-report      禁用自动生成 Gerrit 网页报告
--serve-gerrit-web-report   分析完成后启动本地服务查看报告
```

默认行为：

- 自动生成静态报告。
- 不自动启动服务。
- 不自动打开浏览器。

## 异常处理

### workspace 不存在

直接失败并输出明确错误。

### 没有 Gerrit 提交记录

生成空报告，页面显示“未发现已提交 Gerrit 的修复变更”。

### JSON 文件损坏或字段缺失

跳过损坏文件，在 `data.json` 中记录 warning，页面顶部显示 warning 数量。

### Gerrit 查询失败

报告仍生成，对应记录标记为 `Unknown` 或 `未补全`，并保留错误原因。

### 服务端口占用

`--serve` 时如果默认端口占用，提示用户使用 `--port` 指定其他端口，不自动随机端口。

### 安全边界

本地服务默认绑定 `127.0.0.1`。只有用户显式传 `--host 0.0.0.0` 时才对外监听。

## 测试计划

### 临时 workspace 数据

构造最小 workspace：

```text
tmp-workspace/
├── 5.崩溃分析/
│   ├── gerrit/
│   │   └── commit_abc123.json
│   └── dde-dock/
│       └── version_1_2_3/
│           ├── analysis.json
│           └── auto_fix_clusters_result.json
└── 6.总结报告/
```

验证：

- 能识别 `commit_*.json`。
- 能识别 `submitted: true + commit_hashes`。
- 能合并同一 commit 的多个来源。
- Gerrit 查询失败时仍输出 HTML。
- 损坏 JSON 被记录为 warning。
- 空 workspace 输出空报告。

### CLI 验证

```bash
python3 coredump-full-analysis/scripts/reporting/generate_gerrit_web_report.py \
  --workspace /tmp/tmp-workspace \
  --no-gerrit-enrich
```

检查：

- `index.html` 存在。
- `data.json` 存在。
- `data.json` 中记录数量正确。
- HTML 中包含统计卡片、筛选区、主表格。

### 本地服务验证

```bash
python3 coredump-full-analysis/scripts/reporting/generate_gerrit_web_report.py \
  --workspace /tmp/tmp-workspace \
  --no-gerrit-enrich \
  --serve \
  --port 8765
```

检查：

- 浏览器能打开。
- 页面表格能展示。
- 搜索和状态筛选可用。
- 展开详情可用。

### Agent 集成验证

使用不联网或不提交 Gerrit 的 dry workspace 测试，确认：

- Agent 结束时会尝试生成报告。
- 没有提交记录时生成空报告。
- 报告生成失败不会让主流程失败。
- `--no-gerrit-web-report` 能禁用自动生成。
