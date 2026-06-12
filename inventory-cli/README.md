# Offline Inventory Counting Merge CLI

本地优先的离线库存盘点合并工具。支持多门店盘点数据导入、按策略合并冲突、导出含来源批次的报告，并提供完整审计历史和回滚能力。

## 技术栈

- **Python 3.10+**
- **Typer** - CLI 框架
- **SQLite** - 本地持久化（零配置）
- 零外部服务依赖，所有数据本地存储

## 核心特性

- ✅ 导入 **CSV** 和 **JSON** 盘点表
- ✅ **5 种冲突策略**：require_manual / first / last / sum / average
- ✅ **严格原子性**：校验失败零写入，不污染快照
- ✅ **3 层配置**：命令行 > 配置文件 > SQLite 持久化
- ✅ **完整审计**：init/import/merge/export/rollback/config 全记录，跨重启可查
- ✅ **审计导出**：按时间范围和操作类型筛选，导出 CSV/JSON 审计日志
- ✅ **快照回滚**：一键回滚到历史版本，无数据丢失
- ✅ **详细报告**：导出含来源批次、差异报告、SKU 维度明细
- ✅ **历史清理**：按日期或保留数量清理旧快照和孤儿批次，支持预演模式

---

## 快速安装

```powershell
# 进入项目目录
cd inventory-cli

# 安装依赖（建议虚拟环境）
python -m pip install -e .
# 或者
python -m pip install typer>=0.12.0 click>=8.0,<8.2 rich pydantic python-dotenv
```

验证安装：
```powershell
python -m inventory_cli.cli --help
```

---

## 配置文件说明

### 配置格式（JSON）

`inventory init` 会在当前目录生成示例配置 `inventory.config.json`：

```json
{
  "description": "Offline Inventory CLI Configuration File",
  "conflict_strategy": "require_manual",
  "validation": {
    "negative_quantities": true,
    "required_columns": true,
    "duplicate_sku": true
  }
}
```

### 字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| `conflict_strategy` | string | 跨门店同 SKU 冲突策略，见下文 |
| `validation.negative_quantities` | bool | 是否拒绝负库存（默认 true） |
| `validation.required_columns` | bool | 是否强制要求 `sku` + `quantity` 列（默认 true） |
| `validation.duplicate_sku` | bool | 是否拒绝同批次重复 SKU（默认 true） |

### 冲突策略（conflict_strategy）

| 策略 | 说明 |
|------|------|
| **require_manual** | **默认 & 推荐**。存在任何跨门店 SKU 数量冲突时**直接失败**，不静默覆盖。最安全。 |
| `first` | 采用最早导入门店的数量 |
| `last` | 采用最晚导入门店的数量 |
| `sum` | 保留各门店各自数量，不做跨门店合并 |
| `average` | 取所有门店数量平均值（向下取整），应用到每个门店 |

### 配置优先级（从高到低）

1. **命令行参数**（如 `--strategy sum`）
2. `--config` 指定的 JSON 配置文件
3. 当前目录默认配置 `./inventory.config.json`（如果存在）
4. SQLite 数据库中持久化的配置（通过 `inventory config` 修改）
5. 代码内置默认值（`require_manual`）

---

## 完整使用流程

以下命令均为**真实可执行**。

### 1. 初始化仓库

```powershell
# 初始化 SQLite 数据库 + 生成示例配置
python -m inventory_cli.cli init

# 指定数据库路径，强制覆盖已有配置
python -m inventory_cli.cli init --database ./data/stores.db --force

# 跳过配置文件生成
python -m inventory_cli.cli init --config ''
```

初始化后当前目录会生成：
- `inventory.db` - SQLite 数据库
- `inventory.config.json` - 示例配置文件（可编辑）

### 2. 查看配置

```powershell
# 查看所有配置
python -m inventory_cli.cli config

# 修改 SQLite 持久化配置
python -m inventory_cli.cli config conflict_strategy sum
python -m inventory_cli.cli config validate_negative false
```

### 3. 导入盘点数据

**准备数据文件：**

`store_a.csv`（A 门店盘点结果）：
```csv
sku,quantity
SKU001,100
SKU002,50
SKU003,75
SKU004,200
```

`store_b.json`（B 门店盘点结果）：
```json
[
  {"sku": "SKU001", "quantity": 100},
  {"sku": "SKU002", "quantity": 60},
  {"sku": "SKU003", "quantity": 75},
  {"sku": "SKU005", "quantity": 150}
]
```

**导入命令：**

```powershell
# 导入 CSV
python -m inventory_cli.cli import tests/store_a.csv STORE001 --batch batch_store_a

# 导入 JSON，指定配置文件
python -m inventory_cli.cli import tests/store_b.json STORE002 --batch batch_store_b --config tests/config_sum.json

# 查看已导入批次
python -m inventory_cli.cli batches
```

### 4. 按配置合并

**场景 1：使用默认 require_manual 策略（有冲突会失败）**

```powershell
# 使用默认配置（require_manual），会失败（SKU002 是 50 vs 60）
python -m inventory_cli.cli merge
```

**场景 2：使用配置文件指定 sum 策略**

```powershell
# 通过配置文件指定策略
python -m inventory_cli.cli merge --config tests/config_sum.json

# 或者直接命令行指定（优先级最高）
python -m inventory_cli.cli merge --strategy sum
```

**场景 3：合并指定批次**

```powershell
# 只合并 batch_store_a 和 batch_store_b
python -m inventory_cli.cli merge batch_store_a batch_store_b --strategy average
```

### 5. 导出合并结果

```powershell
# 导出 CSV（默认导出最新快照）
python -m inventory_cli.cli export output/merged.csv

# 导出 JSON，含来源批次元数据
python -m inventory_cli.cli export output/merged.json

# 导出完整报告，含差异分析、来源批次
python -m inventory_cli.cli export output/merged.report.json
```

### 6. 查看操作历史

```powershell
# 查看最近 50 条操作
python -m inventory_cli.cli history -n 50

# 查看指定批次相关操作
python -m inventory_cli.cli history --batch batch_store_a
```

### 7. 回滚到历史版本

```powershell
# 列出所有快照（ID 用于回滚）
python -m inventory_cli.cli rollback

# 回滚到快照 #1（sum 策略版本）
python -m inventory_cli.cli rollback 1

# 再次导出 → 回到快照 #1 版本
python -m inventory_cli.cli export output/after_rollback.csv
```

### 8. 历史数据清理（prune）

长期使用后会积累大量快照和批次数据，使用 `prune` 命令按规则清理。

> **⚠️ 危险操作提示：删除不可恢复。强烈建议每次清理前先用 `--dry-run` 预演。**

#### 8.1 命令总览

```
prune [--before TIME] [--keep N] [--prune-orphans] [--dry-run] [--database PATH]
```

**至少需要指定 `--before` 或 `--keep` 中的一个。** 同时指定两者时，满足任一条件的快照都会被删除（取并集）。

| 参数 | 说明 |
|------|------|
| `--before <TIME>` | 删除创建时间早于该时间的快照。支持 ISO 格式：`2025-01-01` 或 `2025-01-01T10:00:00` |
| `--keep <N>` | 只保留最近 N 个快照，更早的全部删除。N 为 0 时清空所有快照 |
| `--prune-orphans` | 同时删除不再被任何保留快照引用的批次数据（inventory 表中的原始记录） |
| `--dry-run` | 预演模式，只显示将要删除的内容，**不做任何实际修改** |
| `--database <PATH>` | 指定数据库文件路径，默认 `inventory.db` |

#### 8.2 第一步：先预演（dry-run）

清理前务必先用 `--dry-run` 看清楚会删什么：

```powershell
# 只看快照删除情况（推荐先跑这个）
python -m inventory_cli.cli prune --dry-run --keep 3

# 同时看看哪些批次会被清理
python -m inventory_cli.cli prune --dry-run --keep 3 --prune-orphans
```

输出示例：

```
=== DRY RUN - No changes will be made ===

Snapshots to delete (2):
------------------------------------------------------------------------------------------
  ID  Created At            Batch ID                       Records
------------------------------------------------------------------------------------------
   2  2025-01-15 10:30:00   merged_20250115_103000               8
   1  2025-01-10 14:20:00   merged_20250110_142000               8

Batches to delete (1):
  - old_batch_202412  (orphan)

Note: 2 batches are still referenced by retained snapshots and will NOT be deleted:
  - batch_store_a
  - batch_store_b

Summary: Would delete 2 snapshots and 1 batches
Remove --dry-run to execute the prune operation.
```

确认无误后，去掉 `--dry-run` 实际执行。

#### 8.3 只清理快照（保留批次数据）

只删除旧快照，不碰原始批次数据。安全保守，推荐先用这个。

```powershell
# 只保留最近 5 个快照
python -m inventory_cli.cli prune --keep 5

# 删除 2025-01-01 之前的所有快照（含当天全天）
python -m inventory_cli.cli prune --before 2025-01-01

# 删除 2025-01-01 中午 12 点之前的快照
python -m inventory_cli.cli prune --before 2025-01-01T12:00:00

# 组合条件：保留最近 10 个，且删除 2024 年底前的（取并集）
python -m inventory_cli.cli prune --keep 10 --before 2024-12-31
```

执行成功输出：

```
=== PRUNE COMPLETED ===
Successfully deleted 2 snapshots
Deleted snapshot IDs: [1, 2]
Operation recorded in history. Use 'history' to view.
```

#### 8.4 连孤儿批次一起清理

加上 `--prune-orphans` 会同时删除不再被任何保留快照引用的批次数据。

> **什么是孤儿批次？** 导入了但从未合并进快照，或者所在的快照全部被删了，导致没有任何快照再引用的批次。

```powershell
# 保留最近 3 个快照，同时清理孤儿批次
python -m inventory_cli.cli prune --keep 3 --prune-orphans

# 先预演一下会删哪些批次
python -m inventory_cli.cli prune --dry-run --keep 3 --prune-orphans
```

**注意：如果某个批次仍被保留的快照引用，即使它出现在待删除的快照里，也不会被删。** CLI 会明确提示哪些批次因为被保留快照引用而跳过。

#### 8.5 清理后验证

```powershell
# 查看操作记录（prune 已写入历史）
python -m inventory_cli.cli history

# 查看剩余快照
python -m inventory_cli.cli rollback

# 查看剩余批次
python -m inventory_cli.cli batches

# 导出验证（确保当前数据完整）
python -m inventory_cli.cli export output/after_prune.csv
```

清理动作是**原子**的 —— 要么全部成功，要么全部回滚，不会留下半清理状态。

---

## 错误场景说明

所有校验失败场景**均不会污染数据库或快照**：

| 场景 | 行为 |
|------|------|
| 缺少 `sku` 或 `quantity` 列 | 导入失败，0 记录写入 |
| 负库存（quantity < 0） | 导入失败，0 记录写入 |
| 未知格式（.txt/.xlsx 等） | 导入失败，0 记录写入 |
| 同批次重复 SKU 数量不一致 | 导入失败，0 记录写入 |
| 配置文件 JSON 语法错误 | merge/import 失败，无数据变更 |
| 配置文件 strategy 非法 | merge/import 失败，无数据变更 |
| require_manual + 跨门店冲突 | merge 失败，不创建快照 |

---

## 所有命令速查

```powershell
# 初始化
inventory init [--database PATH] [--config PATH] [--force]

# 导入
inventory import FILE STORE_ID [--batch BATCH] [--config CONFIG] [--database PATH]

# 合并
inventory merge [BATCH1 BATCH2 ...] [--strategy STRATEGY] [--config CONFIG] [--database PATH]

# 导出
inventory export OUTPUT_FILE [--batch BATCH] [--diff/--no-diff] [--database PATH]

# 历史
inventory history [-n LIMIT] [--batch BATCH] [--database PATH]

# 回滚
inventory rollback [SNAPSHOT_ID] [--database PATH]

# 配置
inventory config [KEY] [VALUE] [--database PATH]

# 审计日志导出
inventory audit-log OUTPUT [--from TIME] [--to TIME] [--type TYPES] [--database PATH]

# 批次
inventory batches [--database PATH]
```

---

## 运行测试

```powershell
# 运行端到端测试（全流程）
python tests/test_e2e.py

# 运行配置文件回归测试
python tests/test_config.py

# 运行 prune 历史清理回归测试
python tests/test_prune.py
```

---

## 项目结构

```
inventory-cli/
├── src/inventory_cli/
│   ├── cli.py          # 主 CLI 入口
│   ├── config.py       # 配置管理器（含文件加载）
│   ├── db.py           # SQLite 数据访问
│   ├── importer.py     # CSV/JSON 导入 + 校验
│   ├── merger.py       # 合并引擎 + 冲突检测
│   ├── exporter.py     # 导出引擎
│   └── models.py       # 数据模型
├── tests/
│   ├── store_a.csv / store_b.json   # 示例数据
│   ├── config_*.json                # 测试配置文件
│   ├── test_e2e.py                  # 端到端测试
│   └── test_config.py               # 配置回归测试
└── README.md
```
