---
name: coredump-data-download
description: 从Metabase下载Deepin/UOS崩溃数据。支持单个包下载和批量下载，可按系统版本、日期、包版本过滤。用于：(1) 下载指定包的崩溃数据 (2) 批量下载多个包的崩溃数据 (3) 按时间范围或系统版本过滤数据。触发词：下载崩溃数据、Metabase下载、崩溃数据下载、coredump下载。
---

# Coredump 数据下载

从 Metabase 数据仓库下载崩溃数据。

约定：以下命令示例中的 `$SKILLS_DIR` 表示当前 skill 的实际加载目录。

## ⚠️ 每次分析前必须检查账号配置

本 Skill 依赖 `accounts.json` 中的 Metabase 账号配置。**在执行分析前**，请确认配置有效：

```bash
# 检查账号配置文件
sed -n '1,160p' $SKILLS_DIR/accounts.json
```

## 工作目录

工作目录由 `analyze_crash_complete.sh` 主流程自动创建（带时间戳），无需手动指定。

手动执行时设置环境变量：

```bash
export COREDUMP_WORKSPACE="$HOME/coredump-workspace-$(date +%Y%m%d-%H%M%S)"
mkdir -p $COREDUMP_WORKSPACE/1.数据下载
cd $COREDUMP_WORKSPACE/1.数据下载
```

## 脚本位置

```bash
$SKILLS_DIR/coredump-data-download/scripts/download_metabase_csv.sh
```

## 基本用法

### 单个包下载

```bash
./download_metabase_csv.sh [options] <package> <arch> [data_type]
```

**参数说明**：
- `package`: 包名（如 dde-dock, dde-control-center）
- `arch`: 架构（x86, x86_64, arm64, loongarch64）
- `data_type`: 数据类型（默认 crash）

**选项**：
- `--sys-version N[-M]`: 系统版本过滤（如 1070 或 1070-1075）
- `--start-date YYYY-MM-DD`: 开始日期
- `--end-date YYYY-MM-DD`: 结束日期
- `--version VERSION`: 包版本精确匹配
- `--output-dir DIR`: 输出目录（默认自动创建）
- `--file-date LABEL`: 文件日期标签

### 批量下载

```bash
./download_metabase_csv.sh --batch batch_targets.txt [options]
```

**批量文件格式**：
```
package,arch,data_type,start_date,end_date,version
dde-dock,x86,crash,2025-09-01,2025-09-30,
dde-control-center,x86_64,crash,,,
# 注释行会被跳过
```

## 使用示例

```bash
# 示例1: 下载单个包，系统版本1070-1075
./download_metabase_csv.sh --sys-version 1070-1075 dde-dock x86 crash

# 示例2: 按时间范围过滤
./download_metabase_csv.sh --start-date 2025-09-01 --end-date 2025-09-30 \
    --sys-version 1070-1075 dde-dock x86 crash

# 示例3: 按包版本过滤
./download_metabase_csv.sh --version 5.7.41.11 dde-control-center x86_64 crash

# 示例4: 批量下载
./download_metabase_csv.sh --sys-version 1070-1075 --batch batch_targets.txt
```

## 输出文件

下载的CSV文件保存在：
```
download_<timestamp>/<package>_<ARCH>_<data_type>_<timestamp>.csv
```

**示例**：
```
download_20260407-1600/dde-dock_X86_crash_20260407-1600.csv
```

## 环境配置

运行时统一从仓库根目录 `accounts.json` 读取 Metabase 账号：

```bash
export METABASE_BASE_URL="https://metabase.cicd.getdeepin.org"
export METABASE_USERNAME="app@deepin.org"
export METABASE_PASSWORD="deepin123"
export METABASE_DATABASE_ID="10"
```

## CSV字段说明

| 字段 | 说明 |
|------|------|
| ID | 崩溃记录ID |
| Dt | 崩溃日期 |
| Exe | 可执行文件名 |
| Package | 包名 |
| Version | 包版本 |
| Sig | 崩溃信号 |
| StackInfo | 堆栈信息 |
| Sys V Number | 系统版本号 |
| Baseline | 基线版本 |

## 常见问题

**Q: 下载失败，提示认证错误**

检查 `accounts.json` 中 Metabase 账号配置是否正确有效。

**Q: 数据为空**

检查过滤条件是否过于严格，尝试放宽时间范围或系统版本范围。

**Q: 批量下载中断**

查看错误日志，修复批次文件中的错误行后重新运行。

## 示例输出

**控制台输出示例**：
```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
步骤1: 数据下载
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📦 正在下载: dde-dock
📅 日期范围: 2025-09-01 ~ 2025-09-30
🏗️ 系统版本: 1070-1075
📐 架构: x86

正在从 Metabase 下载数据...
正在发送请求到: https://metabase.cicd.getdeepin.org/api/dataset/10
请求参数:
  database_id=10
  table_id=196
  filters:
    - Package = 'dde-dock'
    - Sys V Number between 1070 and 1075
    - Dt between 2025-09-01 and 2025-09-30

下载完成，正在保存到文件...
文件已保存: /path/to/1.数据下载/download_20260407-1600/dde-dock_X86_crash_20260407-1600.csv
✅ 数据下载完成: 5501 行
```
