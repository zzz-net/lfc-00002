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
- ✅ **完整审计**：init/import/merge/export/rollback 全记录，跨重启可查
- ✅ **快照回滚**：一键回滚到历史版本，无数据丢失
- ✅ **详细报告**：导出含来源批次、差异报告、SKU 维度明细

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
  {"sku": "SKU005", "300"}
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
