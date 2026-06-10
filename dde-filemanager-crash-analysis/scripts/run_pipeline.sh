#!/usr/bin/env bash
set -euo pipefail

# dde-file-manager 崩溃分析流程
# 按周下载原始崩溃数据(DB10) → 合并 → 按版本分类 → 堆栈分析

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

SYS_VERSION=""
START_DATE=""
END_DATE=""
WORKSPACE=""

usage() {
    cat <<EOF
用法: $0 [选项]

dde-file-manager 崩溃数据收集 → 分析流程
按自然周（周一~周日）分割下载，文件名标注数据时间范围。

选项:
  --sys-version N        系统版本号 (如 1075) [必填]
  --start-date YYYY-MM-DD  开始日期 [必填]
  --end-date YYYY-MM-DD    结束日期 [必填]
  --workspace DIR        工作目录 (默认: data/workspace_<timestamp>/)
  -h, --help             显示帮助

示例:
  $0 --sys-version 1075 --start-date 2026-05-25 --end-date 2026-05-31
  $0 --sys-version 1075 --start-date 2026-05-01 --end-date 2026-06-08
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --sys-version)
            SYS_VERSION="${2:-}"; shift 2 ;;
        --start-date)
            START_DATE="${2:-}"; shift 2 ;;
        --end-date)
            END_DATE="${2:-}"; shift 2 ;;
        --workspace)
            WORKSPACE="${2:-}"; shift 2 ;;
        -h|--help)
            usage; exit 0 ;;
        *)
            echo "未知选项: $1"; usage; exit 1 ;;
    esac
done

if [[ -z "$SYS_VERSION" ]]; then
    echo "错误: 必须指定 --sys-version"; usage; exit 1
fi
if [[ -z "$START_DATE" || -z "$END_DATE" ]]; then
    echo "错误: 必须指定 --start-date 和 --end-date"; usage; exit 1
fi

if [[ -z "$WORKSPACE" ]]; then
    WORKSPACE="$SCRIPT_DIR/../data/workspace_${START_DATE//-/}_${END_DATE//-/}"
fi
mkdir -p "$WORKSPACE"

echo "============================================"
echo "dde-file-manager 崩溃分析流程"
echo "============================================"
echo "系统版本: $SYS_VERSION"
echo "日期范围: $START_DATE ~ $END_DATE"
echo "工作目录: $WORKSPACE"
echo ""

# ---- 计算自然周列表 ----
WEEKS=$(python3 -c "
from datetime import datetime, timedelta
start = datetime.strptime('$START_DATE', '%Y-%m-%d')
end = datetime.strptime('$END_DATE', '%Y-%m-%d')
mon = start - timedelta(days=start.weekday())
weeks = []
while mon <= end:
    sun = mon + timedelta(days=6)
    w_start = max(mon, start)
    w_end = min(sun, end)
    weeks.append((w_start.strftime('%Y-%m-%d'), w_end.strftime('%Y-%m-%d')))
    mon += timedelta(days=7)
for ws, we in weeks:
    print(f'{ws} {we}')
")
WEEK_COUNT=$(echo "$WEEKS" | wc -l)
echo "覆盖 $WEEK_COUNT 个自然周:"
echo "$WEEKS" | while read ws we; do echo "  $ws ~ $we"; done
echo ""

# ---- 步骤 1: 按周下载原始数据 ----
echo "============================================"
echo "步骤 1/2: 按周下载原始崩溃数据 (DB10)"
echo "============================================"

DOWNLOAD_DIR="$WORKSPACE/1_download"
mkdir -p "$DOWNLOAD_DIR"
ALL_DOWNLOADS=()

while read -r ws we; do
    [[ -z "$ws" ]] && continue
    echo ""
    echo "--- 下载周: $ws ~ $we ---"
    bash "$SCRIPT_DIR/download_crashes.sh" \
        --sys-version "$SYS_VERSION" \
        --start-date "$ws" \
        --end-date "$we" \
        --output-dir "$DOWNLOAD_DIR"

    csv_path=$(cat "$DOWNLOAD_DIR/.merged_csv_path" 2>/dev/null || true)
    if [[ -n "$csv_path" && -f "$csv_path" ]]; then
        ALL_DOWNLOADS+=("$csv_path")
    fi
done <<< "$WEEKS"

echo ""
echo "下载完成: ${#ALL_DOWNLOADS[@]} 个文件"
for f in "${ALL_DOWNLOADS[@]}"; do echo "  $f"; done

# ---- 合并所有周数据 ----
if [[ ${#ALL_DOWNLOADS[@]} -eq 1 ]]; then
    MERGED_CSV="${ALL_DOWNLOADS[0]}"
    echo ""
    echo "单周数据: $MERGED_CSV ($(wc -l < "$MERGED_CSV") 行)"
else
    MERGED_CSV="$DOWNLOAD_DIR/dde-file-manager_${START_DATE//-/}_${END_DATE//-/}.csv"
    HEADER=""
    > "$MERGED_CSV"

    for f in "${ALL_DOWNLOADS[@]}"; do
        if [[ ! -s "$f" ]]; then continue; fi
        if [[ -z "$HEADER" ]]; then
            cat "$f" > "$MERGED_CSV"
            HEADER="true"
        else
            tail -n +2 "$f" >> "$MERGED_CSV"
        fi
    done

    echo ""
    echo "合并文件: $MERGED_CSV ($(wc -l < "$MERGED_CSV") 行)"
fi

# ---- 步骤 2: 按版本分类 + 堆栈分析 ----
echo ""
echo "============================================"
echo "步骤 2/2: 按版本分类 & 堆栈分析"
echo "============================================"

SPLIT_DIR="$WORKSPACE/2_split_by_version"
mkdir -p "$SPLIT_DIR"

python3 "$SCRIPT_DIR/split_by_version.py" \
    -i "$MERGED_CSV" \
    -o "$SPLIT_DIR"

ANALYSIS_DIR="$WORKSPACE/3_version_analysis_results"
mkdir -p "$ANALYSIS_DIR"

VERSION_FILES=$(find "$SPLIT_DIR" -maxdepth 1 -name "version_*.csv" ! -name "_version_statistics.csv" | sort)
VERSION_COUNT=$(echo "$VERSION_FILES" | grep -c "version_" || true)

if [[ -z "$VERSION_FILES" || "$VERSION_COUNT" -eq 0 ]]; then
    echo "错误: 未找到版本分类文件"
    exit 1
fi

echo ""
echo "找到 $VERSION_COUNT 个版本文件"

i=0
SUCCESS=0
while IFS= read -r vf; do
    [[ -z "$vf" ]] && continue
    i=$((i + 1))
    version_name="$(basename "$vf" .csv | sed 's/^version_//')"
    version_dir="$ANALYSIS_DIR/$version_name"
    mkdir -p "$version_dir"

    output_file="$version_dir/analysis_${version_name}.csv"

    echo "--- [$i/$VERSION_COUNT] $version_name ---"
    if python3 "$SCRIPT_DIR/stack_analyzer.py" \
        -i "$vf" \
        -o "$output_file" \
        -c StackInfo; then
        SUCCESS=$((SUCCESS + 1))
    else
        echo "警告: $version_name 分析失败"
    fi
done <<< "$VERSION_FILES"

echo ""
echo "分析完成: $SUCCESS / $VERSION_COUNT 个版本"

# 生成汇总报告
SUMMARY_FILE="$ANALYSIS_DIR/_summary_report.csv"
echo "Version,Record Count,Analysis Status,Analysis File,Keyword Stats File" > "$SUMMARY_FILE"
for version_dir in "$ANALYSIS_DIR"/*/; do
    vname="$(basename "$version_dir")"
    analysis_file="$version_dir/analysis_${vname}.csv"
    stats_file="$version_dir/analysis_${vname}_keyword_stats.csv"
    if [[ -f "$analysis_file" ]]; then
        status="Success"
    else
        status="Failed"
    fi
    echo "\"$vname\",\"\",\"$status\",\"$analysis_file\",\"$stats_file\"" >> "$SUMMARY_FILE"
done
echo "汇总报告: $SUMMARY_FILE"

echo ""
echo "============================================"
echo "流程完成"
echo "============================================"
echo "工作目录: $WORKSPACE"
echo "  - 原始数据:  $DOWNLOAD_DIR"
echo "  - 版本分类:  $SPLIT_DIR"
echo "  - 分析结果:  $ANALYSIS_DIR"
