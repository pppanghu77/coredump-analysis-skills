#!/usr/bin/env python3
"""
看板服务器 — 只读展示 coredump-stack-clustering workspace

数据全部来自 pipeline 产出物,无独立数据源、不可编辑:
- hash 趋势/占比: <workspace>/3_version_analysis_results/_hash_trend_by_week.csv
- 崩溃率时间序列: <workspace>/1_download/<package>_summary_<周>.csv

"应用"(app) = package。一个 package 可能有多份 workspace(不同日期范围),
自动取 end_date 最大者展示。
"""

import csv, json, os, re, signal, socket, subprocess, threading, time, glob
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

BASE = os.path.dirname(os.path.abspath(__file__))          # .../coredump-stack-clustering/kanban
REPO_ROOT = os.path.dirname(BASE)                          # .../coredump-stack-clustering
WS_ROOT = os.path.join(REPO_ROOT, 'data')                  # .../coredump-stack-clustering/data
PORT = 8765

# ── workspace 发现 ──────────────────────────────────────────────

_WS_RE = re.compile(r'^workspace_(.+)_(\d{8})_(\d{8})$')
_WEEK_RE = re.compile(r'^(\d{8})[_-](\d{8})$')


def list_apps():
    """扫描 WS_ROOT 下 workspace_<package>_<start>_<end>,返回去重排序的 package 列表"""
    apps = []
    if not os.path.isdir(WS_ROOT):
        return apps
    for name in os.listdir(WS_ROOT):
        m = _WS_RE.match(name)
        if m:
            apps.append(m.group(1))
    return sorted(set(apps))


def _resolve_workspace(app):
    """在该 package 的所有 workspace 中取 end_date(目录名末段)最大者"""
    best, best_end = None, ''
    if not os.path.isdir(WS_ROOT):
        return None
    for name in os.listdir(WS_ROOT):
        m = _WS_RE.match(name)
        if m and m.group(1) == app:
            end = m.group(3)
            if end > best_end:
                best_end, best = end, name
    return os.path.join(WS_ROOT, best) if best else None


def _hash_trend_path(ws):
    return os.path.join(ws, '3_version_analysis_results', '_hash_trend_by_week.csv')


# ── 日期工具 ────────────────────────────────────────────────────

def _norm_week(s):
    """统一周标签分隔符为 '_'： '20260511-20260517' → '20260511_20260517'"""
    return s.strip().rstrip('%').strip().replace('-', '_')


def _week_iso_end(col):
    """周标签 → 周尾日 ISO 日期： '20260511_20260517 %' → '2026-05-17'"""
    m = _WEEK_RE.match(_norm_week(col))
    if not m:
        return None
    e = m.group(2)
    return f"{e[:4]}-{e[4:6]}-{e[6:8]}"


def _week_period(col):
    """周标签 → 友好周期标签： '20260511_20260517' → '2026.05.11-05.17'"""
    m = _WEEK_RE.match(_norm_week(col))
    if not m:
        return col
    s, e = m.group(1), m.group(2)
    return f"{s[:4]}.{s[4:6]}.{s[6:8]}-{e[4:6]}.{e[6:8]}"


# ── issue_name 生成(可读 + 唯一 + 与 trend key 一致) ───────────

_FUNC_RE = re.compile(r'^(\S+)\s*(?:\(([^)]*)\))?')


def _extract_func_lib(line):
    """'raise (libc.so.6 + )' → ('raise', 'libc.so.6')；'_ZN.. (libx.so + )' → ('_ZN..','libx.so')"""
    m = _FUNC_RE.match(line.strip())
    if not m:
        return '', ''
    func = m.group(1)
    lib_raw = m.group(2) or ''
    lib = lib_raw.split()[0] if lib_raw.strip() else ''
    return func, lib


def make_issue_name(stack, h):
    """从 cleaned stack 派生可读且全局唯一的名称,尾缀 hash8 保证唯一。

    issue 与 trend 用同一函数同一行 stack 派生 → 名称必然一致,
    前端 appendTrend 用 issue_name 匹配 trend data key(完全相等命中)。
    """
    lines = [l.strip() for l in stack.split('\n') if l.strip()]
    frames = [l for l in lines if not l.lower().startswith('stack trace')]
    sig = []
    for l in frames[:6]:
        func, lib = _extract_func_lib(l)
        if func and func != 'n/a':
            sig.append(f"{func}@{lib}" if lib else func)
        if len(sig) >= 3:
            break
    if not sig:  # n/a 占满的符号缺失栈
        tail = [l for l in frames if 'n/a' not in l.lower()]
        for t in tail[-2:]:
            f = _extract_func_lib(t)[0]
            if f:
                sig.append(f)
        if not sig:
            sig = ['unknown']
    name = ' → '.join(sig[:3])
    if len(name) > 56:
        name = name[:53] + '…'
    return f"{name} [{h[:8]}]"


# ── issue 默认字段(前端契约:28 个英文 key,值用中文) ──────────

DEFAULT_ISSUE = {
    'issue_id': '', 'issue_name': '', 'domain': '', 'severity': '',
    'signal_type': '', 'stack_fingerprint': '', 'full_stack': '', 'root_cause': '',
    'introduced_version': '', 'first_seen_version': '', 'fix_version': '',
    'discovered_at': '', 'analysis_started_at': '', 'root_cause_found_at': '',
    'fix_submitted_at': '', 'verified_at': '', 'closed_at': '', 'first_seen_date': '',
    'fix_type': '', 'fix_effectiveness': '', 'post_fix_pct': '',
    'status': '分析中', 'assignee': '', 'related_issue': '', 'related_mr': '',
    'tags': '', 'affected_arch': '', 'notes': '', 'current_percentage': 0,
}

VALID_STATUS = {'分析中', '待验证', '已修复'}

# 只跟踪最新一周占比达到此阈值的 hash(聚焦头部问题,过滤长尾噪声)
MIN_TRACK_PCT = 1.0


def _sev_from_pct(pct):
    """按最新周占比自动分档严重程度"""
    if pct >= 10:
        return 'P0-致命'
    if pct >= 1:
        return 'P1-严重'
    if pct >= 0.1:
        return 'P2-一般'
    return 'P3-轻微'


# ── 读取 _hash_trend_by_week.csv(带 mtime 缓存) ────────────────

_trend_cache = {'path': None, 'mtime': 0.0, 'data': None}


def _read_hash_trend(ws):
    """读趋势宽表,返回 {weeks:[col原始], rows:[{hash, stack, pcts:[float]}]}"""
    path = _hash_trend_path(ws)
    try:
        mt = os.path.getmtime(path)
    except OSError:
        return None
    if _trend_cache['path'] == path and _trend_cache['mtime'] == mt:
        return _trend_cache['data']

    week_idx, stack_idx, hash_idx = [], None, 0
    with open(path, encoding='utf-8-sig', newline='') as f:
        reader = csv.reader(f)
        header = next(reader, None)
        if not header:
            return None
        for i, col in enumerate(header):
            hs = col.strip()
            if _WEEK_RE.match(_norm_week(hs)):
                week_idx.append(i)
            elif hs == 'Cleaned Stack':
                stack_idx = i
            elif hs == 'Crash Hash':
                hash_idx = i
        week_cols = [header[i] for i in week_idx]
        rows_out = []
        for r in reader:
            if not r or not r[hash_idx].strip():
                continue
            h = r[hash_idx].strip()
            stack = r[stack_idx] if (stack_idx is not None and stack_idx < len(r)) else ''
            pcts = []
            for i in week_idx:
                v = r[i].rstrip('%').strip() if i < len(r) else ''
                try:
                    pcts.append(float(v))
                except ValueError:
                    pcts.append(0.0)
            rows_out.append({'hash': h, 'stack': stack, 'pcts': pcts})

    result = {'weeks': week_cols, 'rows': rows_out}
    _trend_cache.update(path=path, mtime=mt, data=result)
    return result


# ── 业务读取 ────────────────────────────────────────────────────

def read_issues(app):
    ws = _resolve_workspace(app)
    trend = _read_hash_trend(ws) if ws else None
    if not trend:
        return {}
    fixes = read_fix_records()
    result = {}
    for row in trend['rows']:
        h = row['hash']
        latest = row['pcts'][-1] if row['pcts'] else 0.0
        if latest < MIN_TRACK_PCT:
            continue
        name = make_issue_name(row['stack'], h)
        issue = dict(DEFAULT_ISSUE)
        issue.update(
            issue_id=h, issue_name=name,
            full_stack=row['stack'], stack_fingerprint=h[:8],
            current_percentage=round(latest, 2),
            severity=_sev_from_pct(latest),
        )
        urls = _match_fixes(h, fixes)
        if urls:
            issue['status'] = '待验证'
            issue['related_mr'] = ', '.join(urls)
        result[h] = issue
    return result


def read_trend(app):
    ws = _resolve_workspace(app)
    trend = _read_hash_trend(ws) if ws else None
    if not trend:
        return {'dates': [], 'issues': [], 'data': {}}
    dates = [d for d in (_week_iso_end(c) for c in trend['weeks']) if d]
    data, issues = {}, []
    for row in trend['rows']:
        latest = row['pcts'][-1] if row['pcts'] else 0.0
        if latest < MIN_TRACK_PCT:
            continue
        name = make_issue_name(row['stack'], row['hash'])
        data[name] = list(row['pcts'])
        issues.append(name)
    return {'dates': dates, 'issues': issues, 'data': data}


def read_summary(app):
    """聚合 1_download/<package>_summary_<周>.csv → [{date,period,version,rate}]

    rate = 该周各版本"崩溃率(万分之)"求和(复刻旧 update_summary.sh 语义);
    version = 该周崩溃次数最多的版本;date = 统计时段周尾日 ISO。
    """
    ws = _resolve_workspace(app)
    if not ws:
        return []
    files = sorted(glob.glob(os.path.join(ws, '1_download', f'{app}_summary_*_*.csv')))
    out = []
    for fp in files:
        m = re.search(r'_summary_(\d{8}[-_]\d{8})', os.path.basename(fp))
        if not m:
            continue
        week = m.group(1).replace('-', '_')
        try:
            with open(fp, encoding='utf-8', newline='') as f:
                rows = list(csv.DictReader(f))
        except OSError:
            continue
        if not rows:
            continue
        rate = 0.0
        for r in rows:
            try:
                rate += float(r.get('崩溃率(万分之)', '0') or 0)
            except ValueError:
                pass
        best = max(rows, key=lambda r: _safe_int(r.get('崩溃次数', '0')))
        out.append({
            'date': _week_iso_end(week),
            'period': _week_period(week),
            'version': best.get('应用版本', ''),
            'rate': round(rate, 2),
        })
    out.sort(key=lambda r: r['date'])
    return out


def _safe_int(v):
    try:
        return int(v)
    except (ValueError, TypeError):
        return 0


def read_distribution(app):
    """全量 hash 分布(不做 ≥1% 过滤),供饼图展示完整长尾。

    返回 [{hash, name, pct, stack, weeks}],按最新一周占比降序。
    weeks 为各周占比序列,供详情弹窗的趋势卡片使用。
    """
    ws = _resolve_workspace(app)
    trend = _read_hash_trend(ws) if ws else None
    if not trend:
        return []
    out = []
    for row in trend['rows']:
        latest = round(row['pcts'][-1] if row['pcts'] else 0.0, 2)
        if latest <= 0:  # 最新周无占比(0%)的不进饼图
            continue
        out.append({
            'hash': row['hash'],
            'name': make_issue_name(row['stack'], row['hash']),
            'pct': latest,
            'stack': row['stack'],
            'weeks': list(row['pcts']),
        })
    out.sort(key=lambda x: -x['pct'])
    return out


FIX_RECORDS_FILE = os.path.join(BASE, '修复记录.csv')


def read_fix_records():
    """读修复记录 CSV(多对多: gerrit_url ↔ crash_hash)。

    每行一个 (gerrit_url, crash_hash) 对:一个 MR 修复多个 hash 写多行,
    一个 hash 被多个 MR 修复也写多行。crash_hash 可写 8 位或 12 位前缀。
    返回 {hash_prefix: [urls]}。
    """
    records = {}
    if not os.path.exists(FIX_RECORDS_FILE):
        return records
    with open(FIX_RECORDS_FILE, encoding='utf-8-sig', newline='') as f:
        for r in csv.DictReader(f):
            url = (r.get('gerrit_url') or '').strip()
            h = (r.get('crash_hash') or '').strip()
            if url and h:
                records.setdefault(h, []).append(url)
    return records


def _match_fixes(full_hash, fixes):
    """完整 12 位 hash 与修复记录(前缀)双向匹配,返回命中的 url 列表"""
    urls = []
    for prefix, us in fixes.items():
        if full_hash == prefix or full_hash.startswith(prefix) or prefix.startswith(full_hash):
            urls.extend(us)
    return urls


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
    """收集各 workspace 的趋势表 + summary 文件 + 修复记录,变更后自动推前端刷新"""
    files = []
    if os.path.exists(FIX_RECORDS_FILE):
        files.append(FIX_RECORDS_FILE)
    for app in list_apps():
        ws = _resolve_workspace(app)
        if not ws:
            continue
        ht = _hash_trend_path(ws)
        if os.path.exists(ht):
            files.append(ht)
        for fp in glob.glob(os.path.join(ws, '1_download', '*_summary_*.csv')):
            files.append(fp)
    return files


def watch_csv_files():
    global _file_mtimes
    for f in _collect_csv_files():
        try:
            _file_mtimes[f] = os.path.getmtime(f)
        except OSError:
            _file_mtimes[f] = 0
    while _watch_running:
        time.sleep(2)
        current = _collect_csv_files()
        for f in current:
            try:
                mt = os.path.getmtime(f)
            except OSError:
                mt = 0
            if mt != _file_mtimes.get(f, 0):
                _file_mtimes[f] = mt
                _trend_cache['mtime'] = 0  # 失效缓存,强制重读
                sse_manager.notify_all('data_updated')
        for f in current:
            if f not in _file_mtimes:
                try:
                    _file_mtimes[f] = os.path.getmtime(f)
                except OSError:
                    _file_mtimes[f] = 0


# ── HTTP 请求处理 ───────────────────────────────────────────────

class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=BASE, **kw)

    def end_headers(self):
        # 静态文件(index.html 等)禁缓存,前端改动后浏览器自动取最新
        self.send_header('Cache-Control', 'no-cache, must-revalidate')
        super().end_headers()

    def _get_app(self):
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
            self._json_response(read_issues(self._get_app()))
        elif parsed.path == '/api/summary':
            self._json_response(read_summary(self._get_app()))
        elif parsed.path == '/api/trend':
            self._json_response(read_trend(self._get_app()))
        elif parsed.path == '/api/distribution':
            self._json_response(read_distribution(self._get_app()))
        elif parsed.path == '/api/events':
            self._handle_sse()
        else:
            super().do_GET()

    def do_POST(self):
        # 只读模式:数据来自 pipeline workspace,不支持编辑
        self._json_response({'error': '只读模式:数据来自 pipeline workspace,不可编辑'}, 403)

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
            while True:
                time.sleep(30)
                self.wfile.write(b': heartbeat\n\n')
                self.wfile.flush()
        except Exception:
            pass
        finally:
            sse_manager.remove_client(self.wfile)

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


# ── 启动 ────────────────────────────────────────────────────────

if __name__ == '__main__':
    watcher = threading.Thread(target=watch_csv_files, daemon=True)
    watcher.start()

    apps = list_apps()
    print(f'看板服务器启动: http://127.0.0.1:{PORT}/')
    print(f'已发现 {len(apps)} 个应用: {", ".join(apps)}')
    for app in apps:
        ws = _resolve_workspace(app)
        print(f'  {app} → {ws}')

    print('Ctrl+C 停止')

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
