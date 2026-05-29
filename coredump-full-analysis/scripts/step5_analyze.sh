#!/bin/bash
# 步骤5: 崩溃分析 - 逐版本分析与汇总报告
# 对应 Skill: coredump-crash-analysis

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

PACKAGE="${PACKAGE:-}"
WORKSPACE="${WORKSPACE:-}"
START_DATE="${START_DATE:-}"
END_DATE="${END_DATE:-}"

if [[ -z "$WORKSPACE" ]]; then
    WORKSPACE="$HOME/coredump-workspace-$(date +%Y%m%d-%H%M%S)"
fi

while [[ $# -gt 0 ]]; do
    case $1 in
        --package) PACKAGE="$2"; shift 2 ;;
        --workspace) WORKSPACE="$2"; shift 2 ;;
        --start-date) START_DATE="$2"; shift 2 ;;
        --end-date) END_DATE="$2"; shift 2 ;;
        *) shift ;;
    esac
done

if [[ -z "$PACKAGE" ]]; then
    echo "错误: 必须指定 --package 参数"
    exit 1
fi

FILTERED_CSV="$WORKSPACE/2.数据筛选/filtered_${PACKAGE}_crash_data.csv"
STATS_FILE="$WORKSPACE/2.数据筛选/${PACKAGE}_crash_statistics.json"
VERSION_LIST_FILE="$WORKSPACE/2.数据筛选/version_list.txt"
ANALYSIS_DIR="$WORKSPACE/5.崩溃分析/$PACKAGE"
SUMMARY_DIR="$WORKSPACE/6.总结报告"

mkdir -p "$ANALYSIS_DIR" "$SUMMARY_DIR"

echo "=========================================="
echo "步骤5: 崩溃分析 - 逐版本分析与汇总报告"
echo "=========================================="
echo "包名: $PACKAGE"
echo "工作目录: $WORKSPACE"
echo ""

if [[ ! -f "$FILTERED_CSV" ]]; then
    echo "错误: 缺少筛选后的崩溃数据: $FILTERED_CSV"
    exit 1
fi

if [[ ! -f "$STATS_FILE" ]]; then
    echo "错误: 缺少统计数据: $STATS_FILE"
    exit 1
fi

echo "生成版本清单..."
python3 "$SCRIPT_DIR/reporting/generate_version_list.py" \
    "$STATS_FILE" \
    "$VERSION_LIST_FILE" \
    --min-crash-count 1

echo ""
echo "开始逐版本分析..."
while IFS='|' read -r version crash_count priority; do
    [[ -z "$version" || "$version" == \#* ]] && continue
    echo "------------------------------------------"
    echo "版本: $version"
    echo "崩溃次数: $crash_count"
    echo "优先级: $priority"
    python3 "$SCRIPT_DIR/analyze_crash_per_version.py" \
        --package "$PACKAGE" \
        --version "$version" \
        --workspace "$WORKSPACE" \
        --max-crashes 0 || {
        echo "⚠️ 版本 $version 分析失败，继续后续版本"
    }
done < "$VERSION_LIST_FILE"

echo ""
echo "生成最终汇总报告..."
FINAL_REPORT_ARGS=(
    --package "$PACKAGE"
    --workspace "$WORKSPACE"
    --output-dir "$SUMMARY_DIR"
)
if [[ -n "$START_DATE" ]]; then
    FINAL_REPORT_ARGS+=(--start-date "$START_DATE")
fi
if [[ -n "$END_DATE" ]]; then
    FINAL_REPORT_ARGS+=(--end-date "$END_DATE")
fi
python3 "$SCRIPT_DIR/reporting/generate_final_report.py" "${FINAL_REPORT_ARGS[@]}"

echo ""
echo "生成 AI 汇总报告..."
python3 "$SCRIPT_DIR/reporting/generate_ai_report.py" \
    --package "$PACKAGE" \
    --workspace "$WORKSPACE"

echo ""
echo "✅ 步骤5完成"
echo "版本分析目录: $ANALYSIS_DIR"
echo "最终总结目录: $SUMMARY_DIR"
