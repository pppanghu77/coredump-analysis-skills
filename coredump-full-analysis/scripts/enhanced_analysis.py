#!/usr/bin/env python3
"""
Enhanced crash analysis module

Provides 5 analysis methods for crash stack traces:
  1. addr2line + source context  — resolve addresses to source file:line
  2. objdump disassembly         — disassemble crash function
  3. git blame/log               — identify recent changes to crash source
  4. LLM stack reasoning        — AI-powered root cause analysis
  5. debuginfod online symbols   — online debug symbol lookup
"""

import subprocess
import re
import os
import json
import time
import logging
import urllib.request
import urllib.error
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Stack frame parsing
# ---------------------------------------------------------------------------

def parse_frame_addresses(stack_info: str) -> List[Dict]:
    """Parse stack trace into structured frames with addresses and offsets.

    Returns list of dicts: {address, address_int, symbol, library, offset}
    offset is an int (bytes from library base) when available, else None.
    """
    frames = []
    for line in stack_info.strip().split('\n'):
        m = re.match(
            r'\s*#\s*\d+\s+(0x[0-9a-fA-F]+)\s+(\S+)\s+\(([^)]*)\)', line
        )
        if m:
            addr = m.group(1)
            symbol = m.group(2)
            lib_info = m.group(3).strip()

            offset = None
            library = lib_info
            lib_m = re.match(r'(\S+)\s*\+\s*(0x[0-9a-fA-F]+)', lib_info)
            if lib_m:
                library = lib_m.group(1)
                offset = int(lib_m.group(2), 16)

            frames.append({
                'address': addr,
                'address_int': int(addr, 16),
                'symbol': symbol,
                'library': library,
                'offset': offset,
            })
    return frames


def compute_offsets(frames: List[Dict]) -> List[Dict]:
    """For frames without explicit offset, compute it from library base.

    The library base is estimated as the lowest address seen for that library.
    """
    lib_bases: Dict[str, int] = {}
    for f in frames:
        lib = f['library']
        if lib == 'n/a' or not lib:
            continue
        if f['offset'] is not None:
            # We know the base = address_int - offset for this library
            base = f['address_int'] - f['offset']
            if lib not in lib_bases or base < lib_bases[lib]:
                lib_bases[lib] = base

    # Now compute offsets for frames that don't have them
    for f in frames:
        if f['offset'] is None and f['library'] in lib_bases:
            f['offset'] = f['address_int'] - lib_bases[f['library']]
    return frames


# ---------------------------------------------------------------------------
# Binary resolver — find library / debug files on the system
# ---------------------------------------------------------------------------

class BinaryResolver:
    """Locates shared libraries, executables and their debug files."""

    SEARCH_PATHS = [
        '/usr/lib/x86_64-linux-gnu',
        '/usr/lib',
        '/lib/x86_64-linux-gnu',
        '/lib',
        '/usr/lib/debug/usr/lib/x86_64-linux-gnu',
        '/usr/lib/debug/usr/lib',
        '/usr/lib/debug/lib/x86_64-linux-gnu',
        '/usr/lib/debug/lib',
    ]

    def __init__(self, workspace: str, package: str):
        self.workspace = Path(workspace)
        self.package = package
        self._lib_cache: Dict[str, Optional[str]] = {}
        self._buildid_cache: Dict[str, Optional[str]] = {}
        # Pre-build index of all debug files by build-id
        self._buildid_index: Dict[str, str] = {}
        self._index_buildids()

    # -- build-id index --------------------------------------------------

    def _index_buildids(self):
        """Scan /usr/lib/debug/.build-id for available debug files."""
        bid_dir = Path('/usr/lib/debug/.build-id')
        if not bid_dir.is_dir():
            return
        try:
            result = subprocess.run(
                ['find', str(bid_dir), '-name', '*.debug'],
                capture_output=True, text=True, timeout=30
            )
            if result.returncode == 0:
                for line in result.stdout.strip().split('\n'):
                    if not line:
                        continue
                    p = Path(line)
                    # Path: .../ab/cdef1234....debug  →  build-id = abcdef1234...
                    parent = p.parent.name       # "ab"
                    stem = p.stem                # "cdef1234..."
                    bid = parent + stem
                    self._buildid_index[bid] = str(p)
        except Exception:
            pass

    def find_debug_by_buildid(self, buildid: str) -> Optional[str]:
        """Return debug file path for a given build-id."""
        if not buildid or len(buildid) < 8:
            return None
        bid = buildid.lower().replace('-', '')
        if bid in self._buildid_index:
            return self._buildid_index[bid]
        # Direct path check
        direct = Path(f'/usr/lib/debug/.build-id/{bid[:2]}/{bid[2:]}.debug')
        if direct.exists():
            return str(direct)
        return None

    # -- library lookup --------------------------------------------------

    def find_library(self, lib_name: str) -> Optional[str]:
        """Locate a shared library or executable on the filesystem."""
        if lib_name in self._lib_cache:
            return self._lib_cache[lib_name]

        if not lib_name or lib_name == 'n/a':
            self._lib_cache[lib_name] = None
            return None

        path = self._find_library_impl(lib_name)
        self._lib_cache[lib_name] = path
        return path

    def _find_library_impl(self, lib_name: str) -> Optional[str]:
        # 1) dpkg -S
        try:
            r = subprocess.run(
                ['dpkg', '-S', lib_name],
                capture_output=True, text=True, timeout=5
            )
            if r.returncode == 0:
                for line in r.stdout.strip().split('\n'):
                    _, path = line.split(': ', 1)
                    if os.path.exists(path):
                        return path
        except Exception:
            pass

        # 2) Direct search in common paths
        for base in self.SEARCH_PATHS:
            candidate = os.path.join(base, lib_name)
            if os.path.exists(candidate):
                return candidate

        # 3) If lib_name looks like an executable path (e.g. /usr/bin/dde-dock)
        if lib_name.startswith('/'):
            if os.path.exists(lib_name):
                return lib_name

        return None

    def find_debug_file(self, lib_path: str) -> Optional[str]:
        """Find separate debug file for a given binary."""
        if not lib_path or not os.path.exists(lib_path):
            return None

        # 1) Build-ID based lookup (most reliable)
        try:
            r = subprocess.run(
                ['readelf', '-n', lib_path],
                capture_output=True, text=True, timeout=10
            )
            m = re.search(r'Build ID:\s*([0-9a-f]+)', r.stdout)
            if m:
                bid = m.group(1)
                dbg = self.find_debug_by_buildid(bid)
                if dbg:
                    return dbg
        except Exception:
            pass

        # 2) Path-based: /usr/lib/debug/usr/lib/... → mirror of /usr/lib/...
        if lib_path.startswith('/usr/'):
            dbg = '/usr/lib/debug' + lib_path
            if os.path.exists(dbg):
                return dbg

        # 3) .debug suffix
        dbg = lib_path + '.debug'
        if os.path.exists(dbg):
            return dbg

        return None

    def find_main_binary(self, exe: str) -> Optional[str]:
        """Find the main executable binary."""
        if not exe:
            return None
        if os.path.exists(exe):
            return exe
        return self.find_library(os.path.basename(exe))


# ---------------------------------------------------------------------------
# 1. addr2line + source context
# ---------------------------------------------------------------------------

class Addr2LineAnalyzer:
    """Resolve crash addresses to source file:line using addr2line."""

    def __init__(self, resolver: BinaryResolver, source_dir: Optional[str] = None):
        self.resolver = resolver
        self.source_dir = Path(source_dir) if source_dir else None
        self._source_cache: Dict[str, List[str]] = {}
        self._file_search_cache: Dict[str, Optional[str]] = {}

    def resolve_frame(self, lib_name: str, offset: Optional[int]) -> Dict:
        """Resolve a single frame to source location."""
        if offset is None:
            return {'status': 'no_offset'}

        lib_path = self.resolver.find_library(lib_name)
        if not lib_path:
            return {'status': 'lib_not_found', 'library': lib_name}

        # Collect all results and pick the best
        best = None

        for binary in [lib_path, self.resolver.find_debug_file(lib_path)]:
            if not binary:
                continue
            result = self._run_addr2line(binary, offset)
            if result.get('status') == 'error' or result.get('status') == 'timeout':
                continue
            # Keep best result (prefer one with file+line, then function-only)
            if best is None:
                best = result
            elif result.get('file') and result['file'] != '??' and (not best.get('file') or best['file'] == '??'):
                best = result
            elif result.get('function') and result['function'] != '??' and not best.get('function'):
                best = result

        if best is None:
            return {'status': 'unresolved', 'library': lib_name, 'binary': lib_path}

        best['library'] = lib_name
        best['offset'] = offset
        # If _run_addr2line already set status, keep it; otherwise classify
        if best.get('status') in ('ok', 'partial', 'unresolved'):
            return best
        # Backward compatibility
        if best.get('file') and best['file'] != '??' and best.get('line'):
            best['status'] = 'ok'
        elif best.get('function') and best.get('function') != '??':
            best['status'] = 'partial'
        else:
            best['status'] = 'unresolved'
        return best

        return {'status': 'unresolved', 'library': lib_name, 'binary': lib_path}

    def resolve_frames(self, frames: List[Dict], max_frames: int = 20) -> List[Dict]:
        """Resolve multiple frames, return results in order."""
        results = []
        for f in frames[:max_frames]:
            if f['symbol'] != 'n/a' and f['library'] == 'n/a':
                results.append({'status': 'skip', 'reason': 'no library'})
                continue
            r = self.resolve_frame(f['library'], f.get('offset'))
            r['frame_index'] = frames.index(f)
            r['symbol'] = f['symbol']
            r['library'] = f['library']

            # For partial resolution (function name only), try source search
            if r.get('status') == 'partial' and r.get('function') and self.source_dir:
                source_file = self._find_source_by_function(r['function'])
                if source_file:
                    r['source_file'] = source_file
                    r['status'] = 'partial_with_source'

            results.append(r)
        return results

    def _find_source_by_function(self, mangled_name: str) -> Optional[str]:
        """Try to find a source file by searching for the function definition."""
        if not mangled_name or not self.source_dir:
            return None
        # Demangle if needed
        demangled = self._demangle(mangled_name)
        # Extract search terms
        parts = demangled.split('::')
        search_terms = []

        # Best: full qualified name without args
        # e.g. "PluginListView::rowsInserted(QModelIndex const&, int, int)"
        # → "PluginListView::rowsInserted"
        if len(parts) >= 2:
            method_name = parts[-1].split('(')[0].strip()
            class_name = parts[-2].split('<')[0].strip()
            qualified = f'{class_name}::{method_name}'
            if len(qualified) >= 5:
                search_terms.append(('qualified', qualified))
            # Also class name as fallback
            if len(class_name) >= 3:
                search_terms.append(('class', class_name))

        for term_type, term in search_terms:
            try:
                r = subprocess.run(
                    ['grep', '-rn', '--include=*.cpp', '--include=*.cc',
                     '--include=*.c', '-F', term, str(self.source_dir)],
                    capture_output=True, text=True, timeout=30
                )
                if r.returncode == 0 and r.stdout.strip():
                    matches = r.stdout.strip().split('\n')
                    # For qualified search, return first .cpp match (definition)
                    if term_type == 'qualified':
                        for m in matches:
                            m = m.strip()
                            if any(m.endswith(ext) for ext in ['.cpp', '.cc', '.c']):
                                # Extract relative path
                                parts = m.split(':', 1)
                                rel = os.path.relpath(parts[0], str(self.source_dir))
                                return rel
                    # For class name, pick the most specific file
                    for m in matches:
                        m = m.strip()
                        if any(m.endswith(ext) for ext in ['.cpp', '.cc', '.c']):
                            parts = m.split(':', 1)
                            rel = os.path.relpath(parts[0], str(self.source_dir))
                            return rel
                    # Fall back to header
                    for m in matches:
                        parts = m.split(':', 1)
                        rel = os.path.relpath(parts[0], str(self.source_dir))
                        return rel
            except Exception:
                pass
        return None

    def _demangle(self, name: str) -> str:
        """Demangle a C++ symbol name."""
        if not name.startswith('_Z'):
            return name
        try:
            r = subprocess.run(
                ['c++filt', name],
                capture_output=True, text=True, timeout=5
            )
            if r.returncode == 0 and r.stdout.strip():
                return r.stdout.strip()
        except Exception:
            pass
        return name

    def get_source_context(self, file_path: str, line: int,
                           context_lines: int = 5) -> Dict:
        """Read source code around the crash line."""
        if not file_path or not line or not self.source_dir:
            return {'available': False, 'reason': 'no source_dir'}

        real_path = self._locate_source(file_path)
        if not real_path:
            return {'available': False, 'reason': 'file_not_found', 'file': file_path}

        try:
            text = real_path.read_text(encoding='utf-8', errors='replace')
            lines = text.splitlines()
            start = max(0, line - context_lines - 1)
            end = min(len(lines), line + context_lines)

            context = []
            for i in range(start, end):
                context.append({
                    'line_num': i + 1,
                    'content': lines[i],
                    'is_crash_line': (i + 1) == line,
                })
            return {
                'available': True,
                'source_file': str(real_path),
                'display_file': file_path,
                'line': line,
                'context': context,
            }
        except Exception as e:
            return {'available': False, 'reason': str(e)}

    def _locate_source(self, file_path: str) -> Optional[Path]:
        """Find a source file in the source directory."""
        if not self.source_dir:
            return None

        # Build candidate relative paths
        candidates = []
        if file_path.startswith('/'):
            candidates.append(file_path)
            # Strip common build prefixes
            for prefix in ['/build/', '/source/', '/src/', '/home/']:
                if file_path.startswith(prefix):
                    candidates.append(file_path[len(prefix):])
        else:
            # Already a relative path - try it directly
            candidates.append(file_path)

        basename = os.path.basename(file_path)
        candidates.append(basename)

        for c in candidates:
            p = self.source_dir / c
            if p.exists():
                return p

        # Find by basename
        if basename not in self._file_search_cache:
            self._file_search_cache[basename] = self._find_file_by_name(basename)
        found = self._file_search_cache[basename]
        return found

    def _find_file_by_name(self, name: str) -> Optional[Path]:
        try:
            env = os.environ.copy()
            env['LC_ALL'] = 'C'
            r = subprocess.run(
                ['find', str(self.source_dir), '-name', name, '-type', 'f'],
                capture_output=True, text=True, timeout=20, env=env
            )
            if r.returncode == 0 and r.stdout.strip():
                return Path(r.stdout.strip().split('\n')[0])
        except Exception:
            pass
        return None

    def _run_addr2line(self, binary: str, offset: int) -> Dict:
        try:
            r = subprocess.run(
                ['addr2line', '-e', binary, '-f', '-p', f'0x{offset:x}'],
                capture_output=True, text=True, timeout=10
            )
            out = r.stdout.strip()
            if not out:
                return {'status': 'error', 'error': 'empty_output'}

            # Format: "func_name at /path/file.cpp:123" or "func_name 于 /path/file.cpp:123"
            # Both English "at" and Chinese "于" are possible
            m = re.match(r'(.+?)\s+(?:at|于)\s+(.+):(\d+)', out)
            if m:
                func = m.group(1) if m.group(1) != '??' else None
                return {
                    'status': 'ok' if m.group(2) != '??' else 'partial',
                    'function': func,
                    'file': m.group(2),
                    'line': int(m.group(3)) if m.group(2) != '??' else None,
                    'raw': out,
                }

            # Partial: function name only, "于 ??:?" or "at ??:?"
            m2 = re.match(r'(.+?)\s+(?:at|于)\s+\?\?:\?', out)
            if m2:
                func = m2.group(1) if m2.group(1) != '??' else None
                return {
                    'status': 'partial' if func else 'unresolved',
                    'function': func,
                    'file': None,
                    'line': None,
                    'raw': out,
                }

            # Just file:line
            m3 = re.match(r'(.+):(\d+)', out)
            if m3:
                return {
                    'status': 'ok' if m3.group(1) != '??' else 'unresolved',
                    'function': None,
                    'file': m3.group(1),
                    'line': int(m3.group(2)),
                    'raw': out,
                }

            return {'status': 'unresolved', 'raw': out}
        except subprocess.TimeoutExpired:
            return {'status': 'timeout'}
        except Exception as e:
            return {'status': 'error', 'error': str(e)}


# ---------------------------------------------------------------------------
# 2. objdump disassembly
# ---------------------------------------------------------------------------

class ObjdumpAnalyzer:
    """Disassemble code around crash addresses using objdump."""

    def __init__(self, resolver: BinaryResolver):
        self.resolver = resolver

    def disassemble_around(self, lib_name: str, offset: int,
                           before: int = 8, after: int = 8) -> Dict:
        """Disassemble instructions around the crash address."""
        lib_path = self.resolver.find_library(lib_name)
        if not lib_path:
            return {'available': False, 'reason': 'library_not_found'}

        # Use debug file if available for better symbol info
        debug = self.resolver.find_debug_file(lib_path)
        target = debug or lib_path

        start = max(0, offset - before * 4)
        end = offset + after * 4

        try:
            r = subprocess.run(
                ['objdump', '-d', '-M', 'intel',
                 '--start-address', f'0x{start:x}',
                 '--stop-address', f'0x{end:x}',
                 target],
                capture_output=True, text=True, timeout=30
            )
            if r.returncode != 0:
                return {'available': False, 'reason': 'objdump_failed'}

            lines = r.stdout.strip().split('\n')
            # Find the crash instruction line
            crash_idx = None
            for i, line in enumerate(lines):
                if re.search(rf'\b{offset:x}\b', line):
                    crash_idx = i
                    break

            return {
                'available': True,
                'library': lib_name,
                'offset': f'0x{offset:x}',
                'binary': target,
                'instructions': lines,
                'crash_instruction_index': crash_idx,
                'instruction_count': len(lines),
            }
        except subprocess.TimeoutExpired:
            return {'available': False, 'reason': 'timeout'}
        except Exception as e:
            return {'available': False, 'reason': str(e)}


# ---------------------------------------------------------------------------
# 3. git blame / log
# ---------------------------------------------------------------------------

class GitAnalyzer:
    """Git blame and log analysis on crash source files."""

    def __init__(self, source_dir: Optional[str]):
        self.source_dir = Path(source_dir) if source_dir else None
        self._rel_cache: Dict[str, Optional[str]] = {}

    def blame(self, file_path: str, line: int,
              context: int = 3) -> Dict:
        """Run git blame on the crash line with surrounding context."""
        if not self._git_available():
            return {'available': False, 'reason': 'no_git_repo'}

        rel = self._find_relative(file_path)
        if not rel:
            return {'available': False, 'reason': 'file_not_in_repo'}

        start = max(1, line - context)
        end = line + context

        try:
            r = subprocess.run(
                ['git', 'blame', f'-L{start},{end}', '-e', '--date=short', rel],
                capture_output=True, text=True, timeout=15,
                cwd=str(self.source_dir),
            )
            if r.returncode != 0:
                return {'available': False, 'reason': 'git_blame_failed'}

            blame_entries = []
            for bl in r.stdout.strip().split('\n'):
                m = re.match(
                    r'^(\^?[0-9a-f]+)\s+\((.+?)\s+(\d{4}-\d{2}-\d{2})\s+(\d+)\)\s+(.*)',
                    bl,
                )
                if m:
                    blame_entries.append({
                        'commit': m.group(1),
                        'author': m.group(2).strip(),
                        'date': m.group(3),
                        'line': int(m.group(4)),
                        'is_crash_line': int(m.group(4)) == line,
                        'code': m.group(5),
                    })
            return {'available': True, 'file': rel, 'entries': blame_entries}
        except subprocess.TimeoutExpired:
            return {'available': False, 'reason': 'timeout'}
        except Exception as e:
            return {'available': False, 'reason': str(e)}

    def log(self, file_path: str, max_commits: int = 10) -> Dict:
        """Recent git log for the crash file."""
        if not self._git_available():
            return {'available': False, 'reason': 'no_git_repo'}

        rel = self._find_relative(file_path)
        if not rel:
            return {'available': False, 'reason': 'file_not_in_repo'}

        try:
            r = subprocess.run(
                ['git', 'log', f'-{max_commits}', '--oneline',
                 '--date=short', '--format=%h %ad %an %s', rel],
                capture_output=True, text=True, timeout=15,
                cwd=str(self.source_dir),
            )
            if r.returncode != 0:
                return {'available': False, 'reason': 'git_log_failed'}

            commits = []
            for line in r.stdout.strip().split('\n'):
                if not line.strip():
                    continue
                parts = line.split(' ', 3)
                if len(parts) >= 4:
                    commits.append({
                        'hash': parts[0],
                        'date': parts[1],
                        'author': parts[2],
                        'message': parts[3],
                    })
            return {'available': True, 'file': rel, 'commits': commits}
        except Exception as e:
            return {'available': False, 'reason': str(e)}

    def _git_available(self) -> bool:
        return (
            self.source_dir
            and (self.source_dir / '.git').exists()
        )

    def _find_relative(self, file_path: str) -> Optional[str]:
        if not self.source_dir:
            return None
        if file_path in self._rel_cache:
            return self._rel_cache[file_path]

        candidates = [file_path]
        if file_path.startswith('/'):
            for pfx in ['/build/', '/source/', '/src/']:
                if file_path.startswith(pfx):
                    candidates.append(file_path[len(pfx):])

        for c in candidates:
            full = self.source_dir / c
            if full.exists():
                rel = str(full.relative_to(self.source_dir))
                self._rel_cache[file_path] = rel
                return rel

        # Search by basename
        basename = os.path.basename(file_path)
        try:
            r = subprocess.run(
                ['find', str(self.source_dir), '-name', basename, '-type f'],
                capture_output=True, text=True, timeout=15,
            )
            if r.returncode == 0 and r.stdout.strip():
                found = Path(r.stdout.strip().split('\n')[0])
                rel = str(found.relative_to(self.source_dir))
                self._rel_cache[file_path] = rel
                return rel
        except Exception:
            pass

        self._rel_cache[file_path] = None
        return None


# ---------------------------------------------------------------------------
# 4. LLM stack reasoning
# ---------------------------------------------------------------------------

class LLMStackAnalyzer:
    """Use LLM API to reason about crash root cause."""

    def __init__(self, config: Optional[Dict] = None):
        """
        config keys:
          api_key, api_base (default https://api.openai.com/v1),
          model (default gpt-4o-mini)
        """
        self.config = config or {}
        self.api_key = self.config.get('api_key') or os.environ.get(
            'OPENAI_API_KEY', ''
        )
        self.api_base = self.config.get('api_base', '').rstrip('/')
        self.model = self.config.get('model', 'gpt-4o-mini')
        self.enabled = bool(self.api_key and self.api_base)

    def analyze(self, crash: Dict, addr2line_results: List[Dict],
                source_contexts: List[Dict]) -> Dict:
        """Ask LLM to reason about crash root cause."""
        if not self.enabled:
            return {'available': False, 'reason': 'LLM API not configured'}

        prompt = self._build_prompt(crash, addr2line_results, source_contexts)
        if not prompt:
            return {'available': False, 'reason': 'insufficient_data'}

        try:
            response = self._call_llm(prompt)
            return {
                'available': True,
                'model': self.model,
                'analysis': response,
                'timestamp': datetime.now().isoformat(),
            }
        except Exception as e:
            return {'available': False, 'reason': str(e)}

    def _build_prompt(self, crash, a2l_results, source_contexts) -> str:
        parts = [
            "你是一个 C/C++ 崩溃分析专家。请分析以下崩溃信息，给出：",
            "1. 根因分析（root cause）",
            "2. 崩溃类型判定（空指针/释放后使用/缓冲区溢出/逻辑错误等）",
            "3. 修复建议（具体的代码修改方向）",
            "4. 置信度（high/medium/low）",
            "",
            "=== 崩溃信号 ===",
            f"信号: {crash.get('signal', 'N/A')}",
            f"进程: {crash.get('exe', 'N/A')}",
            f"应用层符号: {crash.get('app_layer_symbol', 'N/A')}",
            f"应用层库: {crash.get('app_layer_library', 'N/A')}",
            "",
            "=== 堆栈信息 ===",
        ]

        frames = crash.get('frames', [])
        for i, f in enumerate(frames[:15]):
            sym = f.get('symbol', '?')
            lib = f.get('library', '?')
            parts.append(f"  #{i} {sym} ({lib})")

        # Add addr2line resolved info
        resolved = [r for r in a2l_results if r.get('status') == 'ok']
        if resolved:
            parts.append("")
            parts.append("=== addr2line 解析结果 ===")
            for r in resolved[:10]:
                parts.append(
                    f"  {r.get('function', '?')} at {r.get('file', '?')}:{r.get('line', '?')}"
                    f"  [{r.get('library', '?')}]"
                )

        # Add source context
        for ctx in source_contexts:
            if ctx.get('available'):
                parts.append("")
                parts.append(f"=== 源码上下文: {ctx.get('display_file', '?')} ===")
                for line in ctx.get('context', []):
                    marker = '>>>' if line.get('is_crash_line') else '   '
                    parts.append(f"  {marker} {line['line_num']}: {line['content']}")

        parts.extend([
            "",
            "请用中文回答，简洁直接。以 JSON 格式返回：",
            '{"root_cause": "...", "crash_type": "...", "fix_suggestion": "...", "confidence": "...", "reasoning": "..."}',
        ])

        return '\n'.join(parts)

    def _call_llm(self, prompt: str) -> str:
        url = f"{self.api_base}/chat/completions"
        payload = json.dumps({
            'model': self.model,
            'messages': [
                {'role': 'system', 'content': '你是 C/C++ 崩溃分析专家，回复 JSON 格式。'},
                {'role': 'user', 'content': prompt},
            ],
            'temperature': 0.3,
            'max_tokens': 1000,
        }).encode('utf-8')

        req = urllib.request.Request(
            url, data=payload,
            headers={
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {self.api_key}',
            },
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read())
            return data['choices'][0]['message']['content']


# ---------------------------------------------------------------------------
# 5. debuginfod online symbol lookup
# ---------------------------------------------------------------------------

class DebuginfodClient:
    """Query debuginfod servers for debug symbols."""

    DEFAULT_SERVERS = [
        'https://debuginfod.ubuntu.com',
        'https://debuginfod.debian.net',
    ]

    def __init__(self, servers: Optional[List[str]] = None):
        self.servers = servers or self.DEFAULT_SERVERS
        # Also check env variable
        env_urls = os.environ.get('DEBUGINFOD_URLS', '')
        if env_urls:
            for u in env_urls.split():
                if u not in self.servers:
                    self.servers.insert(0, u)
        self._cache: Dict[str, Optional[str]] = {}

    def find_debug(self, buildid: str, filetype: str = 'debug') -> Dict:
        """Query debuginfod for a debug file by build-id.

        filetype: 'debug' for separate debug info, 'executable' for the binary.
        Returns {available, path_or_url, server}.
        """
        if not buildid or len(buildid) < 8:
            return {'available': False, 'reason': 'invalid_buildid'}

        bid = buildid.lower().replace('-', '')
        cache_key = f"{bid}:{filetype}"
        if cache_key in self._cache:
            return {'available': bool(self._cache[cache_key]),
                    'path': self._cache[cache_key]}

        # Try each server
        for server in self.servers:
            url = f"{server.rstrip('/')}/{bid}/{filetype}"
            try:
                req = urllib.request.Request(url, method='HEAD')
                req.add_header('User-Agent', 'coredump-analysis/1.0')
                with urllib.request.urlopen(req, timeout=15) as resp:
                    if resp.status == 200:
                        content_url = resp.url  # follow redirects
                        self._cache[cache_key] = content_url
                        return {
                            'available': True,
                            'url': content_url,
                            'server': server,
                        }
            except (urllib.error.HTTPError, urllib.error.URLError,
                    TimeoutError):
                continue
            except Exception:
                continue

        self._cache[cache_key] = None
        return {'available': False, 'reason': 'not_found_on_any_server'}

    def download_debug(self, buildid: str, output_dir: str,
                       filetype: str = 'debug') -> Dict:
        """Download a debug file from debuginfod."""
        result = self.find_debug(buildid, filetype)
        if not result['available']:
            return result

        url = result['url']
        bid = buildid.lower().replace('-', '')[:2]
        rest = buildid.lower().replace('-', '')[2:]
        out_path = os.path.join(output_dir, bid, f"{rest}.debug")
        os.makedirs(os.path.dirname(out_path), exist_ok=True)

        if os.path.exists(out_path):
            result['path'] = out_path
            return result

        try:
            req = urllib.request.Request(url)
            req.add_header('User-Agent', 'coredump-analysis/1.0')
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = resp.read()
                with open(out_path, 'wb') as f:
                    f.write(data)
            result['path'] = out_path
            return result
        except Exception as e:
            return {'available': False, 'reason': str(e)}


# ---------------------------------------------------------------------------
# Orchestrator — coordinates all analysis methods
# ---------------------------------------------------------------------------

class EnhancedAnalyzer:
    """Orchestrates all enhanced analysis methods for a single crash."""

    def __init__(self, workspace: str, package: str, version: str,
                 llm_config: Optional[Dict] = None,
                 max_addr2line_frames: int = 300):
        self.workspace = workspace
        self.package = package
        self.version = version
        self.max_addr2line_frames = max(1, int(max_addr2line_frames or 300))

        ws_path = Path(workspace)
        source_dir = ws_path / '3.代码管理' / package
        self.source_dir = str(source_dir) if source_dir.is_dir() else None

        self.resolver = BinaryResolver(workspace, package)
        self.addr2line = Addr2LineAnalyzer(self.resolver, self.source_dir)
        self.objdump = ObjdumpAnalyzer(self.resolver)
        self.git = GitAnalyzer(self.source_dir)
        self.llm = LLMStackAnalyzer(llm_config)
        self.debuginfod = DebuginfodClient()

    def analyze(self, crash: Dict) -> Dict:
        """Run all enhanced analyses on a single crash record.

        Returns a dict with keys: addr2line, source_context, objdump,
        git_analysis, llm_analysis, debuginfod, improved_fixability.
        """
        result = {}
        degradation_reasons = []

        # Parse frames and compute offsets
        frames = parse_frame_addresses(crash.get('stack_info', ''))
        frames = compute_offsets(frames)
        if not frames:
            degradation_reasons.append('no_parsed_frames')

        # 1. addr2line resolution
        a2l = self.addr2line.resolve_frames(
            frames, max_frames=self.max_addr2line_frames
        )
        result['addr2line'] = a2l

        statuses = [r.get('status') for r in a2l]
        if not a2l:
            degradation_reasons.append('no_addr2line_results')
        if any(status == 'lib_not_found' for status in statuses):
            degradation_reasons.append('library_not_found')
        if any(status == 'no_offset' for status in statuses):
            degradation_reasons.append('missing_frame_offset')
        if any(status == 'timeout' for status in statuses):
            degradation_reasons.append('addr2line_timeout')
        if any(status == 'error' for status in statuses):
            degradation_reasons.append('addr2line_error')
        if any(status == 'unresolved' for status in statuses):
            degradation_reasons.append('addr2line_unresolved')

        # 1b. Source context for resolved frames
        source_contexts = self._collect_source_contexts(a2l, resolved_limit=3, partial_limit=2)
        resolved_frames = [r for r in a2l if r.get('status') == 'ok' and r.get('file')]
        partial_with_src = [r for r in a2l if r.get('status') == 'partial_with_source' and r.get('source_file')]
        result['source_context'] = source_contexts
        if partial_with_src and not any(ctx.get('available') for ctx in source_contexts):
            degradation_reasons.append('source_context_unavailable')
        elif not resolved_frames and not partial_with_src:
            degradation_reasons.append('no_resolved_source_frames')

        # 2. objdump disassembly for key frame
        objdump_result = self._get_objdump_for_crash_frames(crash, frames)
        result['objdump'] = objdump_result
        if crash.get('key_frame') and not objdump_result:
            degradation_reasons.append('objdump_not_available')

        # 3. git blame/log for crash source
        git_results = self._collect_git_results(a2l, max_candidates=2)
        result['git_analysis'] = git_results
        if (resolved_frames or partial_with_src) and not git_results:
            degradation_reasons.append('git_analysis_unavailable')

        deep_dive = None
        deep_dive_reasons = self._get_deep_dive_reasons(crash)
        if deep_dive_reasons:
            deep_dive = self._run_targeted_deep_dive(crash, frames, a2l, deep_dive_reasons)
            if deep_dive.get('performed'):
                result['deep_dive'] = deep_dive
                deep_a2l = deep_dive.get('addr2line', [])
                deep_source_contexts = deep_dive.get('source_context', [])
                deep_git_results = deep_dive.get('git_analysis', [])
                if self._count_usable_frames(deep_a2l) > self._count_usable_frames(a2l):
                    a2l = deep_a2l
                    result['addr2line'] = a2l
                if sum(1 for c in deep_source_contexts if c.get('available')) > sum(1 for c in source_contexts if c.get('available')):
                    source_contexts = deep_source_contexts
                    result['source_context'] = source_contexts
                if len(deep_git_results) > len(git_results):
                    git_results = deep_git_results
                    result['git_analysis'] = git_results
                if deep_dive.get('objdump') and not objdump_result:
                    objdump_result = deep_dive.get('objdump')
                    result['objdump'] = objdump_result
                degradation_reasons.extend(deep_dive.get('degradation_reasons', []))
                if deep_dive.get('performed') and not deep_dive.get('improved'):
                    degradation_reasons.append('deep_dive_no_gain')

        # 5. debuginfod (if we have buildid)
        buildid = crash.get('buildid', '')
        di_result = None
        if buildid:
            di_result = self.debuginfod.find_debug(buildid)
            if not di_result or not di_result.get('available'):
                degradation_reasons.append('debuginfod_unavailable')
        result['debuginfod'] = di_result

        # 4. LLM analysis (only for uncertain crashes)
        llm_result = None
        final_resolved_frames = [r for r in a2l if r.get('status') == 'ok' and r.get('file')]
        final_partial_with_src = [r for r in a2l if r.get('status') == 'partial_with_source' and r.get('source_file')]
        if crash.get('fixable') == 'uncertain' and (final_resolved_frames or final_partial_with_src):
            llm_result = self.llm.analyze(crash, a2l, source_contexts)
            if not llm_result or not llm_result.get('available'):
                degradation_reasons.append('llm_analysis_unavailable')
        result['llm_analysis'] = llm_result

        # Improved fixability assessment based on enhanced data
        result['improved_fixability'] = self._improve_fixability(
            crash, a2l, source_contexts, objdump_result, llm_result
        )
        result['degradation_reasons'] = sorted(set(degradation_reasons))

        return result

    def _count_usable_frames(self, a2l_results: List[Dict]) -> int:
        return sum(1 for r in a2l_results if r.get('status') in ('ok', 'partial_with_source'))

    def _collect_source_contexts(self, a2l_results: List[Dict], resolved_limit: int = 3,
                                 partial_limit: int = 2) -> List[Dict]:
        source_contexts = []
        resolved_frames = [r for r in a2l_results if r.get('status') == 'ok' and r.get('file')]
        partial_with_src = [r for r in a2l_results if r.get('status') == 'partial_with_source' and r.get('source_file')]
        for r in resolved_frames[:resolved_limit]:
            ctx = self.addr2line.get_source_context(r['file'], r['line'])
            source_contexts.append(ctx)
        for r in partial_with_src[:partial_limit]:
            ctx = self._get_partial_source_context(r)
            source_contexts.append(ctx)
        return source_contexts

    def _collect_git_results(self, a2l_results: List[Dict], max_candidates: int = 2) -> List[Dict]:
        git_results = []
        resolved_frames = [r for r in a2l_results if r.get('status') == 'ok' and r.get('file')]
        partial_with_src = [r for r in a2l_results if r.get('status') == 'partial_with_source' and r.get('source_file')]
        for r in (resolved_frames + partial_with_src)[:max_candidates]:
            file_path = r.get('file') or r.get('source_file')
            line = r.get('line')
            if not file_path or not line:
                if r.get('source_file') and r.get('function'):
                    found_line = self._find_function_line(r['source_file'], r['function'])
                    if found_line:
                        file_path = r['source_file']
                        line = found_line
            if file_path and line:
                blame = self.git.blame(file_path, line)
                log = self.git.log(file_path, max_commits=5)
                git_results.append({
                    'file': file_path,
                    'line': line,
                    'blame': blame,
                    'log': log,
                })
        return git_results

    def _get_objdump_for_crash_frames(self, crash: Dict, frames: List[Dict]):
        key_frame = crash.get('key_frame')
        if not key_frame:
            return None
        prioritized = []
        key_library = key_frame.get('library', '')
        if key_library:
            prioritized.extend([
                f for f in frames
                if f.get('library') == key_library or key_library in f.get('library', '')
            ])
        prioritized.extend(frames)
        seen = set()
        for f in prioritized:
            frame_key = (f.get('address'), f.get('library'), f.get('offset'))
            if frame_key in seen:
                continue
            seen.add(frame_key)
            lib = f.get('library', '')
            if f.get('offset') is not None and lib:
                result = self.objdump.disassemble_around(lib, f['offset'])
                if result and result.get('available'):
                    return result
        return None

    def _prioritize_frames_for_deep_dive(self, crash: Dict, frames: List[Dict]) -> List[Dict]:
        prioritized = []
        key_frame = crash.get('key_frame') or {}
        key_library = key_frame.get('library', '')
        key_symbol = (key_frame.get('symbol') or '').lower()
        app_symbol = (crash.get('app_layer_symbol') or '').lower()

        if key_library:
            prioritized.extend([
                f for f in frames
                if f.get('library') == key_library or key_library in f.get('library', '')
            ])
        if key_symbol:
            prioritized.extend([
                f for f in frames
                if key_symbol and key_symbol in (f.get('symbol') or '').lower()
            ])
        if app_symbol:
            prioritized.extend([
                f for f in frames
                if app_symbol and app_symbol in (f.get('symbol') or '').lower()
            ])
        prioritized.extend(frames)

        unique = []
        seen = set()
        for f in prioritized:
            frame_key = (f.get('address'), f.get('library'), f.get('offset'))
            if frame_key in seen:
                continue
            seen.add(frame_key)
            unique.append(f)
        return unique

    def _has_app_layer_signal(self, crash: Dict) -> bool:
        app_symbol = (crash.get('app_layer_symbol') or '').strip().lower()
        if app_symbol and app_symbol not in {'n/a', 'unknown'}:
            return True
        key_frame = crash.get('key_frame') or {}
        key_symbol = (key_frame.get('symbol') or '').strip().lower()
        key_library = (key_frame.get('library') or '').strip().lower()
        package_name = (self.package or '').strip().lower()
        if key_symbol and key_symbol not in {'n/a', 'unknown'} and package_name and package_name in key_symbol:
            return True
        if key_library and package_name and package_name in key_library:
            return True
        return False

    def _get_deep_dive_reasons(self, crash: Dict) -> List[str]:
        reasons = []
        if crash.get('fixable') == 'uncertain':
            reasons.append('uncertain_fixability')
        if self._has_app_layer_signal(crash):
            reasons.append('app_layer_signal')
        try:
            if int(crash.get('count') or 0) >= 3:
                reasons.append('high_frequency')
        except (TypeError, ValueError):
            pass
        return reasons

    def _run_targeted_deep_dive(self, crash: Dict, frames: List[Dict], base_a2l: List[Dict], reasons: List[str]) -> Dict:
        deep_limit = max(self.max_addr2line_frames * 2, 200)
        prioritized_frames = self._prioritize_frames_for_deep_dive(crash, frames)
        deep_a2l = self.addr2line.resolve_frames(prioritized_frames, max_frames=deep_limit)
        deep_source_contexts = self._collect_source_contexts(
            deep_a2l, resolved_limit=5, partial_limit=5
        )
        deep_git_results = self._collect_git_results(deep_a2l, max_candidates=5)
        deep_objdump = self._get_objdump_for_crash_frames(crash, prioritized_frames)
        improved = (
            self._count_usable_frames(deep_a2l) > self._count_usable_frames(base_a2l)
            or sum(1 for c in deep_source_contexts if c.get('available')) > 0
            or len(deep_git_results) > 0
            or bool(deep_objdump and deep_objdump.get('available'))
        )
        degradation_reasons = []
        if not improved:
            degradation_reasons.append('deep_dive_exhausted')
        return {
            'performed': True,
            'reasons': reasons,
            'frame_limit': deep_limit,
            'improved': improved,
            'addr2line': deep_a2l,
            'source_context': deep_source_contexts,
            'git_analysis': deep_git_results,
            'objdump': deep_objdump,
            'degradation_reasons': degradation_reasons,
        }

    def _get_partial_source_context(self, frame_result: Dict) -> Dict:
        """Get source context for a partially resolved frame (function name, no line)."""
        source_file = frame_result.get('source_file')
        function = frame_result.get('function')
        if not source_file or not function:
            return {'available': False, 'reason': 'no source file'}

        # Find the function definition line
        line = self._find_function_line(source_file, function)
        if not line:
            # Just read the beginning of the file
            return self.addr2line.get_source_context(source_file, 1, context_lines=15)

        return self.addr2line.get_source_context(source_file, line, context_lines=10)

    def _find_function_line(self, rel_file: str, mangled_name: str) -> Optional[int]:
        """Find the line number of a function definition in a source file."""
        if not self.source_dir or not rel_file:
            return None
        full_path = Path(self.source_dir) / rel_file
        if not full_path.exists():
            return None

        # Demangle and extract class/function name
        demangled = self.addr2line._demangle(mangled_name)
        parts = demangled.split('::')
        # Use last two parts: class::method
        if len(parts) >= 2:
            class_name = parts[-2].split('<')[0].strip()
            method_name = parts[-1].split('(')[0].strip()
            search = f'{class_name}::{method_name}'
        elif len(parts) == 1:
            search = parts[0].split('(')[0].strip()
        else:
            return None

        try:
            with open(full_path, 'r', encoding='utf-8', errors='replace') as f:
                for i, line in enumerate(f, 1):
                    if search in line:
                        return i
        except Exception:
            pass
        return None

    def _improve_fixability(self, crash, a2l, source_ctxs, objdump_r, llm_r):
        """Use enhanced data to improve the fixability assessment."""
        improvements = {}

        resolved_count = sum(1 for r in a2l if r.get('status') == 'ok')
        partial_source_count = sum(1 for r in a2l if r.get('status') == 'partial_with_source')
        usable_source_count = resolved_count + partial_source_count
        if usable_source_count == 0:
            improvements['resolved'] = False
            improvements['usable_source_frames'] = 0
            return improvements

        improvements['resolved'] = True
        improvements['resolved_frame_count'] = resolved_count
        improvements['partial_source_frame_count'] = partial_source_count
        improvements['usable_source_frames'] = usable_source_count

        # Check if source context reveals common patterns
        crash_type = None
        for ctx in source_ctxs:
            if not ctx.get('available'):
                continue
            code_text = ' '.join(
                line['content'] for line in ctx.get('context', [])
            ).lower()
            if crash_type is None:
                if any(p in code_text for p in ['nullptr', 'null', '->']):
                    crash_type = 'null_deref'
                elif 'delete' in code_text and 'new' in code_text:
                    crash_type = 'use_after_free'
                elif any(p in code_text for p in ['[', ']', 'at(', 'size']):
                    crash_type = 'buffer_overflow'

        if crash_type:
            improvements['detected_crash_type'] = crash_type

        # LLM analysis override
        if llm_r and llm_r.get('available'):
            try:
                llm_data = json.loads(llm_r['analysis'])
                if llm_data.get('confidence') in ('high', 'medium'):
                    improvements['llm_suggested_fix'] = llm_data.get('fix_suggestion')
                    improvements['llm_confidence'] = llm_data.get('confidence')
            except (json.JSONDecodeError, TypeError):
                pass

        # Git blame — recently changed crash line is more likely fixable
        for gr in (source_ctxs if source_ctxs else []):
            if not gr.get('available'):
                continue
            # git_results is separate, check via blame
            pass

        return improvements


# ---------------------------------------------------------------------------
# Batch analysis helper — run enhanced analysis for all crashes in a version
# ---------------------------------------------------------------------------

def run_enhanced_analysis_for_version(
    crashes: List[Dict],
    workspace: str,
    package: str,
    version: str,
    llm_config: Optional[Dict] = None,
    max_crashes: int = 0,
    max_addr2line_frames: int = 300,
) -> Tuple[List[Dict], Dict]:
    """Run enhanced analysis on all crashes.

    Returns (enhanced_results_list, summary_stats).
    Each element of enhanced_results_list corresponds to the input crashes list.
    """
    analyzer = EnhancedAnalyzer(
        workspace,
        package,
        version,
        llm_config,
        max_addr2line_frames=max_addr2line_frames,
    )

    targets = crashes if max_crashes <= 0 else crashes[:max_crashes]
    results = []

    stats = {
        'total': len(targets),
        'addr2line_resolved': 0,
        'addr2line_partial': 0,
        'source_found': 0,
        'git_available': 0,
        'objdump_available': 0,
        'llm_analyzed': 0,
        'fixability_improved': 0,
    }

    for crash in targets:
        try:
            enhanced = analyzer.analyze(crash)
            results.append(enhanced)

            # Stats
            for r in enhanced.get('addr2line', []):
                if r.get('status') == 'ok':
                    stats['addr2line_resolved'] += 1
                elif r.get('status') in ('partial', 'partial_with_source'):
                    stats['addr2line_partial'] += 1
            if any(c.get('available') for c in enhanced.get('source_context', [])):
                stats['source_found'] += 1
            if any(g.get('blame', {}).get('available') or g.get('log', {}).get('available')
                   for g in enhanced.get('git_analysis', [])):
                stats['git_available'] += 1
            objdump_info = enhanced.get('objdump') or {}
            if objdump_info.get('available'):
                stats['objdump_available'] += 1
            llm_info = enhanced.get('llm_analysis') or {}
            if llm_info.get('available'):
                stats['llm_analyzed'] += 1
            fixability_info = enhanced.get('improved_fixability') or {}
            if fixability_info.get('resolved'):
                stats['fixability_improved'] += 1
        except Exception as e:
            logger.warning(f"Enhanced analysis failed for crash: {e}")
            results.append({'error': str(e)})

    return results, stats
