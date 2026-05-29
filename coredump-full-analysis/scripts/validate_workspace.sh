#!/bin/bash
#=============================================================================
# Workspace 验收脚本
# 刷新汇总 -> 校验闭环 -> 输出摘要
#=============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SUMMARY_DIR_NAME="6.总结报告"

WORKSPACE=""
PACKAGES=""
DATE_RANGE_LABEL=""

show_help() {
    cat << EOF
用法:
  $0 --workspace <dir> [--packages <pkg1,pkg2>] [--date-range-label <text>]

说明:
  1. 重新生成 workspace 汇总
  2. 校验 retry-closure 产物
  3. 打印 retry_summary.md 前部内容
EOF
}

while [[ $# -gt 0 ]]; do
    case $1 in
        --workspace)
            WORKSPACE="$2"
            shift 2
            ;;
        --packages)
            PACKAGES="$2"
            shift 2
            ;;
        --date-range-label)
            DATE_RANGE_LABEL="$2"
            shift 2
            ;;
        --help|-h)
            show_help
            exit 0
            ;;
        *)
            echo "未知参数: $1" >&2
            show_help >&2
            exit 1
            ;;
    esac
done

if [[ -z "$WORKSPACE" ]]; then
    echo "错误: 必须指定 --workspace" >&2
    exit 1
fi

SUMMARY_DIR="$WORKSPACE/$SUMMARY_DIR_NAME"
REPORT_FILE="$SUMMARY_DIR/acceptance_report.txt"
STATUS_FILE="$SUMMARY_DIR/acceptance_status.json"
RUN_CONTEXT_FILE="$WORKSPACE/$SUMMARY_DIR_NAME/run_context.json"
if [[ -f "$RUN_CONTEXT_FILE" ]]; then
    if [[ -z "$PACKAGES" ]]; then
        PACKAGES=$(python3 - "$RUN_CONTEXT_FILE" <<'PY'
import json, sys
with open(sys.argv[1], encoding="utf-8") as f:
    data = json.load(f)
print(data.get("packages", ""))
PY
)
    fi
    if [[ -z "$DATE_RANGE_LABEL" ]]; then
        DATE_RANGE_LABEL=$(python3 - "$RUN_CONTEXT_FILE" <<'PY'
import json, sys
with open(sys.argv[1], encoding="utf-8") as f:
    data = json.load(f)
print(data.get("date_range_label", ""))
PY
)
    fi
fi

mkdir -p "$SUMMARY_DIR"

echo "== 刷新汇总 =="
python3 "$SCRIPT_DIR/reporting/generate_workspace_summary.py" \
    --workspace "$WORKSPACE" \
    --packages "$PACKAGES" \
    --date-range-label "$DATE_RANGE_LABEL"

echo
echo "== 闭环校验 =="
VALIDATION_OUTPUT=$(python3 "$SCRIPT_DIR/validation/validate_workspace_retry_closure.py" --workspace "$WORKSPACE" 2>&1)
VALIDATION_EXIT=$?
printf '%s\n' "$VALIDATION_OUTPUT"

RETRY_SUMMARY="$SUMMARY_DIR/retry_summary.md"
if [[ -f "$RETRY_SUMMARY" ]]; then
    echo
    echo "== 重跑摘要预览 =="
    SUMMARY_PREVIEW=$(sed -n '1,80p' "$RETRY_SUMMARY")
    printf '%s\n' "$SUMMARY_PREVIEW"
else
    SUMMARY_PREVIEW=""
fi

VALIDATION_STATUS="ok"
if [[ $VALIDATION_EXIT -ne 0 ]]; then
    VALIDATION_STATUS="failed"
fi

{
    echo "Workspace Acceptance Report"
    echo "generated_at: $(date '+%Y-%m-%d %H:%M:%S')"
    echo "workspace: $WORKSPACE"
    echo "packages: $PACKAGES"
    echo "date_range_label: $DATE_RANGE_LABEL"
    echo "validation_status: $VALIDATION_STATUS"
    echo
    echo "== Validation Output =="
    printf '%s\n' "$VALIDATION_OUTPUT"
    if [[ -n "$SUMMARY_PREVIEW" ]]; then
        echo
        echo "== Retry Summary Preview =="
        printf '%s\n' "$SUMMARY_PREVIEW"
    fi
} > "$REPORT_FILE"

python3 - "$STATUS_FILE" "$WORKSPACE" "$PACKAGES" "$DATE_RANGE_LABEL" "$VALIDATION_STATUS" <<'PY'
import json
import sys
from datetime import datetime

path, workspace, packages, date_range_label, validation_status = sys.argv[1:6]
with open(path, "w", encoding="utf-8") as f:
    json.dump({
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "workspace": workspace,
        "packages": packages,
        "date_range_label": date_range_label,
        "validation_status": validation_status,
    }, f, indent=2, ensure_ascii=False)
PY

echo
echo "验收报告: $REPORT_FILE"
echo "验收状态: $STATUS_FILE"
echo "验收完成"

exit "$VALIDATION_EXIT"
