#!/usr/bin/env python3
"""生成完整崩溃分析报告 (full_analysis_report.md)"""
import json
import re
from pathlib import Path
import argparse

def demangle(sym):
    """简单的符号反解析"""
    # 这里只是格式化显示，不做完整反解析
    return sym

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--package', required=True)
    parser.add_argument('--workspace', required=True)
    args = parser.parse_args()

    pkg = args.package
    workspace = Path(args.workspace)
    analysis_dir = workspace / '5.崩溃分析' / pkg

    # 收集所有版本
    all_versions = []
    for vf in sorted(analysis_dir.glob('version_*/analysis.json')):
        ver_name = vf.parent.name.replace('version_', '').replace('_', '.')
        with open(vf) as f:
            data = json.load(f)
        all_versions.append({'version': ver_name, 'dir': vf.parent.name, 'data': data})

    def ver_key(v):
        parts = re.findall(r'\d+', v['version'])
        return [int(p) for p in parts[:4]]
    all_versions.sort(key=ver_key)

    lines = []
    lines.append(f"# {pkg} 崩溃分析报告\n")
    lines.append(f"**生成时间**: 2026-04-15\n")
    lines.append(f"**报告路径**: 5.崩溃分析/{pkg}/full_analysis_report.md\n")

    # 总体统计
    total_unique = sum(v['data']['summary']['unique_crashes'] for v in all_versions)
    total_records = sum(v['data']['summary']['total_crash_records'] for v in all_versions)
    total_fixable = sum(v['data']['summary'].get('fixable_count', 0) for v in all_versions)
    total_uncertain = sum(v['data']['summary'].get('uncertain_count', 0) for v in all_versions)
    total_non_fixable = sum(v['data']['summary'].get('non_fixable_count', 0) for v in all_versions)

    signal_stats = {}
    for v in all_versions:
        for sig, cnt in v['data'].get('by_signal', {}).items():
            signal_stats[sig] = signal_stats.get(sig, 0) + cnt

    lines.append("## 总体统计\n")
    lines.append(f"| 指标 | 数值 |")
    lines.append(f"|------|------|")
    lines.append(f"| 分析版本数 | {len(all_versions)} |")
    lines.append(f"| 唯一崩溃数 | {total_unique} |")
    lines.append(f"| 总崩溃记录 | {total_records} |")
    lines.append(f"| 可修复 | {total_fixable} |")
    lines.append(f"| 不可修复 | {total_non_fixable} |")
    lines.append(f"| 需人工判断 | {total_uncertain} |")
    lines.append("")

    if signal_stats:
        lines.append("### 按信号类型统计\n")
        lines.append(f"| 信号 | 次数 | 说明 |")
        lines.append(f"|------|------|------|")
        sig_desc = {'SIGSEGV': '段错误 - 非法内存访问', 'SIGABRT': '主动终止 - 检测到严重错误',
                    'SIGBUS': '总线错误', 'SIGILL': '非法指令', 'SIGTRAP': '跟踪/断点陷阱'}
        for sig, cnt in sorted(signal_stats.items(), key=lambda x: -x[1]):
            lines.append(f"| {sig} | {cnt} | {sig_desc.get(sig, sig)} |")
        lines.append("")

    # 版本统计表
    lines.append("## 版本崩溃统计\n")
    lines.append(f"| 版本 | 唯一崩溃 | 总次数 | 可修复 | 不可修复 | 需人工判断 |")
    lines.append(f"|------|---------|--------|--------|----------|------------|")
    for v in all_versions:
        s = v['data']['summary']
        lines.append(f"| {v['version']} | {s.get('unique_crashes', '?')} | {s.get('total_crash_records', '?')} | {s.get('fixable_count', 0)} | {s.get('non_fixable_count', 0)} | {s.get('uncertain_count', '?')} |")
    lines.append("")

    # 详细崩溃
    for v in all_versions:
        crashes = v['data'].get('crashes', [])
        if not crashes:
            continue

        lines.append(f"## 版本 {v['version']} 崩溃详情\n")
        lines.append(f"共 **{len(crashes)}** 个唯一崩溃\n")

        for i, c in enumerate(crashes):
            sym = c.get('app_layer_symbol', c.get('description', '').split()[-1] if c.get('description') else 'N/A')
            lines.append(f"### {i+1}. {sym}\n")
            lines.append(f"- **崩溃次数**: {c.get('count', '?')} 次")
            lines.append(f"- **信号**: {c.get('signal', 'N/A')} - {c.get('signal_desc', '')}")
            lines.append(f"- **可执行文件**: `{c.get('exe', 'N/A')}`")
            lines.append(f"- **系统版本**: {c.get('sys_v_number', 'N/A')}")
            lines.append(f"- **应用层符号**: `{c.get('app_layer_symbol', 'N/A')}`")
            lines.append(f"- **应用层库**: `{c.get('app_layer_library', 'N/A')}`")
            lines.append(f"- **可修复性**: {c.get('fixable', '?')}")
            if c.get('fix_reason'):
                lines.append(f"- **判定原因**: {c.get('fix_reason')}")
            if c.get('fix_type'):
                lines.append(f"- **修复类型**: {c.get('fix_type')}")
            if c.get('fix_code'):
                lines.append(f"- **建议修复代码**:\n```cpp\n{c.get('fix_code')}\n```")

            stack = c.get('stack_info', '')
            if stack:
                lines.append(f"- **崩溃堆栈**:\n```\n{stack}\n```")

            frames = c.get('frames', [])
            if frames:
                lines.append(f"- **调用帧**:\n| 帧号 | 符号 | 库 |")
                lines.append(f"|------|------|-----|")
                for fi, frame in enumerate(frames[:15]):
                    f_sym = frame.get('symbol', 'n/a')
                    f_lib = frame.get('library', 'n/a')
                    lines.append(f"| #{fi} | {f_sym} | {f_lib} |")

            lines.append("")

    report_file = analysis_dir / 'full_analysis_report.md'
    analysis_dir.mkdir(parents=True, exist_ok=True)
    report_file.write_text(''.join(lines), encoding='utf-8')
    print(f"✅ full_analysis_report.md 已生成: {report_file}")

if __name__ == '__main__':
    main()
