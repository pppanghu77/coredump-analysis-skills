#!/usr/bin/env python3
"""dde-launcher 自动修复元数据与 fix plan。

这里只描述"如何判定 target branch 是否已修复"以及未来可扩展的 auto_fixer 名称。
没有稳定机械修复方案的模式，不声明 auto_fixer。

对于大多数 dde-launcher 崩溃模式（QSocketNotifier、QHash、QPixmapCache、XCB），
崩溃点位于 Qt/libdbus 系统库中，无法直接定位到应用层源文件修改，采用保守策略。
"""

from pathlib import Path
from typing import Dict

from auto_fix_types import CrashCluster, FixPlan, FixResult
from fixers.common import apply_replacements, file_contains_all


def get_fix_specs() -> Dict[str, Dict]:
    return {
        "app_frame_detected": {
            "symbol_rules": [
                {
                    "symbol_contains": "DDciIconEngine",
                    "fixed_commits": ["b63c6f83", "6be02386"],
                    "auto_fixer": "cherry_pick_known_fix",
                    "preferred_commit": "b63c6f83",
                    "description": "Dci 图标引擎相关崩溃在 develop/eagle 已有图标加载空值保护修复",
                },
                {
                    "symbol_contains": "QDeepinTheme16createIconEngine",
                    "fixed_commits": ["b63c6f83", "6be02386"],
                    "auto_fixer": "cherry_pick_known_fix",
                    "preferred_commit": "b63c6f83",
                    "description": "QDeepinTheme 图标引擎创建链路崩溃在 develop/eagle 已有修复",
                },
                {
                    "symbol_contains": "DBuiltinIconEngine8loadIcon",
                    "fixed_commits": ["b63c6f83", "6be02386"],
                    "auto_fixer": "cherry_pick_known_fix",
                    "preferred_commit": "b63c6f83",
                    "description": "内置图标引擎加载崩溃在 develop/eagle 已有修复",
                },
                {
                    "symbol_contains": "QSvgIOHandlerPrivate4load",
                    "fixed_commits": ["2034c8b5", "d1ee4819"],
                    "auto_fixer": "cherry_pick_known_fix",
                    "preferred_commit": "2034c8b5",
                    "description": "SVG 读取链路崩溃在 develop/eagle 已有修复",
                },
                {
                    "symbol_contains": "XdgIconProxyEngine13pixmapByEntry",
                    "fixed_commits": ["2034c8b5"],
                    "auto_fixer": "cherry_pick_known_fix",
                    "preferred_commit": "2034c8b5",
                    "description": "XDG 图标代理渲染链路崩溃在 develop/eagle 已有修复",
                },
                {
                    "symbol_contains": "QPixmap4load",
                    "fixed_commits": ["6be02386", "b63c6f83"],
                    "auto_fixer": "cherry_pick_known_fix",
                    "preferred_commit": "6be02386",
                    "description": "QPixmap::load 图标加载崩溃在 develop/eagle 已有修复",
                },
                {
                    "symbol_contains": "QPixmapCache4find",
                    "fixed_commits": ["6be02386", "2034c8b5"],
                    "auto_fixer": "cherry_pick_known_fix",
                    "preferred_commit": "6be02386",
                    "description": "QPixmapCache/XDG 图标缓存链路崩溃在 develop/eagle 已有修复",
                },
                {
                    "symbol_contains": "QTimerInfoList14activateTimers",
                    "fixed_commits": ["15a0f827", "091918c2", "83c2f5cb"],
                    "auto_fixer": "cherry_pick_known_fix",
                    "preferred_commit": "15a0f827",
                    "description": "全屏定时刷新触发的 DBusDock 元对象访问崩溃在 develop/eagle 已有修复",
                },
                {
                    "symbol_contains_all": [
                        "QMetaObject8activateEP7QObjectiiPPv",
                        "sendPostedEventsEP7QObjectiP11QThreadData",
                    ],
                    "fixed_commits": ["6b9c61fb"],
                    "auto_fixer": "cherry_pick_known_fix",
                    "preferred_commit": "6b9c61fb",
                    "description": "析构后信号槽悬空导致的 posted events 激活崩溃在 develop/eagle 已有修复",
                },
                {
                    "symbol_contains_all": [
                        "QMetaObject8activateEP7QObjectiiPPv",
                        "sendMouseEventEP7QWidgetP11QMouseEvent",
                    ],
                    "fixed_commits": ["6b9c61fb"],
                    "auto_fixer": "cherry_pick_known_fix",
                    "preferred_commit": "6b9c61fb",
                    "description": "析构后信号槽悬空导致的鼠标事件激活崩溃在 develop/eagle 已有修复",
                },
                {
                    "symbol_contains": "DNativeSettings14createProperty",
                    "fixed_commits": ["93e0fc36", "71662deb"],
                    "auto_fixer": "cherry_pick_known_fix",
                    "preferred_commit": "93e0fc36",
                    "description": "平台插件 createProperty 跨线程元对象更新崩溃可映射到 XdgIconLoader 主线程预初始化修复",
                },
                {
                    "symbol_contains": "png_read_row",
                    "fixed_commits": ["d1ee4819"],
                    "auto_fixer": "cherry_pick_known_fix",
                    "preferred_commit": "d1ee4819",
                    "description": "图像读取健壮性问题在 develop/eagle 已有修复",
                },
            ],
        },
        "qsocketnotifier_event_loop": {
            "fixed_commits": ["e5689752"],
            "auto_fixer": "cherry_pick_known_fix",
            "preferred_commit": "e5689752",
            "description": "QSocketNotifier 生命周期崩溃在 develop/eagle 已有修复提交",
        },
        "qt_event_loop_unknown_symbol": {
            "fixed_commits": ["e5689752"],
            "auto_fixer": "cherry_pick_known_fix",
            "preferred_commit": "e5689752",
            "description": "Qt 事件循环/Notifier 类问题在 develop/eagle 已有对应修复",
        },
        "icon_pixmap_loading": {
            "fixed_commits": ["6be02386", "b63c6f83", "7072174f", "b53a7e69"],
            "auto_fixer": "cherry_pick_known_fix",
            "preferred_commit": "6be02386",
            "description": "图标/位图加载链路在 develop/eagle 已有多次修复",
        },
        "svg_icon_render": {
            "fixed_commits": ["2034c8b5"],
            "auto_fixer": "cherry_pick_known_fix",
            "preferred_commit": "2034c8b5",
            "description": "SVG 图标渲染崩溃在 develop/eagle 已有修复提交",
        },
        "rsvg_icon_render": {
            "fixed_commits": ["2034c8b5"],
            "auto_fixer": "cherry_pick_known_fix",
            "preferred_commit": "2034c8b5",
            "description": "SVG/rsvg 图标渲染崩溃在 develop/eagle 已有修复提交",
        },
        "dbus_warn_abort": {
            "symbol_rules": [
                {
                    "symbol_contains": "_dbus_warn_check_failed",
                    "fixed_commits": ["be28e0f0", "b2a0128e", "dfa8c8da"],
                    "auto_fixer": "cherry_pick_known_fix",
                    "preferred_commit": "be28e0f0",
                    "description": "冷启动 D-Bus 元对象访问崩溃可映射到 DBusDock 属性缓存修复",
                },
            ],
        },
        "dbus_dispatch_path": {
            "symbol_rules": [
                {
                    "symbol_contains": "dbus_message_get_path_decomposed",
                    "fixed_commits": ["be28e0f0", "b2a0128e", "dfa8c8da"],
                    "auto_fixer": "cherry_pick_known_fix",
                    "preferred_commit": "be28e0f0",
                    "description": "D-Bus 分发/路径解析链路崩溃可映射到 DBusDock 属性缓存修复",
                },
            ],
        },
    }


def build_fix_plan_for_cluster(cluster: CrashCluster) -> FixPlan:
    """根据 cluster.key 返回对应的 FixPlan。

    dde-launcher 的崩溃大部分发生在 Qt/libdbus 系统库内部，
    无法安全地在应用层源码定位到具体修改点，因此对已知模式
    采用 record_conservative_analysis_only 保守策略。
    仅对已有 cherry-pick 修复的模式标注可追溯的 commit 信息。
    """
    _conservative = FixPlan(
        cluster_id=cluster.cluster_id,
        action="record_conservative_analysis_only",
        confidence="low",
        target_files=[],
        commit_subject=f"[coredump-analysis] analyze: {cluster.title}",
        root_cause=f"{cluster.title} 已完成自动聚类，但当前本地源码中没有安全的直接修复点。"
                    f"崩溃发生在 Qt/libdbus 系统库内部，建议优先通过 cherry-pick 已知修复提交解决。",
        fix_description="记录自动分析结果，不修改源码。建议参考 get_fix_specs() 中列出的已知修复提交。",
        influence="请结合该根因簇的代表堆栈继续验证。",
    )

    plans = {
        # QSocketNotifier 相关崩溃 — 系统库内部，保守记录
        "qsocketnotifier-setenabled-crash": FixPlan(
            cluster_id=cluster.cluster_id,
            action="record_conservative_analysis_only",
            confidence="low",
            target_files=[],
            commit_subject="[coredump-analysis] analyze: QSocketNotifier::setEnabled 崩溃",
            root_cause="QSocketNotifier::setEnabled 调用时底层 socket 或 notifier 对象已失效，"
                       "崩溃发生在 Qt 事件循环内部，无法在应用层安全定位修改点。",
            fix_description="记录自动分析结果。已知 develop/eagle 分支存在修复提交 e5689752，"
                           "建议优先 cherry-pick。",
            influence="请重点验证 D-Bus 连接生命周期、冷启动和退出场景。",
        ),
        "qsocketnotifier-type-crash": FixPlan(
            cluster_id=cluster.cluster_id,
            action="record_conservative_analysis_only",
            confidence="low",
            target_files=[],
            commit_subject="[coredump-analysis] analyze: QSocketNotifier::type 崩溃",
            root_cause="QSocketNotifier::type 调用时 notifier 对象已被释放，"
                       "崩溃发生在 Qt 事件循环内部。",
            fix_description="记录自动分析结果。已知 develop/eagle 分支存在修复提交 e5689752，"
                           "建议优先 cherry-pick。",
            influence="请重点验证 D-Bus 连接生命周期和退出场景。",
        ),
        # QHash 内部除零崩溃 — 系统库内部
        "qhash-next-node-crash": FixPlan(
            cluster_id=cluster.cluster_id,
            action="record_conservative_analysis_only",
            confidence="low",
            target_files=[],
            commit_subject="[coredump-analysis] analyze: QHashData::nextNode 除零崩溃",
            root_cause="QHash 内部节点遍历时除零错误，通常由容器数据损坏导致，"
                       "崩溃位于 Qt 容器实现内部。",
            fix_description="记录自动分析结果。需要在运行时确认哈希容器使用场景后再手动排查。",
            influence="请重点验证启动阶段数据加载和容器初始化路径。",
        ),
        # QPixmapCache 崩溃 — 图标加载链路
        "pixmap-cache-find-crash": FixPlan(
            cluster_id=cluster.cluster_id,
            action="record_conservative_analysis_only",
            confidence="medium",
            target_files=[],
            commit_subject="[coredump-analysis] analyze: QPixmapCache::find 崩溃",
            root_cause="QPixmapCache::find 在图标缓存查找时触发非法内存访问，"
                       "通常由图标引擎或平台插件资源释放顺序问题导致。",
            fix_description="记录自动分析结果。已知 develop/eagle 分支存在多个修复提交"
                           "（6be02386, 2034c8b5, b63c6f83），建议优先 cherry-pick。",
            influence="请重点验证启动阶段图标加载、主题切换和缓存刷新路径。",
        ),
        # XCB 平台插件崩溃
        "deepin-platform-xcb-native-crash": FixPlan(
            cluster_id=cluster.cluster_id,
            action="record_conservative_analysis_only",
            confidence="low",
            target_files=[],
            commit_subject="[coredump-analysis] analyze: XCB 平台插件崩溃",
            root_cause="Deepin 平台插件 XCB native 资源在窗口操作时访问失效内存，"
                       "崩溃位于平台插件或 XCB 库内部。",
            fix_description="记录自动分析结果。崩溃发生在平台插件底层，无法安全定位应用层修改点。",
            influence="请重点验证窗口显示/隐藏、多屏切换和 X11 会话异常路径。",
        ),
    }

    return plans.get(cluster.key, _conservative)


def is_fix_present(code_dir: Path, plan: FixPlan) -> bool:
    """检查本地源码是否已包含等价修复。"""
    markers = {
        "apply_launcher_notifier_guard": (
            "controller/appcontroller.cpp",
            ["QSocketNotifier", "isEnabled()"],
        ),
    }
    marker = markers.get(plan.action)
    if not marker:
        return False
    relative_path, required_markers = marker
    return file_contains_all(code_dir / relative_path, required_markers)


def apply_fix_plan(code_dir: Path, plan: FixPlan) -> FixResult:
    """应用 dde-launcher 的修复计划。"""
    if is_fix_present(code_dir, plan):
        return FixResult(plan.cluster_id, plan.action, False,
                         "local source already contains equivalent fix", plan.target_files)

    actions = {
        "record_conservative_analysis_only": record_conservative_analysis_only,
    }
    action = actions.get(plan.action, record_conservative_analysis_only)
    return action(code_dir, plan)


def record_conservative_analysis_only(_code_dir: Path, plan: FixPlan) -> FixResult:
    """保守策略：不修改源码，仅记录分析结果。"""
    del _code_dir
    return FixResult(plan.cluster_id, plan.action, False,
                     "no safe local source edit for this cluster", [])
