#!/usr/bin/env python3
"""
通用崩溃数据筛选工具
支持所有包的崩溃数据筛选和统计

改进：
- 添加 VERSION_TAG_MAP 配置
- 扩展系统库列表
- 支持按包名自动加载配置
"""
import csv
import re
import json
import sys
import os
from collections import defaultdict
from datetime import datetime
import glob
import argparse

# 配置
def generate_workspace_with_timestamp():
    """生成带时间戳的workspace路径"""
    for env_name in ("COREDUMP_WORKSPACE", "WORKSPACE"):
        workspace = os.environ.get(env_name)
        if workspace:
            return os.path.expanduser(workspace)
    return os.path.expanduser(f"~/coredump-workspace-{datetime.now().strftime('%Y%m%d-%H%M%S')}")

DEFAULT_WORKSPACE = generate_workspace_with_timestamp()

# ============================================================
# 版本 TAG 映射表
# 用于崩溃分析时切换到正确的代码分支
# ============================================================
VERSION_TAG_MAP = {
    # dde-launcher
    "5.5.33.2+zyd-1": "",
    "5.5.39-1": "",
    "5.5.41-1": "5.5.41",
    "5.5.42.1-1": "5.5.42.1",
    "5.6.15-1": "5.6.15",
    "5.6.15.1-1": "5.6.15.1",
    "5.6.19.1-1": "5.6.19.1",
    "5.6.19.2-1": "5.6.19.2",
    "5.6.19.3-1": "5.6.19.3",
    "5.7.9.5-1": "5.7.9.5",
    "5.7.9.7-1": "5.7.9.7",
    "5.7.16.1-1": "5.7.16.1",
    "5.7.17-1": "5.7.17.4",
    "5.7.20-1": "5.7.20.2",
    "5.7.20.3-1": "5.7.20.3",
    "5.7.25.1-1": "",
    "5.8.4-1": "5.8.4",
    "5.8.5-1": "5.8.5",
    "5.8.6-1": "5.8.6",
    # dde-dock
    "5.7.28.2-1": "5.7.28.2",
    "5.7.28.3-1": "5.7.28.3",
    "5.7.28.5-1": "5.7.28.5",
    "5.7.28.6-1": "5.7.28.6",
    "5.8.4.1-1": "5.8.4.1",
    "5.8.5.2-1": "5.8.5.2",
    "5.8.6.1-1": "5.8.6.1",
    "5.9.1.2-1": "5.9.1.2",
}

# 包名到 VERSION_TAG_MAP 的映射
PACKAGE_VERSION_TAG_MAPS = {
    "dde-launcher": VERSION_TAG_MAP,
    "dde-dock": {
        "5.7.28.2-1": "5.7.28.2",
        "5.7.28.3-1": "5.7.28.3",
        "5.7.28.5-1": "5.7.28.5",
        "5.7.28.6-1": "5.7.28.6",
        "5.8.4.1-1": "5.8.4.1",
        "5.8.5.2-1": "5.8.5.2",
        "5.8.6.1-1": "5.8.6.1",
        "5.9.1.2-1": "5.9.1.2",
    },
}

# ============================================================
# 系统库列表 (这些崩溃不需要修复)
# ============================================================
SYSTEM_LIBRARIES = {
    # Qt库
    "libQt5Core.so.5", "libQt5Widgets.so.5", "libQt5Gui.so.5",
    "libQt5DBus.so.5", "libQt5Network.so.5", "libQt5XcbQpa.so.5",
    "libQt5WaylandClient.so.5", "libQt5Wayland.so.5",
    "libQt6Core.so.6", "libQt6Widgets.so.6", "libQt6Gui.so.6",
    # Wayland
    "libwayland-client.so.0", "libwayland-cursor.so.0",
    "libwayland-egl.so.1",
    # GLib
    "libglib-2.0.so.0", "libgobject-2.0.so.0", "libgio-2.0.so.0",
    # glibc
    "libc.so.6", "libpthread.so.0", "librt.so.1", "libm.so.6",
    "libdl.so.2", "libresolv.so.2", "libnss_*.so.2",
    # GCC/LLVM
    "libstdc++.so.6", "libgcc_s.so.1", "libc++.so.1",
    # Dtk
    "libdtkwidget.so.5", "libdtkgui.so.5", "libdtkcore.so.5",
    "libdtkcore.so.6", "libdtkgui.so.6", "libdtkwidget.so.6",
    "libdtkiconproxy.so", "libdtksettings.so.5",
    # 图标/渲染库
    "libxdgicon.so", "libxdgicon.so.3",
    "libdsvgicon.so", "libdsvgicon.so.5",
    "libQt5Xdg.so", "libQt5XdgIconLoader.so", "libQt5XdgIconLoader.so.3",
    "librsvg-2.so.2", "libgdk_pixbuf-2.0.so.0", "libcairo.so.2",
    # DBus
    "libdframeworkdbus.so.2", "libdframeworkdbus.so.3",
    "libdbus-1.so.3", "libdbus-glib-1.so.2",
    # X11
    "libX11.so.6", "libxcb.so.1", "libXext.so.6",
    "libXrender.so.1", "libXi.so.6", "libXfixes.so.3",
    # DRM/EGL/GL
    "libdrm.so.2", "libgbm.so.1", "libEGL.so.1", "libGL.so.1",
    "libGLdispatch.so.0", "libGLX.so.0",
    # FFI
    "libffi.so.6", "libffi.so.7",
    # BlueZ
    "libbluetooth.so.3", "libbluetooth.so.5",
    # systemd
    "libsystemd.so.0", "libsystemd.so.1",
    # PAM
    "libpam.so.1", "libpam_misc.so.1",
    # SSL
    "libssl.so.1.1", "libssl.so.3", "libcrypto.so.1.1", "libcrypto.so.3",
    # Other
    "libpango-1.0.so.0", "libgdk-3.so.0", "libgtk-3.so.0",
    "libmount.so.1", "libselinux.so.1", "libcap.so.2",
    "libaudit.so.1", "libnsl.so.1", "libshell.so.1",
}


def get_version_tag_map(package: str = "") -> dict:
    """获取指定包的 VERSION_TAG_MAP"""
    if package and package in PACKAGE_VERSION_TAG_MAPS:
        return PACKAGE_VERSION_TAG_MAPS[package]
    return VERSION_TAG_MAP


def lookup_version_tag(version: str, package: str = "") -> str:
    """根据崩溃版本号查找对应的 git tag"""
    tag_map = get_version_tag_map(package)
    return tag_map.get(version, "")


def is_system_library(library: str) -> bool:
    """检查是否是系统库"""
    if not library:
        return False
    for sys_lib in SYSTEM_LIBRARIES:
        if sys_lib.endswith(".*"):
            # 通配符模式
            prefix = sys_lib[:-4]
            if library.startswith(prefix):
                return True
        elif sys_lib in library:
            return True
    return False

# 字段名映射 (小写 -> 大写)
FIELD_MAPPING = {
    'id': 'ID',
    'dt': 'Dt',
    'version': 'Version',
    'package': 'Package',
    'exe': 'Exe',
    'sig': 'Sig',
    'stackinfo': 'StackInfo',
    'sys_v_number': 'Sys V Number',
    'baseline': 'Baseline',
    'buildid': 'Buildid',
    'date': 'Date',
    'arch': 'Arch',
    'sys_c': 'Sys C',
    'sys_v': 'Sys V'
}

def normalize_field_name(field):
    """将小写字段名转换为大写"""
    return FIELD_MAPPING.get(field.lower(), field)

def get_field(row, field_name):
    """从行中获取字段，支持大小写"""
    # 先尝试直接获取
    if field_name in row:
        return row[field_name]
    # 尝试小写版本
    for k, v in row.items():
        if k.lower() == field_name.lower():
            return v
    return ''

def parse_stack_info(stack_info):
    """解析崩溃堆栈，提取关键帧和签名"""
    if not stack_info or not stack_info.strip():
        return {'frames': [], 'signature': '', 'raw': stack_info}

    frames = []
    key_frames = []

    lines = stack_info.strip().split('\n')
    for line in lines:
        # 匹配两种格式:
        # 格式1: #0  0x... n/a (library) - 有空格和 n/a
        # 格式2: #0  0x... symbol (library) - 有函数名
        # 可能前面有空格
        match = re.match(r'\s*#\s*(\d+)\s+0x[0-9a-f]+\s+(\S+)\s+\(([^)]+)\)', line)
        if match:
            frame_num = match.group(1)
            symbol = match.group(2)
            library = match.group(3)
            frames.append({'num': frame_num, 'symbol': symbol, 'library': library})
            # 取前10帧作为签名
            if len(key_frames) < 10:
                is_system_lib = is_system_library(library)
                if not is_system_lib or len(key_frames) < 3:
                    key_frames.append(f"{library}:{symbol}")

    # 生成堆栈签名
    signature = '|'.join(key_frames[:10])

    return {
        'frames': frames,
        'signature': signature,
        'raw': stack_info,
        'frames_count': len(frames)
    }

def find_latest_csv(package, download_dir):
    """查找最新的CSV文件"""
    patterns = [
        f"{download_dir}/download_*/{package}_X86_64_crash_*.csv",
        f"{download_dir}/download_*/{package}_X86_crash_*.csv",
        f"{download_dir}/download_*/{package}_*_crash_*.csv",
        f"{download_dir}/{package}_X86_64_crash_*.csv",
        f"{download_dir}/{package}_X86_crash_*.csv",
        f"{download_dir}/{package}_*_crash_*.csv"
    ]
    files = []
    for pattern in patterns:
        files.extend(glob.glob(pattern))

    if not files:
        # 尝试递归查找
        all_csv = glob.glob(f"{download_dir}/**/*.csv", recursive=True)
        csv_for_package = [f for f in all_csv if f"{package}_" in os.path.basename(f)]
        if csv_for_package:
            return sorted(csv_for_package)[-1]
        return None
    return sorted(files)[-1]

def process_crash_data(package, workspace, input_csv_override=None):
    """处理指定包的崩溃数据；input_csv_override 支持从项目级下载数据中按实际包筛选。"""
    DOWNLOAD_DIR = f"{workspace}/1.数据下载"
    OUTPUT_DIR = f"{workspace}/2.数据筛选"

    print("=" * 80)
    print(f"{package} 崩溃数据筛选与统计工具")
    print("=" * 80)
    print(f"工作目录: {workspace}")
    print()

    # 查找CSV文件；一项目多包场景可由上层传入项目级 CSV，然后这里按实际 package 字段筛选。
    input_csv = input_csv_override or find_latest_csv(package, DOWNLOAD_DIR)
    if not input_csv:
        print(f"错误：未找到 {package} 的崩溃数据文件")
        print(f"请先运行数据下载步骤，下载目录: {DOWNLOAD_DIR}")
        return False

    print(f"输入文件: {input_csv}")
    print()

    # 按版本号分组存储唯一崩溃堆栈
    version_groups = defaultdict(dict)

    # 统计信息
    stats = {
        'total_rows': 0,
        'valid_rows': 0,
        'by_version': defaultdict(lambda: {'total': 0, 'unique': 0}),
        'by_signal': defaultdict(int),
        'by_sys_version': defaultdict(int),
        'by_baseline': defaultdict(int),
        'app_layer_libs': defaultdict(int)
    }

    print("正在读取CSV文件...")

    with open(input_csv, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)

        for row in reader:
            stats['total_rows'] += 1

            exe = get_field(row, 'Exe')
            version = get_field(row, 'Version')
            package_name = get_field(row, 'Package')
            stack_info = get_field(row, 'StackInfo')
            sig = get_field(row, 'Sig')
            sys_v_number = get_field(row, 'Sys V Number')
            baseline = get_field(row, 'Baseline')

            # 项目级下载 CSV 可能包含同一源码项目下多个二进制包；筛选阶段必须只保留当前分析包。
            if package_name and package_name != package:
                continue

            # 过滤无效记录
            if not exe or not stack_info:
                continue

            if not version:
                version = 'unknown'

            stack_data = parse_stack_info(stack_info)
            if not stack_data['frames']:
                continue

            stats['valid_rows'] += 1

            # 统计信号类型
            if sig:
                stats['by_signal'][sig] += 1

            # 统计系统版本
            if sys_v_number:
                stats['by_sys_version'][sys_v_number] += 1

            # 统计基线版本
            if baseline:
                stats['by_baseline'][baseline] += 1

            # 统计应用层库
            for frame in stack_data['frames']:
                is_system = is_system_library(frame['library'])
                if not is_system and frame['symbol'] != 'n/a':
                    stats['app_layer_libs'][frame['library']] += 1
                    break

            # 按版本号和堆栈签名去重
            stack_signature = stack_data['signature']
            record_key = stack_signature

            if record_key not in version_groups[version]:
                version_groups[version][record_key] = {
                    'version': version,
                    'package': package_name,
                    'exe': exe,
                    'sig': sig,
                    'stack_info': stack_info,
                    'stack_signature': stack_signature,
                    'stack_frames_count': stack_data['frames_count'],
                    'stack_info_size': len(stack_info),
                    'app_layer_library': '',
                    'app_layer_symbol': '',
                    'count': 1,
                    'first_seen': get_field(row, 'Dt') or get_field(row, 'Date'),
                    'baseline': baseline,
                    'sys_v_number': sys_v_number
                }

                # 提取应用层崩溃帧
                for frame in stack_data['frames']:
                    is_system = is_system_library(frame['library'])
                    if not is_system and frame['symbol'] != 'n/a':
                        version_groups[version][record_key]['app_layer_library'] = frame['library']
                        version_groups[version][record_key]['app_layer_symbol'] = frame['symbol']
                        break
            else:
                version_groups[version][record_key]['count'] += 1

    # 汇总统计
    total_unique_crashes = sum(len(groups) for groups in version_groups.values())
    duplicates = stats['valid_rows'] - total_unique_crashes

    print(f"原始记录数: {stats['total_rows']}")
    print(f"有效记录数: {stats['valid_rows']}")
    print(f"去重后记录数: {total_unique_crashes}")
    print(f"合并重复: {duplicates}")
    print()

    # 展平结果并按版本号分组排序
    all_records = []
    for version in sorted(version_groups.keys()):
        groups = version_groups[version]
        sorted_groups = sorted(groups.items(), key=lambda x: -x[1]['count'])
        for stack_key, record in sorted_groups:
            all_records.append(record)

    # 保存筛选后的CSV
    output_csv = os.path.join(OUTPUT_DIR, f'filtered_{package}_crash_data.csv')
    print("正在保存筛选数据...")
    fieldnames = [
        'Version', 'Package', 'Count', 'Exe', 'Sig',
        'StackInfo', 'StackSignature', 'StackInfo_Size', 'Stack_Frames_Count',
        'App_Layer_Library', 'App_Layer_Symbol',
        'First_Seen', 'Baseline', 'Sys_V_Number'
    ]

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(output_csv, 'w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for record in all_records:
            writer.writerow({
                'Version': record['version'],
                'Package': record['package'],
                'Count': record['count'],
                'Exe': record['exe'],
                'Sig': record['sig'],
                'StackInfo': record['stack_info'],
                'StackSignature': record['stack_signature'],
                'StackInfo_Size': record['stack_info_size'],
                'Stack_Frames_Count': record['stack_frames_count'],
                'App_Layer_Library': record['app_layer_library'],
                'App_Layer_Symbol': record['app_layer_symbol'],
                'First_Seen': record['first_seen'],
                'Baseline': record['baseline'],
                'Sys_V_Number': record['sys_v_number']
            })

    print(f"已保存筛选数据到: {output_csv}")
    print()

    # 生成统计报告文件
    stats_report = {
        'summary': {
            'total_records': stats['total_rows'],
            'valid_records': stats['valid_rows'],
            'unique_crashes': total_unique_crashes,
            'duplicate_crashes': duplicates,
            'versions_count': len(version_groups),
            'analysis_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        },
        'by_version': {},
        'by_signal': dict(stats['by_signal']),
        'by_sys_version': dict(stats['by_sys_version']),
        'by_baseline': dict(stats['by_baseline']),
        'app_layer_libs': dict(stats['app_layer_libs']),
        'top_crashes': []
    }

    # 按版本统计
    for version in sorted(version_groups.keys()):
        groups = version_groups[version]
        unique_count = len(groups)
        total_count = sum(r['count'] for r in groups.values())
        stats_report['by_version'][version] = {
            'unique_crashes': unique_count,
            'total_crashes': total_count
        }

    # Top 10 崩溃
    top_crashes = sorted(all_records, key=lambda x: -x['count'])[:10]
    for i, crash in enumerate(top_crashes, 1):
        stats_report['top_crashes'].append({
            'rank': i,
            'version': crash['version'],
            'count': crash['count'],
            'signal': crash['sig'],
            'app_layer_symbol': crash['app_layer_symbol'] or 'N/A',
            'app_layer_library': crash['app_layer_library'] or 'N/A'
        })

    # 保存统计报告
    stats_file = os.path.join(OUTPUT_DIR, f'{package}_crash_statistics.json')
    with open(stats_file, 'w', encoding='utf-8') as f:
        json.dump(stats_report, f, ensure_ascii=False, indent=2)

    print(f"已保存统计报告到: {stats_file}")
    print()

    # 输出崩溃版本号列表（按崩溃次数降序排列）
    versions_sorted = sorted(version_groups.keys(), key=lambda v: -sum(r['count'] for r in version_groups[v].values()))
    versions_list_file = os.path.join(OUTPUT_DIR, f'{package}_crash_versions.txt')
    with open(versions_list_file, 'w', encoding='utf-8') as f:
        for v in versions_sorted:
            total = sum(r['count'] for r in version_groups[v].values())
            f.write(f"{v}:{total}\n")
    print(f"已保存崩溃版本列表到: {versions_list_file}")
    print()

    # 打印统计摘要
    print("=" * 80)
    print("统计摘要")
    print("=" * 80)
    print()

    print(f"【总体统计】")
    print(f"  总记录数: {stats['total_rows']}")
    print(f"  有效记录数: {stats['valid_rows']}")
    print(f"  唯一崩溃数: {total_unique_crashes}")
    print(f"  版本数: {len(version_groups)}")
    print()

    print(f"【按版本号统计】")
    print(f"{'版本号':<25} {'唯一崩溃数':<12} {'总崩溃数':<12}")
    print("-" * 50)
    for version in sorted(version_groups.keys()):
        groups = version_groups[version]
        unique_count = len(groups)
        total_count = sum(r['count'] for r in groups.values())
        print(f"{version:<25} {unique_count:<12} {total_count:<12}")
    print()

    print(f"【按信号类型统计】")
    print(f"{'信号类型':<15} {'数量':<10}")
    print("-" * 25)
    for sig, count in sorted(stats['by_signal'].items(), key=lambda x: -x[1]):
        print(f"{sig:<15} {count:<10}")
    print()

    print(f"【Top 5 崩溃堆栈】")
    print(f"{'序号':<4} {'版本':<20} {'次数':<6} {'信号':<10} {'应用层函数':<40}")
    print("-" * 80)
    for i, crash in enumerate(top_crashes[:5], 1):
        symbol = crash['app_layer_symbol'][:38] if crash['app_layer_symbol'] else 'N/A'
        print(f"{i:<4} {crash['version']:<20} {crash['count']:<6} {crash['sig']:<10} {symbol:<40}")
    print()

    print("=" * 80)
    print("完成!")
    print("=" * 80)

    return True

def main():
    parser = argparse.ArgumentParser(description='崩溃数据筛选工具')
    parser.add_argument('package', help='包名')
    parser.add_argument('--workspace', default=DEFAULT_WORKSPACE, help='工作目录')
    parser.add_argument('--input-csv', default='', help='显式指定输入CSV；用于从项目级下载数据中筛选实际包')

    args = parser.parse_args()
    process_crash_data(args.package, args.workspace, args.input_csv or None)

if __name__ == '__main__':
    main()
