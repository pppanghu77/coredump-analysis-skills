---
name: coredump-code-management
description: 拉取崩溃对应的源代码并切换到指定版本。从Gerrit克隆仓库，配置hooks，切换到崩溃版本的git tag。用于：(1) 克隆指定包的源码仓库 (2) 切换到崩溃版本 (3) 批量下载多个包的源码 (4) 配置Gerrit提交环境。触发词：拉取源码、下载源码、切换版本、git clone、Gerrit克隆。
---

# Coredump 代码管理

从 Gerrit 拉取崩溃对应的源代码并切换到指定版本。

约定：以下命令示例中的 `$SKILLS_DIR` 表示当前 skill 的实际加载目录。

## ⚠️ 每次分析前必须检查账号配置

本 Skill 依赖 `accounts.json` 中的 Gerrit 账号配置。**在执行分析前**，请确认配置有效：

```bash
# 检查 Gerrit 账号
sed -n '1,160p' $SKILLS_DIR/accounts.json

# 测试 SSH 连接
ssh -T gerrit.uniontech.com
```

**Gerrit 账号失效会导致源码克隆失败**。

## 工作目录

工作目录由主流程自动创建，无需手动指定。

手动执行时设置环境变量：

```bash
export COREDUMP_WORKSPACE="$HOME/coredump-workspace-$(date +%Y%m%d-%H%M%S)"
mkdir -p $COREDUMP_WORKSPACE/3.代码管理
cd $COREDUMP_WORKSPACE/3.代码管理
```

## 脚本位置

```bash
$SKILLS_DIR/coredump-code-management/scripts/download_crash_source.sh
```

## 前置要求

- 用户需自行将 `~/.ssh/id_rsa.pub` 配置到 Gerrit 的设置-“SSH Keys”里面
- 配置 SSH 密钥到 Gerrit（`~/.ssh/id_rsa`）
- 有 Gerrit 仓库访问权限
- 已安装 git 和 scp

## 基本用法

### 单个包处理

```bash
# 从崩溃数据文件处理指定行
./download_crash_source.sh <crash_data_file> [line_number]

# 示例
./download_crash_source.sh ../2.数据筛选/filtered_crash_data.csv 2
```

**参数说明**：
- `crash_data_file`: 崩溃数据CSV文件路径
- `line_number`: 处理第几行（默认第2行，跳过表头）

### 批量处理

```bash
./batch_download_all.sh <crash_data_file>

# 示例
./batch_download_all.sh ../2.数据筛选/filtered_crash_data.csv
```

### 手动克隆

```bash
# 克隆仓库
PACKAGE="dde-control-center"
git clone ssh://ut000168@gerrit.uniontech.com:29418/${PACKAGE}

# 配置 hooks
scp -p -P 29418 ut000168@gerrit.uniontech.com:hooks/commit-msg ${PACKAGE}/.git/hooks/

# 切换版本
cd ${PACKAGE}
git checkout 5.7.41.11
```

## 版本号处理

脚本会自动清理版本号：

**原始版本** → **清理后版本**
- `1:5.7.41.10-1` → `5.7.41.10`
- `5.7.41.11-1` → `5.7.41.11`
- `5.7.41.12` → `5.7.41.12`

## 版本查找逻辑

1. **精确匹配**：查找完全匹配的 tag
2. **相似匹配**：如果找不到精确 tag，查找相似版本
3. **手动选择**：显示可用的 tag 列表

## 常用Git命令

```bash
# 查看当前版本
git describe --tags --exact-match

# 查看当前分支
git branch

# 查看所有tag
git tag

# 查看特定版本的tag
git tag | grep "^5.7"

# 创建修复分支
git checkout -b fix/issue-description origin/develop/eagle

# 提交代码
git add .
git commit -m "fix: 修复XX问题"
git review develop/eagle -r origin -T -y
```

## Gerrit配置

通过环境变量配置：

```bash
export GERRIT_USER="ut000168"
export GERRIT_HOST="gerrit.uniontech.com"
export GERRIT_PORT="29418"
```

## 目录结构

```
3.代码管理/
├── download_crash_source.sh     # 单个包处理脚本
├── batch_download_all.sh         # 批量处理脚本
├── dde-control-center/          # 源码仓库
│   ├── .git/
│   ├── src/
│   └── ...
├── dde-dock/                    # 源码仓库
└── ...
```

## 常见问题

**Q: 克隆失败，提示权限不足**

- 检查 SSH 密钥是否配置: `ls -la ~/.ssh/id_rsa`
- 确认用户已自行将 `~/.ssh/id_rsa.pub` 配置到 Gerrit 的设置-“SSH Keys”里面
- 测试连接: `ssh -T gerrit.uniontech.com`
- 确认 `accounts.json` 中 Gerrit 账号密码正确

**Q: 找不到对应的 git tag**

脚本会显示可用的 tag 列表，手动选择合适的版本。

**Q: hooks 配置失败**

不影响代码下载，但提交时需要手动添加 Change-Id。

**Q: 版本号格式不标准**

脚本会自动清理版本号中的 epoch 和 debian revision。

## 示例输出

**控制台输出示例**：
```
==========================================
📦 崩溃源码下载工具
==========================================
📄 正在读取崩溃数据文件...
  文件: /path/to/2.数据筛选/filtered_dde-dock_crash_data.csv

🔍 崩溃信息：
   行号: 2
   包名: dde-dock
   完整版本: 1:5.7.41.10-1
   清理版本: 5.7.41.10

📥 正在下载源代码...
Cloning into 'dde-dock'...
remote: Counting objects: 50000, done.
remote: Compressing objects: 100% (250/250), done.
Receiving objects: 100% (50000/50000), 50.00 MiB | 10.00 MiB/s

🔧 配置 commit-msg hooks...
✅ 代码下载完成

🔄 正在切换到版本: 5.7.41.10
   匹配到 tag: 5.7.41.10
HEAD is now at abc1234 Release 5.7.41.10

==========================================
✨ 完成！
==========================================
📂 工作目录: /path/to/3.代码管理/dde-dock
🔖 当前版本: 5.7.41.10
🌿 当前分支: (HEAD detached at 5.7.41.10)
==========================================
```

**版本查找输出示例**（精确匹配失败时）：
```
⚠️ 精确匹配失败: 5.7.41.10
正在查找相似版本...
找到以下可用 tag:
  5.7.41.9
  5.7.41.10
  5.7.41.11
  5.7.41.12
自动选择最接近的版本: 5.7.41.10 ✅
```
