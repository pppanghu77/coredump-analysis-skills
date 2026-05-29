#!/usr/bin/env python3
"""生成AI崩溃分析报告 (AI_analysis_report.md)"""
import json
from pathlib import Path
from collections import defaultdict
import argparse
from datetime import datetime

from package_rules import get_pattern_ai_explanations


def build_generic_explanation(crash, func: str):
    """在没有包级规则文案时提供保守兜底说明。"""
    signal = crash.get('signal', 'UNKNOWN')
    fixable = crash.get('fixable')
    reason = crash.get('reason') or '需要进一步调试分析'
    key_frame = crash.get('key_frame') or {}
    library = key_frame.get('library') or crash.get('app_layer_library') or '未知库'
    symbol = key_frame.get('symbol') or func or '未知符号'

    if signal == 'SIGABRT':
        return {
            'analysis': f'崩溃表现为 {signal}，通常是检测到异常状态后主动终止。',
            'cause': f'关键位置位于 `{library}` 的 `{symbol}`，当前更像断言失败、致命日志或未处理异常。',
            'suggestion': '检查触发 abort 前的错误路径、断言条件和异常处理逻辑。',
        }

    if signal == 'SIGSEGV':
        return {
            'analysis': f'崩溃表现为 {signal}，属于非法内存访问。',
            'cause': f'关键位置位于 `{library}` 的 `{symbol}`，常见于空指针、悬空对象或越界访问。当前判断为：{reason}。',
            'suggestion': '优先检查关键帧附近对象生命周期、空值保护、线程切换和容器边界。',
        }

    if fixable is True:
        return {
            'analysis': '已识别为可继续修复的崩溃。',
            'cause': f'关键位置位于 `{library}` 的 `{symbol}`，当前判断为：{reason}。',
            'suggestion': '结合版本源码和符号文件，优先检查关键帧附近的前置条件与资源状态。',
        }

    if fixable is False:
        return {
            'analysis': '当前更像外部库、环境或运行时触发的问题。',
            'cause': f'关键位置位于 `{library}` 的 `{symbol}`，当前判断为：{reason}。',
            'suggestion': '补充环境信息、依赖版本和原始 coredump，确认是否属于上游库或外部条件触发。',
        }

    return {
        'analysis': '当前规则已完成基础归类，但仍需进一步调试。',
        'cause': f'关键位置位于 `{library}` 的 `{symbol}`，当前判断为：{reason}。',
        'suggestion': '继续结合源码、build-id、addr2line 和原始 coredump 做二次定位。',
    }


def infer_root_cause_category(crash, pattern_explanations):
    """基于模式标签优先，其次回退到信号/修复性做通用分类。"""
    pattern = crash.get('pattern_name', '')
    if pattern and pattern in pattern_explanations:
        category = pattern_explanations[pattern].get('category')
        if category:
            return category

    signal = crash.get('signal', 'UNKNOWN')
    if pattern == 'opaque_no_symbols':
        return '符号缺失/环境问题'
    if signal == 'SIGABRT':
        return '异常终止/断言'
    if signal == 'SIGSEGV':
        return '内存访问/对象生命周期'
    if crash.get('fixable') is False:
        return '外部库/环境问题'
    return '其他'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--package', required=True)
    parser.add_argument('--workspace', required=True)
    args = parser.parse_args()

    pkg = args.package
    workspace = Path(args.workspace)
    analysis_dir = workspace / '5.崩溃分析' / pkg
    pattern_explanations = get_pattern_ai_explanations(pkg)

    # 收集所有崩溃
    all_crashes = []
    versions_seen = set()
    for vf in sorted(analysis_dir.glob('version_*/analysis.json')):
        ver = vf.parent.name.replace('version_', '').replace('_', '.')
        with open(vf) as f:
            data = json.load(f)
        for c in data.get('crashes', []):
            c['version'] = ver
            all_crashes.append(c)
            versions_seen.add(ver)

    dates = [c.get('date') for c in all_crashes if c.get('date')]
    start_date = min(dates) if dates else '未知'
    end_date = max(dates) if dates else '未知'

    # 按函数聚合
    by_func = defaultdict(list)
    for c in all_crashes:
        key_frame = c.get('key_frame') or {}
        func = c.get('app_layer_symbol', '') or \
               key_frame.get('symbol', '') or \
               c.get('pattern_name', '') or \
               'unknown'
        by_func[func].append(c)

    # 按信号聚合
    by_signal = defaultdict(int)
    for c in all_crashes:
        by_signal[c.get('signal', 'UNKNOWN')] += c.get('count', 1)

    # 高频崩溃 (>=3次)
    high_freq = [(f, cs) for f, cs in by_func.items() if sum(x.get('count', 1) for x in cs) >= 3]
    high_freq.sort(key=lambda x: -sum(c.get('count', 1) for c in x[1]))

    lines = []
    lines.append(f"# {pkg} 崩溃 AI 分析报告\n")
    lines.append(f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    lines.append(f"**数据范围**: {start_date} 至 {end_date}\n")
    lines.append(f"**分析版本**: {len(versions_seen)} 个\n")
    lines.append(f"**唯一崩溃**: {len(all_crashes)} 个\n")
    lines.append(f"**总崩溃次数**: {sum(c.get('count', 1) for c in all_crashes)}\n")
    lines.append("\n---\n")

    # 信号统计
    lines.append("## 1. 按信号类型统计\n")
    for sig, cnt in sorted(by_signal.items(), key=lambda x: -x[1]):
        sig_desc = {
            'SIGSEGV': '段错误 - 非法内存访问',
            'SIGABRT': '主动终止 - 检测到严重错误',
            'SIGBUS': '总线错误',
            'SIGILL': '非法指令',
            'SIGTRAP': '跟踪/断点陷阱'
        }
        lines.append(f"- **{sig}**: {cnt} 次 — {sig_desc.get(sig, sig)}\n")

    # 高频崩溃分析
    lines.append(f"\n## 2. 高频崩溃分析 (Top {min(len(high_freq), 15)})\n")

    for rank, (func, crashes) in enumerate(high_freq[:15], 1):
        total_count = sum(c.get('count', 1) for c in crashes)
        versions = sorted(set(c['version'] for c in crashes))
        top_sig = crashes[0].get('signal', 'N/A')

        lines.append(f"### {rank}. `{func}`\n")
        lines.append(f"**崩溃次数**: {total_count}\n")
        lines.append(f"**涉及版本**: {', '.join(versions[:5])}{' ...' if len(versions) > 5 else ''}\n")
        lines.append(f"**信号类型**: {top_sig}\n")
        crash0 = crashes[0]
        key_frame = crash0.get('key_frame') or {}
        pattern = crash0.get('pattern_name', '')
        lines.append(f"**涉及库**: {crash0.get('app_layer_library') or key_frame.get('library', 'N/A')}\n")
        if pattern:
            lines.append(f"**模式标签**: {pattern}\n")

        stack = crashes[0].get('stack_info', '')
        if stack:
            lines.append(f"**堆栈示例**:\n```\n")
            for line in stack.split('\n')[:20]:
                if line.strip():
                    lines.append(f"{line}\n")
            lines.append(f"```\n")

        # AI 分析
        if pattern in pattern_explanations:
            info = pattern_explanations[pattern]
            lines.append(f"**AI 分析**: {info['analysis']}\n")
            lines.append(f"**可能原因**: {info['cause']}\n")
            lines.append(f"**修复建议**: {info['suggestion']}\n")
        else:
            info = build_generic_explanation(crash0, func)
            lines.append(f"**AI 分析**: {info['analysis']}\n")
            lines.append(f"**可能原因**: {info['cause']}\n")
            lines.append(f"**修复建议**: {info['suggestion']}\n")

        lines.append(f"\n---\n")

    # 总结
    lines.append("## 3. 总结与修复建议\n")
    total = sum(c.get('count', 1) for c in all_crashes)
    lines.append(f"本次分析共发现 **{len(all_crashes)}** 个唯一崩溃，分布在 **{len(set(c['version'] for c in all_crashes))}** 个版本中。\n")

    root_causes = {}
    for crash in all_crashes:
        category = infer_root_cause_category(crash, pattern_explanations)
        root_causes[category] = root_causes.get(category, 0) + crash.get('count', 1)

    lines.append(f"\n### 根因分类统计\n")
    for cause, count in sorted(root_causes.items(), key=lambda x: -x[1]):
        if count > 0:
            pct = count * 100 / total
            lines.append(f"- **{cause}**: {count} 次 ({pct:.1f}%)\n")

    lines.append(f"\n### 整体建议\n")
    if root_causes.get('内存访问/对象生命周期', 0) > 0:
        lines.append(f"1. **修复对象析构时序问题**: 使用 `QPointer<>` 或显式 `disconnect()` 避免访问已销毁对象。\n")
    if root_causes.get('D-Bus/进程通信', 0) > 0:
        lines.append(f"2. **修复 D-Bus 连接管理**: 在析构前先断开 D-Bus 连接，避免析构期间仍有消息发送。\n")
    if root_causes.get('Qt事件循环', 0) > 0:
        lines.append(f"3. **修复 Qt 事件循环问题**: 避免在析构期间调用 `postEvent()`，先退出事件循环再销毁对象。\n")
    if root_causes.get('图标渲染/资源加载', 0) > 0:
        lines.append(f"4. **补强图标与资源加载兜底**: 对图标路径、SVG 数据、pixmap 加载结果和主题项增加非空校验与 fallback。\n")
    if root_causes.get('符号缺失/环境问题', 0) > 0:
        lines.append(f"5. **补齐符号与构建信息**: 为缺符号版本补充 dbgsym、build-id 和原始 coredump，避免剩余崩溃停留在 opaque 状态。\n")
    lines.append(f"6. **增加测试覆盖**: 针对插件加载/卸载场景编写自动化测试，覆盖对象生命周期完整路径。\n")

    report_file = analysis_dir / 'AI_analysis_report.md'
    report_file.write_text(''.join(lines), encoding='utf-8')
    print(f"✅ AI_analysis_report.md 已生成: {report_file} ({len(lines)} 行)")

if __name__ == '__main__':
    main()
