#!/bin/bash
# 统一从 accounts.json 加载账号配置

SCRIPT_DIR_LOAD_ACCOUNTS="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT_LOAD_ACCOUNTS="$(cd "$SCRIPT_DIR_LOAD_ACCOUNTS/../.." && pwd)"
ACCOUNTS_FILE_LOAD_ACCOUNTS="${COREDUMP_ACCOUNTS_FILE:-$PROJECT_ROOT_LOAD_ACCOUNTS/accounts.json}"

accounts_require_jq() {
    if ! command -v jq >/dev/null 2>&1; then
        echo "错误: 缺少 jq，无法读取 accounts.json" >&2
        return 1
    fi
}

accounts_file_path() {
    printf '%s' "$ACCOUNTS_FILE_LOAD_ACCOUNTS"
}

accounts_expand_path() {
    local path="$1"
    if [[ "$path" == "~" ]]; then
        printf '%s' "$HOME"
    elif [[ "$path" == ~/* ]]; then
        printf '%s/%s' "$HOME" "${path#~/}"
    else
        printf '%s' "$path"
    fi
}

accounts_read_field() {
    local field="$1"
    jq -r "$field // \"\"" "$(accounts_file_path)" 2>/dev/null
}

accounts_value_missing() {
    local value="$1"
    if [[ -z "$value" || "$value" == "null" || "$value" == *"在此处输入"* || "$value" == *"请在此输入"* ]]; then
        return 0
    fi
    return 1
}

accounts_require_file() {
    if [[ ! -f "$(accounts_file_path)" ]]; then
        echo "错误: accounts.json 不存在: $(accounts_file_path)" >&2
        return 1
    fi
    accounts_require_jq || return 1
}

load_accounts_env() {
    accounts_require_file || return 1

    export METABASE_BASE_URL="$(accounts_read_field '.metabase.url')"
    export METABASE_USERNAME="$(accounts_read_field '.metabase.account.username')"
    export METABASE_PASSWORD="$(accounts_read_field '.metabase.account.password')"
    export METABASE_DATABASE_ID="$(accounts_read_field '.metabase.database.id')"

    export GERRIT_HOST="$(accounts_read_field '.gerrit.host')"
    export GERRIT_PORT="$(accounts_read_field '.gerrit.port')"
    export GERRIT_USER="$(accounts_read_field '.gerrit.account.username')"
    export GERRIT_PASSWORD="$(accounts_read_field '.gerrit.account.password')"
    export GERRIT_SSH_KEY="$(accounts_read_field '.gerrit.ssh_key')"

    export SHUTTLE_URL="$(accounts_read_field '.shuttle.url')"
    export SHUTTLE_API_URL="$(accounts_read_field '.shuttle.api_url')"
    export SHUTTLE_USERNAME="$(accounts_read_field '.shuttle.account.username')"
    export SHUTTLE_PASSWORD="$(accounts_read_field '.shuttle.account.password')"

    export PACKAGE_SERVER_URL="$(accounts_read_field '.internal_server.url')"
    export PACKAGE_SERVER_TASKS_ENDPOINT="$(accounts_read_field '.internal_server.tasks_endpoint')"

    export SUDO_PASSWORD="$(accounts_read_field '.system.sudo_password // .system.password')"
    export ACCOUNTS_WORKSPACE_ROOT="$(accounts_expand_path "$(accounts_read_field '.paths.workspace')")"
}

require_account_service() {
    local service="$1"
    case "$service" in
        metabase)
            accounts_value_missing "${METABASE_USERNAME:-}" && { echo "错误: accounts.json 缺少 metabase.account.username" >&2; return 1; }
            accounts_value_missing "${METABASE_PASSWORD:-}" && { echo "错误: accounts.json 缺少 metabase.account.password" >&2; return 1; }
            ;;
        gerrit)
            accounts_value_missing "${GERRIT_USER:-}" && { echo "错误: accounts.json 缺少 gerrit.account.username" >&2; return 1; }
            accounts_value_missing "${GERRIT_PASSWORD:-}" && { echo "错误: accounts.json 缺少 gerrit.account.password" >&2; return 1; }
            ;;
        shuttle)
            accounts_value_missing "${SHUTTLE_USERNAME:-}" && { echo "错误: accounts.json 缺少 shuttle.account.username" >&2; return 1; }
            accounts_value_missing "${SHUTTLE_PASSWORD:-}" && { echo "错误: accounts.json 缺少 shuttle.account.password" >&2; return 1; }
            ;;
        system)
            accounts_value_missing "${SUDO_PASSWORD:-}" && { echo "错误: accounts.json 缺少 system.sudo_password 或 system.password" >&2; return 1; }
            ;;
        *)
            echo "错误: 未知账户服务: $service" >&2
            return 1
            ;;
    esac
    return 0
}

load_accounts_or_die() {
    load_accounts_env || exit 1
    local service
    for service in "$@"; do
        require_account_service "$service" || {
            echo "流程已暂停，请先完善 accounts.json: $(accounts_file_path)" >&2
            exit 1
        }
    done
}
