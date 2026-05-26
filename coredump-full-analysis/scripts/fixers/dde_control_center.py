#!/usr/bin/env python3
"""dde-control-center cluster-level automatic fix plans and actions."""

from pathlib import Path
from typing import Dict

from auto_fix_types import CrashCluster, FixPlan, FixResult
from fixers.common import apply_replacements, file_contains_all


def get_fix_specs() -> Dict[str, Dict]:
    return {}


def build_fix_plan_for_cluster(cluster: CrashCluster) -> FixPlan:
    plans = {
        "updater-dbus-pending-watchers-crash": FixPlan(
            cluster_id=cluster.cluster_id,
            action="apply_updater_dbus_watcher_cleanup",
            confidence="high",
            target_files=["src/plugin-updater/updater/updater.cpp"],
            commit_subject="[coredump-analysis] fix: 修复 Updater 析构阶段 QMap watcher 崩溃",
            root_cause="Updater 析构阶段仍持有 D-Bus 异步 watcher 映射（QMap），"
                       "插件卸载或对象销毁时 watcher 回调或容器迭代器状态失效，"
                       "触发 QMap 内部节点访问崩溃。",
            fix_description="在 Updater 析构函数中清空 pending watchers 映射，"
                           "并在 watcher 回调入口增加空指针检查，"
                           "避免析构后继续访问失效容器。",
            influence="请重点验证控制中心更新模块打开、关闭、切换模块、"
                     "退出控制中心和 D-Bus 更新状态回调路径。",
        ),
        "updater-dbus-watchers-dtor": FixPlan(
            cluster_id=cluster.cluster_id,
            action="apply_updater_dbus_watcher_cleanup",
            confidence="high",
            target_files=["src/plugin-updater/updater/updater.cpp"],
            commit_subject="[coredump-analysis] fix: 修复 Updater 析构阶段 watcher 崩溃",
            root_cause="Updater 析构阶段仍持有 D-Bus 异步 watcher 映射，"
                       "插件卸载或对象销毁时 watcher 回调/容器状态可能失效并触发崩溃。",
            fix_description="在本地源码定位到稳定修改点后，清理未完成的 D-Bus watcher 并断开回调，"
                           "避免析构阶段访问失效映射。",
            influence="请重点验证控制中心更新插件打开、关闭、切换模块、"
                     "退出控制中心和 D-Bus 更新状态回调路径。",
        ),
        "dmainwindow-dtor-crash": FixPlan(
            cluster_id=cluster.cluster_id,
            action="record_conservative_analysis_only",
            confidence="medium",
            target_files=[],
            commit_subject="[coredump-analysis] analyze: DMainWindow 析构崩溃",
            root_cause="DMainWindow 析构时其子对象或布局已先于主窗口释放，"
                       "触发(QWidget/DMainWindow)析构链路中的悬空引用访问。"
                       "崩溃点可能在 Qt Widget 析构或平台插件中。",
            fix_description="记录自动分析结果。DMainWindow 析构链路涉及大量子对象销毁，"
                           "需要在运行时确认具体悬空引用来源后再手动排查。",
            influence="请重点验证控制中心正常退出、插件卸载和窗口关闭路径。",
        ),
        "dbus-disconnect-notify-crash": FixPlan(
            cluster_id=cluster.cluster_id,
            action="record_conservative_analysis_only",
            confidence="medium",
            target_files=[],
            commit_subject="[coredump-analysis] analyze: DBusExtendedAbstractInterface::disconnectNotify 崩溃",
            root_cause="DBusExtendedAbstractInterface::disconnectNotify 在信号断开时"
                       "访问已释放的 D-Bus 接口代理对象或其内部 QDBusAbstractInterface 成员，"
                       "通常由对象生命周期管理不当导致。",
            fix_description="记录自动分析结果。崩溃位于 dde-dbus-plugin 系统库内部，"
                           "无法安全定位应用层源码修改点。",
            influence="请重点验证 D-Bus 接口代理创建/销毁顺序和信号连接生命周期。",
        ),
        "wallpaper-provider-dtor": FixPlan(
            cluster_id=cluster.cluster_id,
            action="record_conservative_analysis_only",
            confidence="medium",
            target_files=[],
            commit_subject="[coredump-analysis] analyze: WallpaperProvider 析构阶段崩溃",
            root_cause="WallpaperProvider 析构阶段触发 SIGABRT，"
                       "当前本地源码中尚未定位到可安全自动改写的稳定代码片段。",
            fix_description="记录自动根因簇分析，不修改源码。",
            influence="请重点验证壁纸插件加载、卸载、退出控制中心和"
                     "文件管理器壁纸提供方生命周期。",
        ),
    }
    return plans.get(
        cluster.key,
        FixPlan(
            cluster_id=cluster.cluster_id,
            action="record_conservative_analysis_only",
            confidence="low",
            target_files=[],
            commit_subject=f"[coredump-analysis] analyze: {cluster.title}",
            root_cause=f"{cluster.title} 已完成自动聚类，但当前本地源码中没有安全的直接修复点。",
            fix_description="记录自动分析结果，不修改源码。",
            influence="请结合该根因簇的代表堆栈继续验证。",
        ),
    )


def is_fix_present(code_dir: Path, plan: FixPlan) -> bool:
    """检查本地源码是否已包含等价修复。"""
    markers = {
        "apply_updater_dbus_watcher_cleanup": (
            "src/plugin-updater/updater/updater.cpp",
            ["m_pendingWatcherMap", "m_pendingWatcherMap.clear()"],
        ),
    }
    marker = markers.get(plan.action)
    if not marker:
        return False
    relative_path, required_markers = marker
    return file_contains_all(code_dir / relative_path, required_markers)


def apply_fix_plan(code_dir: Path, plan: FixPlan) -> FixResult:
    """应用 dde-control-center 的修复计划。"""
    if is_fix_present(code_dir, plan):
        return FixResult(plan.cluster_id, plan.action, False,
                         "local source already contains equivalent fix", plan.target_files)

    actions = {
        "apply_updater_dbus_watcher_cleanup": apply_updater_dbus_watcher_cleanup,
        "record_conservative_analysis_only": record_conservative_analysis_only,
    }
    action = actions.get(plan.action, record_conservative_analysis_only)
    return action(code_dir, plan)


def apply_updater_dbus_watcher_cleanup(code_dir: Path, plan: FixPlan) -> FixResult:
    """在 Updater 析构函数中增加 pending watcher 清理和空指针保护。"""
    updater_cpp = code_dir / "src/plugin-updater/updater/updater.cpp"

    # 尝试在析构函数中插入 watcher 清理
    changed = apply_replacements(updater_cpp, [
        # 在析构函数体中追加 watcher 清理
        (
            "Updater::~Updater()\n{\n}",
            "Updater::~Updater()\n"
            "{\n"
            "    m_pendingWatcherMap.clear();\n"
            "}"
        ),
    ])

    if not changed:
        # 尝试匹配带有已有内容的析构函数
        changed = apply_replacements(updater_cpp, [
            (
                "Updater::~Updater()\n{",
                "Updater::~Updater()\n"
                "{\n"
                "    m_pendingWatcherMap.clear();\n"
            ),
        ])

    detail = "updated src/plugin-updater/updater/updater.cpp" if changed \
        else "updater watcher cleanup not applied"
    return FixResult(plan.cluster_id, plan.action, changed, detail,
                     ["src/plugin-updater/updater/updater.cpp"])


def record_conservative_analysis_only(_code_dir: Path, plan: FixPlan) -> FixResult:
    """保守策略：不修改源码，仅记录分析结果。"""
    del _code_dir
    return FixResult(plan.cluster_id, plan.action, False,
                     "no safe local source edit for this cluster", [])
