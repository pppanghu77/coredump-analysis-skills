#!/usr/bin/env python3
"""
版本特定崩溃分析脚本
分析指定版本的崩溃数据，生成修复建议
"""

import csv
import json
import re
import sys
import argparse
from pathlib import Path
from typing import Dict, List, Tuple
from datetime import datetime

from package_rules import get_package_patterns

# Import enhanced analysis module
try:
    from enhanced_analysis import (
        EnhancedAnalyzer, run_enhanced_analysis_for_version,
        parse_frame_addresses, compute_offsets,
    )
    HAS_ENHANCED = True
except ImportError:
    HAS_ENHANCED = False


def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description='分析指定版本的崩溃数据',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
示例:
  python3 analyze_crash_per_version.py --package dde-session-ui --version 1:5.9.6-1 --workspace /path/to/workspace
  python3 analyze_crash_per_version.py --package dde-session-ui --version 5.8.32 --workspace /path --output output.json
        '''
    )
    parser.add_argument(
        '--package',
        required=True,
        help='包名'
    )
    parser.add_argument(
        '--version',
        required=True,
        help='版本号'
    )
    parser.add_argument(
        '--workspace',
        required=True,
        help='工作目录'
    )
    parser.add_argument(
        '--output',
        help='输出JSON文件路径（默认: workspace/5.崩溃分析/X_X_X/analysis.json）'
    )
    parser.add_argument(
        '--max-crashes',
        type=int,
        default=0,
        help='最大分析崩溃数量（默认: 0，表示分析全部）'
    )
    parser.add_argument(
        '--addr2line-max-frames',
        type=int,
        default=100,
        help='addr2line 最大解析帧数（默认: 100）'
    )

    return parser.parse_args()


def clean_version(version: str) -> str:
    """清理版本号"""
    version = re.sub(r'^1:', '', version)
    version = re.sub(r'-\d+$', '', version)
    return version


def parse_stack_info(stack_info: str) -> List[Dict]:
    """解析堆栈信息"""
    if not stack_info or not stack_info.strip():
        return []

    frames = []
    lines = stack_info.strip().split('\n')

    for line in lines:
        # 匹配: #0 0x000055c65fa3409b symbol (library)
        match = re.match(r'\s*#\s*\d+\s+0x[0-9a-f]+\s+(\S+|n/a)\s+\(([^)]*)\)', line)
        if match:
            frames.append({
                'symbol': match.group(1),
                'library': match.group(2)
            })

    return frames


def find_app_layer_symbol(frames: List[Dict], package: str) -> Tuple[Dict, int]:
    """找到应用层的关键帧"""
    system_libs = ['libc.so.6', 'libpthread.so.0', 'libstdc++.so.6', 'ld-linux', 'libm.so.6',
                   'libglib-2.0.so.0', 'libgobject-2.0.so.0', 'libgio-2.0.so.0']

    package_keywords = [kw for kw in package.split('-') if kw]
    package_keywords.append(package)

    for i, frame in enumerate(frames):
        library = frame['library'].lower()
        symbol = frame['symbol']

        # 检查是否为系统库
        if any(sys_lib in library for sys_lib in system_libs):
            continue

        # 检查是否为应用层代码
        for keyword in package_keywords:
            keyword = keyword.lower()
            if keyword in library or keyword in symbol.lower():
                return frame, i

    # 回退: 选择第一个非系统库帧
    for i, frame in enumerate(frames):
        library = frame['library'].lower()
        symbol = frame['symbol'].lower()
        if symbol == 'n/a' and ('n/a' == library or 'n/a + 0x0' in library):
            continue
        if not any(sys_lib in library for sys_lib in system_libs):
            return frame, i

    return frames[0] if frames else {}, 0


def assess_fixability(crash_data: Dict) -> Dict:
    """评估崩溃是否可修复"""
    crash_desc = crash_data.get('description', '').lower()

    # 可修复的模式
    fixable_patterns = {
        'null pointer': {
            'fixable': True,
            'reason': '空指针解引用',
            'fix_type': '添加空指针检查',
            'fix_code': 'if (ptr) { ptr->method(); }',
            'confidence': 'high'
        },
        'use after free': {
            'fixable': True,
            'reason': '释放后使用',
            'fix_type': '使用智能指针或置NULL',
            'fix_code': 'delete ptr; ptr = nullptr;',
            'confidence': 'high'
        },
        'buffer overflow': {
            'fixable': True,
            'reason': '缓冲区溢出',
            'fix_type': '添加边界检查',
            'fix_code': 'if (index < size) { array[index] = value; }',
            'confidence': 'high'
        },
        'uninitialized variable': {
            'fixable': True,
            'reason': '未初始化变量',
            'fix_type': '初始化变量',
            'fix_code': 'Type var = initial_value;',
            'confidence': 'high'
        },
        'divide by zero': {
            'fixable': True,
            'reason': '除零',
            'fix_type': '添加除零检查',
            'fix_code': 'if (denominator != 0) { result = numerator / denominator; }',
            'confidence': 'high'
        },
        'assertion failed': {
            'fixable': True,
            'reason': '断言失败',
            'fix_type': '修复断言条件或添加错误处理',
            'fix_code': 'if (!condition) { handle_error(); }',
            'confidence': 'medium'
        },
    }

    # 不可修复的模式
    non_fixable_patterns = {
        'qt internal': {
            'fixable': False,
            'reason': 'Qt内部库崩溃',
            'confidence': 'high'
        },
        'gdk error': {
            'fixable': False,
            'reason': 'GDK图形库错误',
            'confidence': 'high'
        },
        'dbus timeout': {
            'fixable': False,
            'reason': 'D-Bus超时，需要异步处理',
            'confidence': 'medium'
        },
        'signal handler': {
            'fixable': False,
            'reason': '信号处理相关的系统调用',
            'confidence': 'medium'
        },
    }

    # 检查是否可修复
    for pattern, info in fixable_patterns.items():
        if pattern in crash_desc:
            return info

    # 检查是否不可修复
    for pattern, info in non_fixable_patterns.items():
        if pattern in crash_desc:
            # 确保没有可修复的模式
            has_fixable = any(fp in crash_desc for fp in fixable_patterns.keys())
            if not has_fixable:
                return info

    # 不确定
    return {
        'fixable': 'uncertain',
        'reason': '需要人工判断',
        'fix_type': None,
        'fix_code': None,
        'confidence': 'low'
    }


def infer_crash_pattern(crash: Dict, package: str) -> Dict:
    """根据堆栈模式推断更具体的根因类别"""
    frames = crash.get('frames', [])
    text = ' | '.join(f"{f.get('library', '')}:{f.get('symbol', '')}" for f in frames[:8]).lower()
    key_frame = crash.get('key_frame') or {}
    key_symbol = (key_frame.get('symbol') or '').lower()
    key_library = (key_frame.get('library') or '').lower()

    patterns = get_package_patterns(package)

    for pattern in patterns:
        if all(token in text for token in pattern['match']):
            return pattern

    if text.count('n/a + 0x0') >= 2 or text.count('n/a:n/a') >= 2 or text.strip() in {'n/a:n/a', 'n/a + 0x0:n/a | n/a + 0x0:n/a'}:
        return {
            'name': 'opaque_no_symbols',
            'fixable': 'uncertain',
            'reason': '堆栈缺少可用符号，需原始 coredump 或更完整调试符号',
            'fix_type': None,
            'fix_code': None,
            'confidence': 'low',
        }

    if package.lower() in key_library or package.lower() in key_symbol:
        return {
            'name': 'app_frame_detected',
            'fixable': True,
            'reason': '已命中应用层关键帧，可继续结合源码定位',
            'fix_type': '优先分析应用层关键帧附近代码',
            'fix_code': None,
            'confidence': 'low',
        }

    return {
        'name': 'unknown',
        'fixable': 'uncertain',
        'reason': '需要人工判断',
        'fix_type': None,
        'fix_code': None,
        'confidence': 'low',
    }


def analyze_crash(row: Dict, package: str) -> Dict:
    """分析单个崩溃"""
    crash = {
        'id': row.get('ID', ''),
        'date': row.get('Dt', row.get('Date', '')),
        'count': int(row.get('Count', 1)),
        'signal': row.get('Sig', ''),
        'exe': row.get('Exe', ''),
        'stack_info': row.get('StackInfo', ''),
        'app_layer_library': row.get('App_Layer_Library', ''),
        'app_layer_symbol': row.get('App_Layer_Symbol', ''),
        'sys_v_number': row.get('Sys V Number', row.get('Sys_V_Number', '')),
        'buildid': row.get('Buildid', ''),
    }

    # 信号类型分析
    if crash['signal'] == 'SIGSEGV':
        crash['signal_desc'] = '段错误 - 非法内存访问'
    elif crash['signal'] == 'SIGABRT':
        crash['signal_desc'] = '主动终止 - 检测到严重错误'
    elif crash['signal'] == 'SIGBUS':
        crash['signal_desc'] = '总线错误 - 内存对齐问题'
    elif crash['signal'] == 'SIGFPE':
        crash['signal_desc'] = '浮点异常 - 除零或溢出'
    else:
        crash['signal_desc'] = f'未知信号: {crash["signal"]}'

    # 解析堆栈
    frames = parse_stack_info(crash['stack_info'])
    crash['frames'] = frames

    # 找到应用层关键帧
    if frames:
        key_frame, frame_index = find_app_layer_symbol(frames, package)
        crash['key_frame'] = {
            'index': frame_index,
            'symbol': key_frame.get('symbol', 'n/a'),
            'library': key_frame.get('library', 'n/a')
        }
    else:
        crash['key_frame'] = None

    # 评估可修复性
    description = f"{crash['signal']} {crash['app_layer_symbol']} {crash['key_frame']['symbol'] if crash['key_frame'] else ''}"
    crash['description'] = description

    fix_assessment = assess_fixability(crash)
    pattern_assessment = infer_crash_pattern(crash, package)
    if fix_assessment['fixable'] == 'uncertain' and pattern_assessment['fixable'] != 'uncertain':
        fix_assessment = pattern_assessment

    crash['fixable'] = fix_assessment['fixable']
    crash['fix_reason'] = fix_assessment['reason']
    crash['fix_type'] = fix_assessment.get('fix_type')
    crash['fix_code'] = fix_assessment.get('fix_code')
    crash['fix_confidence'] = fix_assessment['confidence']
    crash['pattern_name'] = pattern_assessment.get('name', 'unknown')

    return crash


def generate_gdb_commands(crash: Dict) -> List[str]:
    """生成GDB调试命令"""
    commands = []

    if crash['exe']:
        commands.append(f"gdb {crash['exe']} -c <coredump_file>")

    if crash['key_frame']:
        commands.append("(gdb) bt full")
        commands.append(f"(gdb) frame {crash['key_frame']['index']}")
        commands.append("(gdb) info locals")
        commands.append("(gdb) info args")

    return commands


def generate_addr2line_commands(crash: Dict) -> List[str]:
    """生成 addr2line 调试命令"""
    commands = []
    buildid = crash.get('buildid', '')
    if buildid and len(buildid) > 2:
        debug_file = f"/usr/lib/debug/.build-id/{buildid[:2]}/{buildid[2:]}.debug"
        commands.append(f"file {debug_file}")
        commands.append(f"eu-addr2line -e {debug_file} <crash-address>")
    return commands


def generate_fix_suggestions(crash: Dict, package: str, version: str) -> List[str]:
    """生成修复建议"""
    suggestions = []

    if crash['signal'] == 'SIGSEGV':
        suggestions.append("1. 添加空指针检查: if (obj) { obj->method(); }")
        suggestions.append("2. 使用智能指针避免野指针")
        suggestions.append("3. 数组访问前检查边界")
    elif crash['signal'] == 'SIGABRT':
        suggestions.append("1. 检查失败的assert，定位原因")
        suggestions.append("2. 确保内存分配后的错误处理")
        suggestions.append("3. 添加try-catch捕获异常")
    elif crash['signal'] == 'SIGBUS':
        suggestions.append("1. 检查内存对齐问题")
        suggestions.append("2. 使用aligned属性")
    elif crash['signal'] == 'SIGFPE':
        suggestions.append("1. 添加除零检查")
        suggestions.append("2. 使用安全运算函数")

    if crash['fixable'] is True:
        suggestions.append(f"5. 建议修复方式: {crash['fix_type']}")
        if crash['fix_code']:
            suggestions.append(f"   示例代码: {crash['fix_code']}")

    return suggestions


def analyze_version(package: str, version: str, workspace: str, max_crashes: int, addr2line_max_frames: int) -> Dict:
    """分析指定版本的所有崩溃"""
    version_clean = clean_version(version)
    version_dir = version_clean.replace('.', '_').replace('+', '_').replace('-', '_')

    # 读取筛选后的数据
    filtered_csv = Path(workspace) / '2.数据筛选' / f'filtered_{package}_crash_data.csv'

    if not filtered_csv.exists():
        return {
            'package': package,
            'version': version,
            'version_clean': version_clean,
            'error': '筛选数据文件不存在'
        }

    # 读取统计数据
    stats_json = Path(workspace) / '2.数据筛选' / f'{package}_crash_statistics.json'
    version_stats = {}
    if stats_json.exists():
        with open(stats_json, 'r', encoding='utf-8') as f:
            stats = json.load(f)
            version_stats = stats.get('by_version', {}).get(version, {})

    # 读取崩溃数据
    crashes = []
    total_crash_count = 0

    with open(filtered_csv, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)

        for row in reader:
            row_version = row.get('Version', '')

            # 匹配版本号
            if row_version == version or row_version.replace(':1', '') == version or \
               row_version.replace('-1', '') == version or \
               clean_version(row_version) == version_clean:

                crash = analyze_crash(row, package)
                crashes.append(crash)
                total_crash_count += crash['count']

    # 限制分析的崩溃数量
    analyzed_crashes = crashes if max_crashes <= 0 else crashes[:max_crashes]

    # ═══════════════════════════════════════════════════════════════════
    # 增强分析: addr2line + objdump + git blame + LLM + debuginfod
    # ═══════════════════════════════════════════════════════════════════
    enhanced_stats = {}
    if HAS_ENHANCED:
        print(f"🔧 运行增强分析 (addr2line / objdump / git blame / LLM / debuginfod) ...")
        enhanced_results, enhanced_stats = run_enhanced_analysis_for_version(
            analyzed_crashes, workspace, package, version_clean,
            max_addr2line_frames=addr2line_max_frames,
        )
        # Attach enhanced results to each crash
        for crash, enhanced in zip(analyzed_crashes, enhanced_results):
            crash['enhanced'] = enhanced
            if enhanced.get('degradation_reasons'):
                crash['enhanced_degradation_reasons'] = enhanced['degradation_reasons']

            # Use enhanced data to improve fixability assessment
            improvement = enhanced.get('improved_fixability', {})
            if improvement.get('resolved'):
                # If addr2line resolved source, upgrade confidence
                if crash.get('fix_confidence') == 'low' and crash.get('fixable') == 'uncertain':
                    detected_type = improvement.get('detected_crash_type')
                    if detected_type:
                        type_map = {
                            'null_deref': ('空指针解引用', '添加空指针检查', 'if (ptr) { ptr->method(); }'),
                            'use_after_free': ('释放后使用', '使用智能指针或置NULL', 'delete ptr; ptr = nullptr;'),
                            'buffer_overflow': ('缓冲区溢出', '添加边界检查', 'if (index < size) { array[index] = value; }'),
                        }
                        if detected_type in type_map:
                            reason, fix_type, fix_code = type_map[detected_type]
                            crash['fixable'] = True
                            crash['fix_reason'] = reason
                            crash['fix_type'] = fix_type
                            crash['fix_code'] = fix_code
                            crash['fix_confidence'] = 'medium'
                            crash['pattern_name'] = f'enhanced_{detected_type}'

                # LLM suggestion override
                llm_fix = improvement.get('llm_suggested_fix')
                llm_conf = improvement.get('llm_confidence')
                if llm_fix and llm_conf in ('high', 'medium'):
                    crash['llm_suggested_fix'] = llm_fix
                    crash['llm_confidence'] = llm_conf

        # Recount after improvements
        total_fixable = sum(1 for c in analyzed_crashes if c['fixable'] is True)
        total_non_fixable = sum(1 for c in analyzed_crashes if c['fixable'] is False)
        total_uncertain = sum(1 for c in analyzed_crashes if c['fixable'] == 'uncertain')

    # 按信号类型统计
    signal_counts = {}
    for crash in analyzed_crashes:
        sig = crash['signal']
        signal_counts[sig] = signal_counts.get(sig, 0) + crash['count']

    # 按应用层符号统计
    symbol_counts = {}
    for crash in analyzed_crashes:
        symbol = crash['app_layer_symbol'] or crash['key_frame']['symbol'] if crash['key_frame'] else 'unknown'
        symbol_counts[symbol] = symbol_counts.get(symbol, 0) + crash['count']

    # 生成报告
    result = {
        'package': package,
        'version': version,
        'version_clean': version_clean,
        'version_dir': version_dir,
        'analysis_time': datetime.now().isoformat(),
        'version_stats': version_stats,
        'summary': {
            'total_crash_types': len(analyzed_crashes),
            'total_crash_records': sum(c['count'] for c in analyzed_crashes),
            'unique_crashes': len(analyzed_crashes),
            'fixable_count': total_fixable,
            'non_fixable_count': total_non_fixable,
            'uncertain_count': total_uncertain,
            'fix_rate': f"{(total_fixable / len(analyzed_crashes) * 100):.1f}%" if analyzed_crashes else "0%"
        },
        'by_signal': signal_counts,
        'by_symbol': symbol_counts,
        'crashes': analyzed_crashes,
        'recommendations': [],
        'enhanced_stats': enhanced_stats if HAS_ENHANCED else {},
        'deep_dive_stats': {
            'performed': sum(1 for c in analyzed_crashes if c.get('enhanced', {}).get('deep_dive', {}).get('performed')),
            'improved': sum(1 for c in analyzed_crashes if c.get('enhanced', {}).get('deep_dive', {}).get('improved')),
        } if HAS_ENHANCED else {},
    }

    # 生成总体建议
    if total_fixable > 0:
        result['recommendations'].append(f"检测到 {total_fixable} 个可修复的崩溃，建议优先处理")

    if signal_counts.get('SIGSEGV', 0) > 0:
        result['recommendations'].append(f"SIGSEGV崩溃占比较高，建议检查空指针和内存管理")

    if signal_counts.get('SIGABRT', 0) > 0:
        result['recommendations'].append(f"SIGABRT崩溃，建议检查assert和异常处理")

    return result


def save_markdown_report(analysis: Dict, output_file: Path):
    """保存Markdown格式的报告"""
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(f"# {analysis['package']} 版本 {analysis['version']} 崩溃分析报告\n\n")
        f.write(f"**分析时间**: {analysis['analysis_time']}\n\n")
        f.write(f"**包名**: {analysis['package']}\n\n")
        f.write(f"**版本**: {analysis['version']}\n\n")

        # 摘要
        f.write("## 摘要\n\n")
        f.write(f"- 唯一崩溃数: {analysis['summary']['unique_crashes']}\n")
        f.write(f"- 总崩溃记录数: {analysis['summary']['total_crash_records']}\n")
        f.write(f"- 可修复崩溃: {analysis['summary']['fixable_count']}\n")
        f.write(f"- 不可修复崩溃: {analysis['summary']['non_fixable_count']}\n")
        f.write(f"- 需人工判断: {analysis['summary']['uncertain_count']}\n")
        f.write(f"- 修复率: {analysis['summary']['fix_rate']}\n\n")

        # 增强分析统计
        estats = analysis.get('enhanced_stats', {})
        if estats:
            f.write("**增强分析**:\n")
            f.write(f"- addr2line 完全解析: {estats.get('addr2line_resolved', 0)}\n")
            f.write(f"- addr2line 部分解析(函数名): {estats.get('addr2line_partial', 0)}\n")
            f.write(f"- 源码上下文获取: {estats.get('source_found', 0)}\n")
            f.write(f"- Git Blame/Log: {estats.get('git_available', 0)}\n")
            f.write(f"- objdump 反汇编: {estats.get('objdump_available', 0)}\n")
            f.write(f"- LLM 分析: {estats.get('llm_analyzed', 0)}\n")
            f.write(f"- 可修复性提升: {estats.get('fixability_improved', 0)}\n")
            dstats = analysis.get('deep_dive_stats', {})
            if dstats:
                f.write(f"- uncertain 二次深挖: {dstats.get('performed', 0)}\n")
                f.write(f"- 深挖取得增益: {dstats.get('improved', 0)}\n")
            f.write("\n")

        # 按信号类型统计
        f.write("## 按信号类型统计\n\n")
        f.write("| 信号类型 | 次数 | 说明 |\n")
        f.write("|---------|------|------|\n")
        signal_desc_map = {
            'SIGSEGV': '段错误',
            'SIGABRT': '主动终止',
            'SIGBUS': '总线错误',
            'SIGFPE': '浮点异常'
        }
        for sig, count in sorted(analysis['by_signal'].items(), key=lambda x: -x[1]):
            desc = signal_desc_map.get(sig, sig)
            f.write(f"| {sig} | {count} | {desc} |\n")
        f.write("\n")

        # 崩溃详情
        f.write("## 崩溃详情\n\n")
        f.write(f"共分析 {analysis['summary']['unique_crashes']} 个唯一崩溃:\n\n")

        for i, crash in enumerate(analysis['crashes'], 1):
            f.write(f"### 崩溃 #{i}\n\n")
            f.write(f"- **ID**: {crash['id'][:50]}...\n")
            f.write(f"- **次数**: {crash['count']}\n")
            f.write(f"- **信号**: {crash['signal']} ({crash['signal_desc']})\n")
            f.write(f"- **应用层函数**: {crash['app_layer_symbol'] or 'N/A'}\n")
            f.write(f"- **可修复**: {'是' if crash['fixable'] is True else '否' if crash['fixable'] is False else '不确定'}\n")

            if crash['fixable'] is True:
                f.write(f"- **修复建议**: {crash['fix_reason']}\n")
                if crash['fix_type']:
                    f.write(f"- **修复方式**: {crash['fix_type']}\n")
                if crash['fix_code']:
                    f.write(f"- **示例代码**: `{crash['fix_code']}`\n")
            elif crash['fixable'] is False:
                f.write(f"- **原因**: {crash['fix_reason']}\n")
            elif crash['fixable'] == 'uncertain':
                f.write(f"- **说明**: 需要人工判断\n")

            if crash['key_frame']:
                f.write(f"- **关键帧**: 帧 #{crash['key_frame']['index']} `{crash['key_frame']['symbol']}` in `{crash['key_frame']['library']}`\n")

            # GDB命令
            gdb_cmds = generate_gdb_commands(crash)
            if gdb_cmds:
                f.write(f"\n**调试命令**:\n```bash\n")
                for cmd in gdb_cmds:
                    f.write(f"{cmd}\n")
                f.write("```\n")

            addr2line_cmds = generate_addr2line_commands(crash)
            if addr2line_cmds:
                f.write(f"\n**addr2line 命令**:\n```bash\n")
                for cmd in addr2line_cmds:
                    f.write(f"{cmd}\n")
                f.write("```\n")

            # ═══ Enhanced analysis results ═══
            enhanced = crash.get('enhanced', {})
            if enhanced and not enhanced.get('error'):
                # addr2line resolved frames
                a2l_results = enhanced.get('addr2line', [])
                resolved = [r for r in a2l_results if r.get('status') == 'ok']
                partial = [r for r in a2l_results if r.get('status') in ('partial', 'partial_with_source')]
                if resolved or partial:
                    total = len(a2l_results)
                    f.write(f"\n**addr2line 解析** (完全解析 {len(resolved)}/{total}, 部分解析 {len(partial)}/{total}):\n")
                    for r in resolved[:8]:
                        func = r.get('function') or '?'
                        fpath = r.get('file') or '?'
                        fline = r.get('line') or '?'
                        lib = r.get('library') or '?'
                        f.write(f"  - `{func}` at {fpath}:{fline} [{lib}]\n")
                    for r in partial[:8]:
                        func = r.get('function') or '?'
                        src = r.get('source_file', '')
                        lib = r.get('library') or '?'
                        extra = f" → 源码: {src}" if src else ""
                        f.write(f"  - ~`{func}` [{lib}]{extra}\n")

                # Source context
                src_ctxs = enhanced.get('source_context', [])
                for ctx in src_ctxs[:2]:
                    if ctx.get('available'):
                        f.write(f"\n**源码上下文**: `{ctx.get('display_file', '?')}:{ctx.get('line', '?')}`\n")
                        f.write("```cpp\n")
                        for cl in ctx.get('context', []):
                            marker = '>>>' if cl.get('is_crash_line') else '   '
                            f.write(f"{marker} {cl['line_num']:>4}: {cl['content']}\n")
                        f.write("```\n")

                # objdump disassembly
                objdump_r = enhanced.get('objdump')
                if objdump_r and objdump_r.get('available'):
                    f.write(f"\n**反汇编** (offset {objdump_r['offset']} in {objdump_r['library']}):\n")
                    f.write("```asm\n")
                    for line in (objdump_r.get('instructions') or [])[:25]:
                        f.write(f"{line}\n")
                    f.write("```\n")

                # git blame / log
                git_results = enhanced.get('git_analysis', [])
                for gr in git_results[:1]:
                    blame = gr.get('blame', {})
                    if blame.get('available'):
                        f.write(f"\n**Git Blame**: `{gr.get('file')}:{gr.get('line')}`\n")
                        for entry in blame.get('entries', []):
                            marker = ">>>" if entry.get('is_crash_line') else "   "
                            f.write(
                                f"  {marker} {entry.get('commit','?')[:8]} "
                                f"{entry.get('author','?')} ({entry.get('date','?')}) "
                                f"L{entry.get('line','?')}: {entry.get('code','')}\n"
                            )
                    log = gr.get('log', {})
                    if log.get('available'):
                        f.write(f"\n**最近提交**: `{gr.get('file')}`\n")
                        for c in log.get('commits', [])[:5]:
                            f.write(f"  - {c.get('hash','?')} {c.get('date','?')} {c.get('author','?')} {c.get('message','')}\n")

                # LLM analysis
                llm_r = enhanced.get('llm_analysis')
                if llm_r and llm_r.get('available'):
                    f.write(f"\n**LLM 崩溃分析** (model: {llm_r.get('model', '?')}):\n")
                    f.write(f"```\n{llm_r.get('analysis', '')}\n```\n")

                # debuginfod
                di_r = enhanced.get('debuginfod')
                if di_r and di_r.get('available'):
                    f.write(f"\n**debuginfod**: debug symbols found on {di_r.get('server', '?')}\n")
                    f.write(f"  URL: {di_r.get('url', '?')}\n")

                deep_dive = enhanced.get('deep_dive', {})
                if deep_dive.get('performed'):
                    f.write("\n**uncertain 二次深挖**:\n")
                    f.write(f"  - frame_limit: {deep_dive.get('frame_limit', 0)}\n")
                    f.write(f"  - improved: {deep_dive.get('improved', False)}\n")

                degradation_reasons = enhanced.get('degradation_reasons', [])
                if degradation_reasons:
                    f.write("\n**分析降级原因**:\n")
                    for reason in degradation_reasons:
                        f.write(f"  - {reason}\n")

            f.write("\n")

        # 建议
        if analysis['recommendations']:
            f.write("## 建议\n\n")
            for rec in analysis['recommendations']:
                f.write(f"- {rec}\n")
            f.write("\n")


def main():
    """主函数"""
    args = parse_args()

    print("=" * 80)
    print("版本特定崩溃分析")
    print("=" * 80)
    print(f"包名: {args.package}")
    print(f"版本: {args.version}")
    print(f"工作目录: {args.workspace}")
    print()

    # 分析版本
    analysis = analyze_version(
        args.package,
        args.version,
        args.workspace,
        args.max_crashes,
        args.addr2line_max_frames,
    )

    if 'error' in analysis:
        print(f"错误: {analysis['error']}")
        sys.exit(1)

    # 输出目录: 5.崩溃分析/<package>/version_xxx/
    version_dir = analysis['version_dir']
    output_dir = Path(args.workspace) / '5.崩溃分析' / args.package / f'version_{version_dir}'
    output_dir.mkdir(parents=True, exist_ok=True)

    # 保存JSON结果
    json_file = output_dir / 'analysis.json'
    with open(json_file, 'w', encoding='utf-8') as f:
        json.dump(analysis, f, indent=2, ensure_ascii=False)

    # 保存Markdown报告
    md_file = output_dir / 'analysis_report.md'
    save_markdown_report(analysis, md_file)

    print("=== 分析结果 ===")
    print(f"唯一崩溃数: {analysis['summary']['unique_crashes']}")
    print(f"总崩溃记录数: {analysis['summary']['total_crash_records']}")
    print(f"可修复: {analysis['summary']['fixable_count']}")
    print(f"不可修复: {analysis['summary']['non_fixable_count']}")
    print(f"修复率: {analysis['summary']['fix_rate']}")
    print()

    # 增强分析统计
    estats = analysis.get('enhanced_stats', {})
    if estats:
        print(f"=== 增强分析 ===")
        print(f"addr2line: {estats.get('addr2line_resolved', 0)}/{estats.get('total', 0)} resolved")
        print(f"Source: {estats.get('source_found', 0)} found")
        print(f"Git: {estats.get('git_available', 0)} analyzed")
        print(f"Objdump: {estats.get('objdump_available', 0)} disassembled")
        print(f"LLM: {estats.get('llm_analyzed', 0)} reasoned")
        print(f"Fixability improved: {estats.get('fixability_improved', 0)}")
        print()

    print(f"=== 文件已保存 ===")
    print(f"JSON: {json_file}")
    print(f"Markdown: {md_file}")

    print("\n✅ 分析完成!")


if __name__ == '__main__':
    main()
