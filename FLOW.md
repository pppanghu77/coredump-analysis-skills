# 全量崩溃分析当前流程图

本文描述 `coredump-analysis-skills` 当前主链路，而不是历史专项脚本。

约定：
- 默认项目清单来自仓库根目录 `packages.txt`
- 当前 `packages.txt` 启用了 24 个默认项目，全量分析默认按这 24 个项目执行
- 当前主入口是 `run_analysis_agent.sh` 和 `coredump-full-analysis/scripts/analyze_crash_complete.sh`

## 一、总体架构

```mermaid
graph TD
A([开始]) --> B[检查 accounts.json]
B --> C[读取 packages.txt 或命令行 --packages]
C --> D[创建/复用 workspace]
D --> E[逐包执行完整流程]
E --> F[步骤1 下载崩溃数据]
F --> G[步骤2 去重与统计]
G --> H[步骤3 源码拉取/版本切换]
H --> I[步骤4 deb/dbgsym 下载与安装]
I --> J[步骤5 逐版本崩溃分析]
J --> K[增强分析 / 自动二次深挖]
K --> L[自动修复提交 / 分析报告 fallback]
L --> M[生成包级报告]
M --> N{还有下一个包?}
N -->|是| E
N -->|否| O[生成 workspace 汇总]
O --> P[生成 Gerrit Web Report]
P --> Q([完成])
```

## 二、单包主链路

```mermaid
graph TD
A([单包开始]) --> B[step1_download.sh]
B --> C[下载目录 CSV]
C --> D[step2_filter.sh]
D --> E[filtered crash CSV]
D --> F[crash statistics JSON]
E --> G[step3_source.sh]
G --> H[源码 checkout]
H --> I[step4_packages.sh]
I --> J[deb 和 dbgsym 下载]
J --> K[step5_analyze.sh 或 analyze_crash_per_version.py]
K --> L[version analysis.json]
K --> M[version analysis_report.md]
M --> N[full_analysis_report.md]
N --> O([单包完成])
```

## 三、增强分析与自动二次深挖

```mermaid
graph TD
A[基础堆栈分析] --> B[enhanced_analysis.py]
B --> C[addr2line / source context / git blame / objdump]
C --> D{是否触发自动二次深挖?}
D -->|uncertain| E[深挖]
D -->|app-layer signal| E
D -->|count >= 3| E
D -->|否| F[保留首轮结果]
E --> G[提高 frame budget]
G --> H[优先重新解析关键帧与应用层帧]
H --> I[生成 deep_dive 结果与 degradation reasons]
I --> J[写入 analysis.json / analysis_report.md]
F --> J
```

当前默认规则：
- `--max-crashes 0`：单版本默认分析全部去重后的 crash
- `--addr2line-max-frames 300`
- 自动二次深挖至少扩展到 `600` 帧
- 深挖触发条件：`fixable == 'uncertain'` / app-layer signal / `count >= 3`

## 四、自动修复提交规则

```mermaid
graph TD
A[版本分析结果] --> B{有 cluster/spec fixer?}
B -->|有| C[尝试生成代码修复]
B -->|无| D[进入 spec path / manual_required]
C --> E{产生真实源码变更?}
E -->|是| F[提交 Gerrit]
E -->|否| G[仅保留本地分析结果]
D --> H{存在可自动应用的代码修复?}
H -->|是| F
H -->|否| G
F --> J[auto_fix_result.json / auto_fix_clusters_result.json]
G --> J
```

说明：
- 只有真实代码修改（源码改动或代码 cherry-pick）才允许提交 Gerrit
- 仅分析文件 / 说明文档不会自动提交 Gerrit，只保留在本地结果中
- Gerrit Web Report 是辅助汇总，不是自动提交是否成功的唯一真相来源
- 自动修复链路的详细覆盖情况见 `references/fixer-architecture.md`

## 五、workspace 产物

```text
<workspace>/
  1.数据下载/
  2.数据筛选/
  3.代码管理/
  4.包管理/downloads/
  5.崩溃分析/<package>/
    version_*/analysis.json
    version_*/analysis_report.md
    full_analysis_report.md
    AI_analysis_report.md
  6.修复补丁/
  6.总结报告/
    final_conclusion.md
    summary_statistics.json
    package_status.tsv
    version_status.tsv
    gerrit-web-report/index.html
    logs/analysis_<pkg>.log
```

## 六、当前推荐入口

1. 唯一自动化入口：
```bash
bash run_analysis_cron.sh
```

2. 多包/全量手工入口：
```bash
bash run_analysis_agent.sh --progress 180
```

3. 单包完整流程：
```bash
bash coredump-full-analysis/scripts/analyze_crash_complete.sh --package <package>
```

4. 仅在排查或恢复时使用分步脚本：
- `step1_download.sh`
- `step2_filter.sh`
- `step3_source.sh`
- `step4_packages.sh`
- `step5_analyze.sh`

## 七、不要再把这些当作主链路

