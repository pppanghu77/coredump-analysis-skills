# 崩溃看板

只读看板,数据全部来自 `coredump-stack-clustering` pipeline 产出物 + 本地修复记录,无独立数据库、不可在前端编辑。

## 启动

```bash
cd coredump-stack-clustering/kanban
python3 server.py
# → http://127.0.0.1:8765/
```

## 数据源(全部只读)

| 数据 | 来源 | 说明 |
|------|------|------|
| hash 趋势/占比 | `<workspace>/3_version_analysis_results/_hash_trend_by_week.csv` | 跨周精确 hash 占比 |
| 崩溃率时间序列 | `<workspace>/1_download/<package>_summary_<周>.csv` | DB9 崩溃汇总(各版本率求和) |
| 修复记录 | `kanban/修复记录.csv` | 人工维护,MR ↔ hash 多对多 |

## 工作机制

### workspace 发现
扫描 `data/workspace_<package>_<start>_<end>`,应用(app)= package;同一 package 有多份 workspace 时自动取 end_date 最大者。

### 问题跟踪阈值
只跟踪**最新一周占比 ≥ 1%** 的 hash(`server.py` 中 `MIN_TRACK_PCT = 1.0`),过滤长尾噪声。看板卡片、趋势折线均基于此阈值。
饼图(`当前问题占比分布`)单独展示**完整长尾**(占比 > 0% 的全部 hash)。

### 看板两列

- **已修复 / 待验证** — 修复记录命中的问题(已提修复,待验证效果)
- **分析中** — 其余跟踪中的问题

### 修复记录(多对多,本地维护)

`修复记录.csv` 每行一个 `(gerrit_url, crash_hash)` 对:

- 一个 MR 修复多个问题 → 同一 url 写多行,每行一个 hash
- 一个问题被多个 MR 修复 → 同一 hash 写多行,每行一个 url
- `crash_hash` 可写 **8 位或 12 位**前缀(`a37ca347` 或 `a37ca347d13b` 均可)

命中的问题自动移到「已修复 / 待验证」列,详情里显示可点击的修复 MR 链接。修改该文件后 SSE 自动推送前端刷新,无需重启 server。

```csv
gerrit_url,crash_hash
https://gerrit.uniontech.com/c/dde-file-manager/+/356180,a37ca347
https://gerrit.uniontech.com/c/dde-file-manager/+/356180,769c513bd3ac
https://gerrit.uniontech.com/c/dde-file-manager/+/345752,b5426e4e
```

> 注:`修复记录.csv` 已加入 `.gitignore`,不入库,各自本地维护。

## 交互

- 点击**占比趋势图**的任意一条线 → 弹出该问题完整详情(概要、完整堆栈、历史占比、修复 MR)
- 点击**饼图**任意扇区(含长尾)→ 同样弹详情
- 卡片右上角「选择问题类型」下拉控制趋势折线的显隐
- 数据文件变更后页面自动刷新(SSE)

## API

| 接口 | 说明 |
|------|------|
| `GET /api/apps` | 应用(package)列表 |
| `GET /api/issues?app=X` | 跟踪的问题(≥1%),含修复记录命中的状态 |
| `GET /api/trend?app=X` | 各 hash 周占比趋势(≥1%) |
| `GET /api/distribution?app=X` | 全量 hash 分布(饼图长尾,>0%) |
| `GET /api/summary?app=X` | 崩溃率时间序列 |
| `GET /api/events` | SSE 数据变更推送 |
| `POST *` | 只读模式,返回 403 |

## 文件清单

| 文件 | 作用 |
|------|------|
| `server.py` | 只读看板服务器(端口 8765),读 workspace + 修复记录 |
| `index.html` | ECharts 前端(崩溃率折线 / 占比趋势 / 饼图 / 看板列) |
| `修复记录.csv` | 人工维护的 MR↔hash 修复映射(`.gitignore` 忽略) |
