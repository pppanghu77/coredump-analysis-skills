---
name: coredump-data-filter
description: 崩溃数据去重。将同一崩溃的多条记录合并为一条，输出标准CSV格式。基于堆栈签名识别重复崩溃。触发词：去重崩溃数据、崩溃数据过滤。
---

# Coredump 数据去重

**核心功能**：将同一崩溃的多条记录合并为一条，输出标准CSV格式文件。

约定：以下命令示例中的 `$SKILLS_DIR` 表示当前 skill 的实际加载目录。

## ⚠️ 每次分析前必须检查账号配置

本 Skill 依赖 `accounts.json` 中的 Metabase 账号配置（如用于数据校验）。**在执行分析前**，请确认配置有效：

```bash
sed -n '1,160p' $SKILLS_DIR/accounts.json
```

## 工作目录

工作目录由主流程自动创建，无需手动指定。

手动执行时设置环境变量：

```bash
export COREDUMP_WORKSPACE="$HOME/coredump-workspace-$(date +%Y%m%d-%H%M%S)"
mkdir -p $COREDUMP_WORKSPACE/2.数据筛选
cd $COREDUMP_WORKSPACE/2.数据筛选
```

## 脚本位置

```bash
$SKILLS_DIR/coredump-data-filter/scripts/filter_crash_data.py
```

## 使用方法

```bash
python3 filter_crash_data.py <package_name>
```

**示例**：
```bash
python3 filter_crash_data.py dde-control-center
python3 filter_crash_data.py dde-dock
```

## 去重规则

基于以下三维组合判断是否为同一崩溃：

| 维度 | 字段 | 说明 |
|------|------|------|
| Exe | 可执行文件路径 | 唯一标识程序 |
| Sys V Number | 系统版本号 | 同一系统环境 |
| Stack Signature | 堆栈签名 | 前10帧的库+函数组合 |

**堆栈签名示例**：
```
libQt5Core.so.5:QMetaObject::activate|dde-dock:main|libc.so.6:__libc_start_main
```

## 输出文件

### 去重后的CSV文件

**路径**：`filtered_<package>_crash_data.csv`

**CSV字段说明**：

| 字段名 | 说明 | 示例 |
|--------|------|------|
| Version | 包版本 | 5.9.6-1 |
| Package | 包名 | dde-control-center |
| Count | 重复次数 | 45 |
| Exe | 可执行文件路径 | /usr/bin/dde-control-center |
| Sig | 信号类型 | SIGSEGV |
| StackInfo | 完整堆栈信息 | Stack trace of thread... |
| StackSignature | 堆栈签名 | libQt5Core.so.5:xxx\|dde-dock:yyy |
| App_Layer_Library | 应用层库 | libdcc-update-plugin.so |
| App_Layer_Symbol | 应用层符号 | UpdateWorker::run |
| First_Seen | 首次出现时间 | 2026-03-08T10:00:00 |
| Sys_V_Number | 系统版本号 | 1071 |

### 统计报告JSON

**路径**：`<package>_crash_statistics.json`

```json
{
  "summary": {
    "total_records": 5501,
    "unique_crashes": 120,
    "duplicate_count": 5381
  },
  "by_signal": {
    "SIGSEGV": 800,
    "SIGABRT": 150
  },
  "top_crashes": [
    {
      "rank": 1,
      "count": 45,
      "signal": "SIGSEGV",
      "version": "5.9.6-1",
      "app_layer_symbol": "UpdateWorker::run"
    }
  ]
}
```

## CSV格式保证

- 使用标准RFC 4180 CSV格式
- 字段值中的逗号会用双引号包裹
- 换行符会正确处理
- 文件编码：UTF-8

## 数据流程

```
原始CSV (5501条)
    ↓
[Exe + SysV + StackSignature] 三维去重
    ↓
去重后CSV (~120条)
    ↓
统计报告JSON
```

## 注意事项

- 自动查找最新的下载文件（download_*/ 目录）
- 去重后保留首次出现的记录
- Count字段记录原始重复次数
- 系统库（libc, libpthread等）不计入应用层统计

## 示例输出

**输入CSV**（原始数据，5501条）：
```csv
ID,Dt,Version,Sig,Exe,StackInfo
abc123,2026-03-08,5.9.6-1,SIGSEGV,/usr/bin/dde-control-center,"Stack trace..."
def456,2026-03-08,5.9.6-1,SIGSEGV,/usr/bin/dde-control-center,"Stack trace..."
（共10条相同堆栈）
```

**输出CSV**（去重后，~120条）：
```csv
Version,Package,Count,Exe,Sig,StackInfo,StackSignature,App_Layer_Library,App_Layer_Symbol,First_Seen,Sys_V_Number
5.9.6-1,dde-control-center,10,/usr/bin/dde-control-center,SIGSEGV,"Stack trace...",libdcc-update-plugin:UpdateWorker|...,libdcc-update-plugin.so,UpdateWorker::run,2026-03-08,1071
```

**统计报告** (`<package>_crash_statistics.json`)：
```json
{
  "summary": {
    "total_records": 5501,
    "unique_crashes": 120,
    "duplicate_count": 5381
  },
  "by_signal": {
    "SIGSEGV": 800,
    "SIGABRT": 150
  },
  "top_crashes": [
    {
      "rank": 1,
      "count": 45,
      "signal": "SIGSEGV",
      "version": "5.9.6-1",
      "app_layer_symbol": "UpdateWorker::run"
    }
  ]
}
```

**控制台输出示例**：
```
读取崩溃数据: /path/to/download_20260407-1600/dde-control-center_X86_crash_20260407-1600.csv
共 5501 条崩溃记录
正在基于堆栈签名去重...
去重完成: 5501 条 -> 120 条（唯一崩溃）
正在生成统计报告...
✅ 去重完成！
   总记录: 5501
   唯一崩溃: 120
   去重率: 97.8%

各信号类型统计:
  SIGSEGV: 800 (66.7%)
  SIGABRT: 150 (12.5%)
  SIGBUS:  50 (4.2%)

Top 5 崩溃:
  1. [SIGSEGV] UpdateWorker::run    x45  (5.9.6-1)
  2. [SIGSEGV] QWidget::show        x32  (5.9.6-1)
  3. [SIGABRT] QCoreApplication...  x28  (5.9.5-1)
  4. [SIGSEGV] EventDispatcher...  x21  (5.9.6-1)
  5. [SIGBUS]  QWindow::setFlag...  x15  (5.9.4-1)

输出文件:
  /path/to/2.数据筛选/filtered_dde-control-center_crash_data.csv
  /path/to/2.数据筛选/dde-control-center_crash_statistics.json
```
