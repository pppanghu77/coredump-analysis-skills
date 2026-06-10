#!/usr/bin/env python3
"""
看板服务器 — 多应用支持，直接读写 CSV
- 数据源: data/<app_name>/*.csv
- API 直接读 CSV 返回 JSON
- CRUD 操作直接写回 CSV
- SSE + 文件监控：CSV 变更后自动推送前端刷新
"""

import csv, json, os, signal, socket, subprocess, threading, time
from collections import defaultdict
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, 'data')
PORT = 8765

# ── 多应用数据路径 ──────────────────────────────────────────────

def list_apps():
    """扫描 data/ 下的子目录，返回应用名列表"""
    apps = []
    if not os.path.isdir(DATA):
        return apps
    for name in sorted(os.listdir(DATA)):
        path = os.path.join(DATA, name)
        if os.path.isdir(path) and os.path.exists(os.path.join(path, 'issue_info.csv')):
            apps.append(name)
    return apps

def app_dir(app):
    return os.path.join(DATA, app)

def issue_csv(app):
    return os.path.join(DATA, app, 'issue_info.csv')

def summary_csv(app):
    return os.path.join(DATA, app, 'report_summary.csv')

# ── CSV 工具函数 ────────────────────────────────────────────────

def read_csv(path):
    with open(path, encoding='utf-8') as f:
        return list(csv.DictReader(f))

def write_csv(path, rows, fieldnames):
    with open(path, 'w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
        w.writeheader()
        w.writerows(rows)

# ── 字段映射 ────────────────────────────────────────────────────

ISSUE_CN_TO_EN = {
    '问题ID': 'issue_id', '问题名称': 'issue_name', '问题领域': 'domain',
    '严重程度': 'severity', '信号类型': 'signal_type', '堆栈指纹': 'stack_fingerprint',
    '完整堆栈': 'full_stack', '根因描述': 'root_cause', '引入版本': 'introduced_version',
    '首现版本': 'first_seen_version', '修复版本': 'fix_version', '当前状态': 'status',
    '修复类型': 'fix_type', '修复效果': 'fix_effectiveness', '修复后占比': 'post_fix_pct',
    '发现日期': 'discovered_at', '开始分析日期': 'analysis_started_at',
    '定位日期': 'root_cause_found_at', '提修日期': 'fix_submitted_at',
    '验证通过日期': 'verified_at', '关闭日期': 'closed_at', '负责人': 'assignee',
    '首现日期': 'first_seen_date',
    '关联Issue': 'related_issue', '关联MR': 'related_mr', '标签': 'tags',
    '影响架构': 'affected_arch', '备注': 'notes',
}

EN_TO_ISSUE_CN = {v: k for k, v in ISSUE_CN_TO_EN.items()}

ISSUE_FIELDNAMES = [
    '问题ID', '问题名称', '问题领域', '严重程度',
    '信号类型', '堆栈指纹', '完整堆栈', '根因描述',
    '引入版本', '首现版本', '修复版本',
    '发现日期', '开始分析日期', '定位日期', '提修日期', '验证通过日期', '关闭日期', '首现日期',
    '修复类型', '修复效果', '修复后占比',
    '当前状态', '负责人', '关联Issue', '关联MR', '标签', '影响架构', '备注', '趋势数据',
]


def row_to_issue(row):
    issue = {}
    for cn, en in ISSUE_CN_TO_EN.items():
        issue[en] = row.get(cn, '').strip()
    return issue

def issue_to_row(issue):
    row = {}
    for cn in ISSUE_FIELDNAMES:
        en = ISSUE_CN_TO_EN.get(cn, '')
        val = issue.get(en, '')
        row[cn] = str(val) if val is not None else ''
    return row

# ── SSE 管理器 ──────────────────────────────────────────────────

class SSEManager:
    def __init__(self):
        self.clients = []
        self.lock = threading.Lock()

    def add_client(self, wfile):
        with self.lock:
            self.clients.append(wfile)

    def remove_client(self, wfile):
        with self.lock:
            self.clients = [w for w in self.clients if w is not wfile]

    def notify_all(self, message='data_updated'):
        with self.lock:
            for wfile in self.clients:
                try:
                    wfile.write(f'data: {message}\n\n'.encode('utf-8'))
                    wfile.flush()
                except Exception:
                    pass

sse_manager = SSEManager()

# ── 文件监控 ────────────────────────────────────────────────────

_file_mtimes = {}
_watch_running = True

def _collect_csv_files():
    """收集所有应用的 CSV 文件路径"""
    files = []
    for app in list_apps():
        for fname in ['issue_info.csv', 'report_summary.csv']:
            path = os.path.join(DATA, app, fname)
            if os.path.exists(path):
                files.append(path)
    return files

def watch_csv_files():
    global _file_mtimes
    csv_files = _collect_csv_files()
    for f in csv_files:
        try:
            _file_mtimes[f] = os.path.getmtime(f)
        except OSError:
            _file_mtimes[f] = 0

    while _watch_running:
        time.sleep(2)
        current_files = _collect_csv_files()
        for f in current_files:
            try:
                mtime = os.path.getmtime(f)
            except OSError:
                mtime = 0
            if mtime != _file_mtimes.get(f, 0):
                _file_mtimes[f] = mtime
                sse_manager.notify_all('data_updated')
        # 检测新增的 CSV 文件
        for f in current_files:
            if f not in _file_mtimes:
                try:
                    _file_mtimes[f] = os.path.getmtime(f)
                except OSError:
                    _file_mtimes[f] = 0

# ── HTTP 请求处理 ───────────────────────────────────────────────

class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=BASE, **kw)

    def _get_app(self):
        """从 query string 提取 app 参数，默认返回第一个可用应用"""
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        app = params.get('app', [None])[0]
        if app:
            return app
        apps = list_apps()
        return apps[0] if apps else 'default'

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == '/api/apps':
            self._json_response(list_apps())
        elif parsed.path == '/api/issues':
            self._json_response(self._read_issues(self._get_app()))
        elif parsed.path == '/api/summary':
            self._json_response(self._read_summary(self._get_app()))
        elif parsed.path == '/api/trend':
            self._json_response(self._read_trend(self._get_app()))
        elif parsed.path == '/api/events':
            self._handle_sse()
        else:
            super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        length = int(self.headers.get('Content-Length', 0))
        body = json.loads(self.rfile.read(length).decode('utf-8')) if length else {}
        app = self._get_app()

        if parsed.path == '/api/save_issue':
            self._save_issue(app, body)
        elif parsed.path == '/api/add_issue':
            self._add_issue(app, body)
        elif parsed.path == '/api/delete_issue':
            self._delete_issue(app, body)
        elif parsed.path == '/api/add_summary':
            self._add_summary(app, body)
        else:
            self._json_response({'error': 'not found'}, 404)

    # ── SSE ──
    def _handle_sse(self):
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.send_header('Cache-Control', 'no-cache')
        self.send_header('Connection', 'keep-alive')
        self.end_headers()
        sse_manager.add_client(self.wfile)
        try:
            self.wfile.write(b'data: connected\n\n')
            self.wfile.flush()
            # 心跳保活，不阻塞数据推送
            while True:
                time.sleep(30)
                self.wfile.write(b': heartbeat\n\n')
                self.wfile.flush()
        except Exception:
            pass
        finally:
            sse_manager.remove_client(self.wfile)

    # ── 读取 API ──
    def _read_issues(self, app):
        path = issue_csv(app)
        if not os.path.exists(path):
            return {}
        rows = read_csv(path)
        result = {}
        for r in rows:
            issue = row_to_issue(r)
            iid = issue['issue_id']
            if not iid:
                continue
            issue['current_percentage'] = self._calc_percentage(app, issue['issue_name'])
            result[iid] = issue
        return result

    def _read_summary(self, app):
        path = summary_csv(app)
        if not os.path.exists(path):
            return []
        rows = read_csv(path)
        return [{'date': r.get('报告日期', '').strip(),
                 'period': r.get('数据周期', '').strip(),
                 'rate': _parse_float(r.get('崩溃率(‱)', '')),
                 'version': r.get('最新版本', '').strip()} for r in rows]

    def _read_trend(self, app):
        # 从 issue_info.csv 的趋势数据 JSON 列重建趋势结构
        path = issue_csv(app)
        if not os.path.exists(path):
            return {'dates': [], 'issues': [], 'data': {}}
        rows = read_csv(path)
        date_set = set()
        issue_set = set()
        raw_data = defaultdict(dict)
        for r in rows:
            name = r.get('问题名称', '').strip()
            if not name:
                continue
            trend_json = r.get('趋势数据', '[]').strip()
            try:
                entries = json.loads(trend_json)
            except Exception:
                entries = []
            for e in entries:
                d = e.get('d', '')
                p = float(e.get('p', 0))
                date_set.add(d)
                issue_set.add(name)
                raw_data[d][name] = p
        dates = sorted(date_set)
        issues = sorted(issue_set)
        tdata = {}
        for iss in issues:
            tdata[iss] = [raw_data.get(d, {}).get(iss, 0) for d in dates]
        return {'dates': dates, 'issues': issues, 'data': tdata}

    def _calc_percentage(self, app, issue_name):
        path = issue_csv(app)
        try:
            rows = read_csv(path)
        except Exception:
            return 0
        latest_date = ''
        latest_pct = 0.0
        for r in rows:
            name = r.get('问题名称', '').strip()
            if name == issue_name or issue_name.find(name) >= 0 or name.find(issue_name) >= 0:
                trend_json = r.get('趋势数据', '[]').strip()
                try:
                    entries = json.loads(trend_json)
                except Exception:
                    entries = []
                for e in entries:
                    d = e.get('d', '')
                    p = float(e.get('p', 0))
                    if d > latest_date:
                        latest_date = d
                        latest_pct = p
        return latest_pct

    # ── 写入 API ──
    def _normalize_body(self, body):
        norm = {}
        for key, val in body.items():
            en = ISSUE_CN_TO_EN.get(key, key)
            norm[en] = str(val).strip() if val else ''
        return norm

    def _save_issue(self, app, body):
        data = self._normalize_body(body)
        issue_id = data.get('issue_id', '')
        if not issue_id:
            self._json_response({'error': 'issue_id 不能为空'}, 400)
            return

        path = issue_csv(app)
        rows = read_csv(path)
        found = False
        for row in rows:
            if row.get('问题ID', '').strip() == issue_id:
                for en_key, val in data.items():
                    cn_key = EN_TO_ISSUE_CN.get(en_key)
                    if cn_key and cn_key != '问题ID':
                        row[cn_key] = str(val) if val else ''
                found = True
                break

        if not found:
            self._json_response({'error': 'issue not found'}, 404)
            return

        write_csv(path, rows, ISSUE_FIELDNAMES)
        sse_manager.notify_all('data_updated')
        self._json_response({'ok': True})

    def _add_issue(self, app, body):
        data = self._normalize_body(body)
        issue_id = data.get('issue_id', '')
        if not issue_id:
            self._json_response({'error': 'issue_id 不能为空'}, 400)
            return

        path = issue_csv(app)
        rows = read_csv(path)
        for row in rows:
            if row.get('问题ID', '').strip() == issue_id:
                self._json_response({'error': 'issue_id 已存在'}, 400)
                return

        new_row = {cn: '' for cn in ISSUE_FIELDNAMES}
        for en_key, val in data.items():
            cn_key = EN_TO_ISSUE_CN.get(en_key)
            if cn_key:
                new_row[cn_key] = str(val) if val else ''
        rows.append(new_row)

        write_csv(path, rows, ISSUE_FIELDNAMES)
        sse_manager.notify_all('data_updated')
        self._json_response({'ok': True})

    def _delete_issue(self, app, body):
        data = self._normalize_body(body)
        issue_id = data.get('issue_id', '')
        if not issue_id:
            self._json_response({'error': 'issue_id 不能为空'}, 400)
            return

        path = issue_csv(app)
        rows = read_csv(path)
        rows = [r for r in rows if r.get('问题ID', '').strip() != issue_id]

        write_csv(path, rows, ISSUE_FIELDNAMES)
        sse_manager.notify_all('data_updated')
        self._json_response({'ok': True})

    def _add_summary(self, app, body):
        path = summary_csv(app)
        rows = read_csv(path)
        fieldnames = ['报告日期', '数据周期', '崩溃率(‱)', '最新版本']
        rows.append({
            '报告日期': body.get('date', ''),
            '数据周期': body.get('period', ''),
            '崩溃率(‱)': str(body.get('rate', '')),
            '最新版本': body.get('version', ''),
        })
        write_csv(path, rows, fieldnames)
        sse_manager.notify_all('data_updated')
        self._json_response({'ok': True})

    # ── 工具方法 ──
    def _json_response(self, data, code=200):
        payload = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', len(payload))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, fmt, *args):
        pass


def _parse_float(v, default=None):
    if not v or not str(v).strip():
        return default
    try:
        return float(str(v).strip())
    except (ValueError, TypeError):
        return default


# ── 启动 ────────────────────────────────────────────────────────

if __name__ == '__main__':
    watcher = threading.Thread(target=watch_csv_files, daemon=True)
    watcher.start()

    apps = list_apps()
    print(f'看板服务器启动: http://127.0.0.1:{PORT}/')
    print(f'已发现 {len(apps)} 个应用: {", ".join(apps)}')
    print(f'已发现 {len(apps)} 个应用: {", ".join(apps)}')
    print(f'数据目录: {DATA}/')
    print('Ctrl+C 停止')

    # 杀掉占用端口的旧进程
    try:
        result = subprocess.run(['lsof', '-ti', f':{PORT}'], capture_output=True, text=True)
        for pid in result.stdout.strip().split('\n'):
            if pid and int(pid) != os.getpid():
                os.kill(int(pid), signal.SIGTERM)
                print(f'已终止旧进程 PID={pid}')
        time.sleep(0.5)
    except Exception:
        pass

    server = ThreadingHTTPServer(('0.0.0.0', PORT), Handler)
    server.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        _watch_running = False
        server.server_close()
        print('已停止')
