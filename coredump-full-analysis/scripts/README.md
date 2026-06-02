# scripts 目录结构说明

本目录包含 coredump 崩溃分析主链路的全部分析脚本、报告工具、校验工具和辅助脚本。

推荐人工入口（白名单）

以下脚本是人直接调用的入口，文档和帮助信息也面向人工使用：

| 脚本 | 用途 |
|------|------|
| `analyze_crash_complete.sh` | 单包完整流程（下载→筛选→源码→包→分析→报告→auto-fix） |
| `step1_download.sh` | 分步入口：数据下载 |
| `step2_filter.sh` | 分步入口：数据筛选 |
| `step3_source.sh` | 分步入口：源码克隆 |
| `step4_packages.sh` | 分步入口：deb/dbgsym 下载与安装 |
| `step5_analyze.sh` | 分步入口：逐版本崩溃分析 |
| `validate_workspace.sh` | workspace 验收：刷新汇总→校验闭环→输出摘要 |

仓库根目录的 `run_analysis_agent.sh` 是多包全量编排引擎，不在本目录内；仓库唯一保留的自动化包装入口是 `run_analysis_cron.sh`。

脚本分类索引

分析核心（INTERNAL — 不建议直接调用）

由入口脚本编排调用，不面向人工直接使用：

| 脚本 | 用途 |
|------|------|
| `analyze_crash_per_version.py` | 逐版本崩溃分析，调用 enhanced_analysis / cluster_crashes |
| `enhanced_analysis.py` | 增强分析模块（addr2line/objdump/git blame/DWARF 降级） |
| `cluster_crashes.py` | 确定性根因聚类（24 条规则） |
| `package_rules.py` | 规则注册与包级模块装配 |
| `rules/` | 包级分析规则（当前仅 dde_launcher） |

auto-fix（INTERNAL — 不建议直接调用）

由 `analyze_crash_complete.sh` 在分析完成后编排调用：

| 脚本 | 用途 |
|------|------|
| `auto_fix_submit.py` | auto-fix 主入口：cluster/spec 两条路径；仅真实代码修改允许提交 Gerrit |
| `auto_fix_types.py` | FixPlan/FixResult/CrashCluster 数据类型 |
| `fixers/` | 包级修复器（dde-dock/launcher/control-center/clipboard/polkit-agent/startdde） |
| `fixers/common.py` | 修复器通用工具（apply_replacements/get_fix_specs） |
| `create_patch.sh` | 为可修复崩溃生成补丁文件 |

报告/汇总（INTERNAL TOOLING）

生成分析报告与 workspace 级汇总产物：

| 脚本 | 用途 |
|------|------|
| `reporting/generate_workspace_summary.py` | workspace 汇总：run_manifest/retry_summary/root_cause_clusters/new_crashes_overview |
| `reporting/generate_gerrit_web_report.py` | Gerrit web HTML 报告 |
| `reporting/generate_version_list.py` | 从 crash_statistics.json 生成 version_list.txt |
| `reporting/generate_full_report.py` | 生成 full_analysis_report.md |
| `reporting/generate_final_report.py` | 汇总所有版本分析结果，生成最终结论报告 |
| `reporting/generate_ai_report.py` | 生成 AI_analysis_report.md |
| `reporting/generate_issue_doc.py` | 为不可修复崩溃生成详细问题文档 |

校验/验收（VALIDATION TOOLING）

分析后 / 重跑后的闭环校验工具：

| 脚本 | 用途 |
|------|------|
| `validation/verify_retry_targets.py` | 校验重跑目标是否仍留在 retry 列表中 |
| `validation/validate_workspace_retry_closure.py` | 校验 workspace retry-closure 产物完整性 |
| `validation/run_retry_step.sh` | 失败步骤重跑执行器，结果反写 version_status.tsv |

支撑脚本（SUPPORT — 被入口脚本 source 或调用）

| 脚本 | 用途 |
|------|------|
| `load_accounts.sh` | 统一从 accounts.json 加载账号配置 |
| `install_package.sh` | 安装指定版本的 deb 和 dbgsym 包 |
| `download_all_version_packages.sh` | 批量下载所有版本的 deb 和 dbgsym |
| `sync_version.sh` | 同时切换代码和包到指定版本 |

legacy / experimental（已弃用）

| 脚本 / 目录 | 用途 |
|-------------|------|
| `legacy/` | 已弃用脚本的历史实现 |

参见 `legacy/README.md` 了解完整的 legacy 策略。

快速判断规则

- 脚本文件头标注 `INTERNAL` 或 `INTERNAL TOOLING` → 不建议直接调用
- 脚本文件头标注 `VALIDATION TOOLING` → 仅用于分析后校验
- 脚本文件头标注 `SUPPORT` → 被其他脚本 source 或编排调用
- 脚本文件头标注 `DEPRECATED` 或 `LEGACY` → 已弃用，迁移到 `legacy/`
- 没有标注且在上方“推荐人工入口”表中的 → 主入口
