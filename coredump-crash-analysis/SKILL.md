---
name: coredump-crash-analysis
description: 分析崩溃堆栈，定位崩溃原因，提供修复建议。识别SIGSEGV/SIGABRT/SIGBUS等信号类型，定位应用层崩溃函数，判断项目内/外崩溃，生成GDB调试命令和addr2line定位指令。用于：(1) 分析崩溃堆栈 (2) 定位崩溃代码 (3) 判断崩溃类型 (4) 提供修复建议 (5) 生成调试命令。触发词：崩溃分析、堆栈分析、GDB调试、addr2line、崩溃定位。
---

# Coredump 崩溃分析

分析崩溃堆栈，定位问题原因，提供修复建议。

约定：以下命令示例中的 `$SKILLS_DIR` 表示当前 skill 的实际加载目录。

## ⚠️ 每次分析前必须检查账号配置

本 Skill 主要依赖 `accounts.json` 中的 Gerrit 账号（用于关联修复记录）和系统 sudo 密码（用于安装调试符号包）。**在执行分析前**，请确认配置有效：

```bash
sed -n '1,160p' $SKILLS_DIR/accounts.json
```

## 目录结构

```
coredump-crash-analysis/
├── SKILL.md                          # 本文件
├── scripts/
│   └── analyze_crash_final.py         # 崩溃分析脚本
│   └── analyze_blackwidget_crashes.py # dde-blackwidget 专项分析脚本
├── centralized/                      # 通用分析模块
│   ├── __init__.py                   # 包导出
│   ├── models.py                     # 通用数据模型
│   ├── base_config.py                # 通用系统库/插件库配置
│   ├── gerrit_client.py              # 通用Gerrit SSH客户端
│   ├── crash_classifier.py           # 通用崩溃分类器
│   ├── fix_mapper.py                 # 通用崩溃→修复映射器
│   └── report_generator.py            # 通用报告生成器
└── references/
```

## 快速开始

### 完整流程分析（推荐）

```bash
cd $SKILLS_DIR/coredump-full-analysis/scripts
bash analyze_crash_complete.sh --package dde-dock
```

### 单独运行崩溃分析

```bash
cd $SKILLS_DIR/coredump-crash-analysis/scripts
python3 analyze_crash_final.py --package dde-dock --workspace ~/coredump-workspace
```

### 单独运行 dde-blackwidget 专项分析

适用于 `dde-session-ui` 原始崩溃数据，自动收敛 `dde-blackwidget` 相关记录并生成签名、低频、问题清单。
支持输入单个 CSV，也支持输入一个目录并递归合并其中多份 CSV。

```bash
cd $SKILLS_DIR/coredump-crash-analysis/scripts
python3 analyze_blackwidget_crashes.py \
    --csv /path/to/dde-session-ui_X86_crash_xxx.csv \
    --output-dir /tmp/dde-blackwidget-analysis

python3 analyze_blackwidget_crashes.py \
    --csv /path/to/1.数据下载 \
    --output-dir /tmp/dde-blackwidget-analysis
```

输出文件包括：

- `dde-blackwidget_all_records.csv`
- `signature_summary.csv`
- `signature_triage_v2.csv`
- `signature_triage_v3.csv`
- `lowfreq_resolution_v2.csv`
- `actionable_issues.csv`
- `retained_issues.csv`
- `final_issue_summary.md`
- `remaining_issue_review_v3.md`

## 通用模块 (centralized/)

通用崩溃分析模块，可被多个 coredump-* skills 复用。

### 模块说明

| 模块 | 功能 | 使用方式 |
|------|------|---------|
| `models.py` | 数据模型 (CrashRecord, FixMapping等) | `from centralized import CrashRecord` |
| `base_config.py` | 系统库/插件库列表配置 | `from centralized import SYSTEM_LIBRARIES` |
| `gerrit_client.py` | Gerrit SSH 客户端 | `GerritClient(project="dde-dock")` |
| `crash_classifier.py` | 崩溃分类 (app/system/plugin) | `CrashClassifier.for_package("dde-dock")` |
| `fix_mapper.py` | 崩溃→修复映射 | `FixMapper.create_for_dde_dock()` |
| `report_generator.py` | Markdown 报告生成 | `ReportGenerator("dde-dock")` |

## 分析流程

```
读取CSV → 解析堆栈 → 识别信号类型 → 定位关键帧 → 判断崩溃类型 → 关联Gerrit修复 → 生成报告
```

`dde-blackwidget` 专项分析流程：

```
读取 dde-session-ui CSV → 收敛 dde-blackwidget 记录 → 生成签名 → 低频记录归类 → 问题分层 → 剩余问题复判 → 输出问题清单
```

## 依赖说明（⚠️ 重要）

崩溃分析并非孤立运行，需要以下两个 Skill **协同配合**才能完成完整分析：

| 依赖 Skill | 作用 | 说明 |
|------------|------|------|
| **coredump-code-management** | 克隆崩溃版本的源码 | 根据崩溃包版本切换到对应 git tag，确保分析时源码与崩溃环境一致 |
| **coredump-package-management** | 下载安装 deb/dbgsym 包 | 安装崩溃版本的 deb 包（含可执行文件）和 dbgsym 调试符号包（用于 addr2line 定位源码行号）|

**三者配合的逻辑**：

```
1. coredump-crash-analysis 获取崩溃堆栈
          ↓
2. 根据崩溃版本，coredump-code-management 克隆源码并切换到对应 tag
          ↓
3. coredump-package-management 下载并安装对应版本的 deb 和 dbgsym 包
          ↓
4. 使用 addr2line + dbgsym + 源码，定位崩溃的源代码文件和行号
          ↓
5. 生成修复建议
```

**如果需要提交修复**：

在 coredump-crash-analysis 完成崩溃分析并生成修复建议后：

1. 使用 **coredump-code-management** 切换到 `develop/eagle` 分支：
   ```bash
   cd <workspace>/3.代码管理/<package>
   git checkout origin/develop/eagle -b fix/<issue-description>
   ```
2. 应用修复代码
3. 提交到 Gerrit，Commit message 格式如下：
   ```text
   fix/feat/chore: 提交信息说明

   崩溃信息:
   - 崩溃版本: <version>
   - 架构: <arch> (x86/arm64/x86_64/loongarch64)
   - 修复详细堆栈:
   <full_stack_trace>

   本次修复说明:
   <fix_description>

   Log: 基于产品说明本次修复内容
   Influence: 影响哪些功能点
   ```
   **Commit message 示例**：
   ```text
   fix: 修复 QWidget::show() 空指针崩溃

   崩溃信息:
   - 崩溃版本: 5.7.41.11
   - 架构: x86
   - 修复详细堆栈:
   #0  QWidget::show()  at /path/to/widget.cpp:123
   #1  QMetaObject::activate()  at /path/to/qobject.cpp:456
   #2  QTimer::timeout()  at /path/to/qtimer.cpp:789
   #3  g_main_context_iteration()  at glib.cpp:101

   本次修复说明:
   在调用前检查对象指针 if (obj) { obj->show(); }

   Log: 修复 QWidget::show() 空指针崩溃
   Influence: 影响 QWidget::show() 触发的界面展示路径
   ```
4. 推送到 Gerrit：
   ```bash
   git push origin HEAD:refs/heads/develop/eagle
   ```

## 信号类型说明

| 信号 | 含义 | 常见原因 | 修复建议 |
|------|------|----------|----------|
| SIGSEGV | 段错误 | 空指针、野指针、越界访问 | 添加空指针检查、使用智能指针 |
| SIGABRT | 主动终止 | assert失败、内存分配失败 | 检查assert条件、添加错误处理 |
| SIGBUS | 总线错误 | 内存对齐问题 | 检查内存对齐、使用aligned属性 |
| SIGFPE | 浮点异常 | 除零、整数溢出 | 添加除零检查、使用安全运算 |

## 崩溃分类 (CrashClassifier)

```python
from centralized import CrashClassifier

# 根据包名自动适配
classifier = CrashClassifier.for_package("dde-dock")
classifier = CrashClassifier.for_package("dde-session-shell")

# 分类单条记录
result = classifier.classify(crash_record)
# 返回: "app_layer" | "system" | "plugin"

# 批量分类
app_crashes, sys_crashes, plugin_crashes = classifier.classify_batch(records)
```

## 崩溃→修复映射 (FixMapper)

```python
from centralized import FixMapper

# 创建 dde-dock 专用映射器
fix_mapper = FixMapper.create_for_dde_dock()

# 映射崩溃到修复
fixes = fix_mapper.map_crash_to_fixes(crash_record)
for fix in fixes:
    print(fix.commit_hash)      # "3d9fef0"
    print(fix.description)      # "修复多处空指针崩溃问题"
    print(fix.get_gerrit_url()) # "https://gerrit.uniontech.com/c/dde-dock/+/{change_number}"
```

## Gerrit 集成 (GerritClient)

```python
from centralized import GerritClient, GerritConfig

# 创建客户端
gerrit = GerritClient()

# 查询 commit 对应的 change URL
url = gerrit.get_change_url("3d9fef0", project="dde-dock")

# 批量查询
results = gerrit.batch_get_changes(["3d9fef0", "5801d11"], project="dde-dock")
```

## 报告生成 (ReportGenerator)

```python
from centralized import ReportGenerator

report_gen = ReportGenerator("dde-dock")
report = report_gen.generate_report(
    version_analyses=analyses,
    statistics=stats,
    all_fix_mappings=fixes,
    gerrit_client=gerrit
)
```

## GDB 常用命令

```bash
# 加载 coredump
gdb /usr/bin/<exe> -c <coredump_file>

# 查看完整堆栈
(gdb) bt
(gdb) bt full

# 切换栈帧
(gdb) frame 2
(gdb) up
(gdb) down

# 查看变量
(gdb) info locals
(gdb) info args
(gdb) print variable_name
```

## addr2line 使用

```bash
# 基本用法
addr2line -e /usr/lib/debug/.build-id/<aa>/<bbbb...> <address>

# 示例
addr2line -e /usr/lib/debug/.build-id/ab/c123def456.debug 0x000055c65fa3409b
# 输出: /path/to/source.cpp:123
```

## 注意事项

- 确保已安装调试符号包（dbgsym），否则 addr2line 无法定位源码行号
- 项目外崩溃需要等待上游修复
- 修复代码需要切换到正确的版本分支
- 提交时包含完整的崩溃信息和分析
- centralized/ 通用模块可被其他 coredump-* skills 复用
- **每次分析前检查 `accounts.json` 中 sudo 密码是否配置正确**（用于安装 dbgsym 包）

## 示例输出

**控制台输出示例**：
```
================================================================================
[记录 1] 崩溃分析
================================================================================
  ID:       12345678-1234-1234-1234-123456789abc
  时间:     2026-04-07T15:30:00
  包:       dde-control-center
  版本:     5.7.41.11
  信号:     SIGSEGV (段错误 - 非法内存访问)
  系统:     Deepin 1070
  崩溃次数: 45

[崩溃定位]
✓ 已定位到应用层崩溃帧: 帧 #2
  库文件:  dde-control-center
  符号:    QWidget::show()
  地址:    0x000055c65fa3409b

[堆栈跟踪]
--------------------------------------------------------------------------------
► #0 0x000055c65fa3409b QWidget::show()
       库: dde-control-center
    #1 0x00007f1234567890 QMetaObject::activate()
       库: libQt5Core.so.5
    #2 0x00007f1234567abc0 QTimer::timeout()
       库: libQt5Core.so.5
    #3 0x00007f1234560000 g_main_context_iteration()
       库: libglib-2.0.so.0
--------------------------------------------------------------------------------

[修复建议]
  针对 SIGSEGV:
    1. 添加空指针检查: if (obj) { obj->method(); }
    2. 使用智能指针避免野指针
    3. 数组访问前检查边界

================================================================================
分析完成，共处理 120 个唯一崩溃
  应用层崩溃: 85 (可修复)
  系统库崩溃: 28 (需上游修复)
  插件崩溃:   7 (需联系插件维护者)
================================================================================
```

**分析报告文件** (`<workspace>/5.崩溃分析/<package>_crash_analysis_report.md`)：
```markdown
# dde-control-center 崩溃分析报告

## 统计概览
- 分析时间: 2026-04-07 15:30:00
- 崩溃总数: 5501
- 唯一崩溃: 120
- 应用层崩溃: 85
- 系统库崩溃: 28
- 插件崩溃: 7

## Top 5 崩溃

| 排名 | 信号 | 崩溃次数 | 应用层函数 | 版本 | 可修复 |
|------|------|---------|-----------|------|--------|
| 1 | SIGSEGV | 45 | QWidget::show() | 5.7.41.11 | ✅ |
| 2 | SIGSEGV | 32 | UpdateWorker::run() | 5.7.41.11 | ✅ |
| 3 | SIGABRT | 28 | QCoreApplication::quit() | 5.9.5-1 | ✅ |
| 4 | SIGBUS | 15 | QWindow::setFlags() | 5.9.4-1 | ❌ |
| 5 | SIGSEGV | 12 | EventDispatcher::process() | 5.9.6-1 | ✅ |

## 修复建议示例

### 崩溃 #1: QWidget::show() SIGSEGV
- **崩溃次数**: 45
- **版本**: 5.7.41.11
- **堆栈**: QWidget::show() -> QMetaObject::activate() -> QTimer::timeout()
- **根因**: 对象未初始化就调用 show()
- **修复**:
  1. 在调用 show() 前检查对象指针
  2. 使用 std::unique_ptr 管理对象生命周期
  3. 添加防御性编程检查

### 对应 Gerrit 修复
  - Commit: `3d9fef0`
  - URL: https://gerrit.uniontech.com/c/dde-control-center/+ /3d9fef0
  - 状态: 已合并到 develop/eagle
```
