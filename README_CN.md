# AWS 中国区定价查询 Skill

[🇺🇸 English](README.md)

一个 OpenClaw Skill，用于查询 AWS 中国区服务价格、计算成本和生成报价单。覆盖北京区 (cn-north-1)、宁夏区 (cn-northwest-1) 和 Auto Cloud Local Zone (cn-north-1-pkx-1) 的 95+ 个服务。

## 功能特性

- **智能导入** — 自然语言服务描述自动映射为 AWS ServiceCode（80+ 条规则）
- **实时价格查询** — 通过 AWS Price List API 查询任意服务定价
- **完整 RI 覆盖** — Standard & Convertible RI，1年/3年期，无预付/部分预付/全预付（12 种组合）
- **Savings Plans** — Compute SP + EC2 Instance SP 定价及对比
- **EDP/PPA 折扣** — 企业折扣计划和私有定价折扣，支持配置叠加顺序
- **批量成本计算** — 导入 CSV/Excel 工作负载，计算整体方案成本
- **Excel 报价单** — 生成正式报价单，含客户信息、有效期、明细和汇总
- **规格推荐** — 根据 vCPU/内存需求推荐最优实例类型，按性价比排序
- **数据传输费** — 出公网（阶梯定价）、跨 AZ、同区域、CloudFront 分发
- **双区域对比** — 北京 vs 宁夏同配置价格并列对比
- **税费支持** — 可选 6% 增值税（中国区云服务税率）
- **价格缓存** — Bulk API 下载 + 索引化本地缓存，增量更新

## 前置条件

- **AWS CLI** 已配置中国区 profile
- **Python 3.10+**
- **pip 依赖**: `openpyxl`, `pyyaml`

```bash
pip install openpyxl pyyaml
```

### AWS CLI 配置

Skill 需要名为 `cn-north-1` 的 profile：

```ini
# ~/.aws/credentials
[cn-north-1]
aws_access_key_id = 你的AK
aws_secret_access_key = 你的SK

# ~/.aws/config
[profile cn-north-1]
region = cn-north-1
```

> **说明**: Pricing API 的 endpoint 在 `cn-northwest-1`，但使用任一中国区域的凭证即可。

## 快速开始

### 0. 智能导入（自然语言输入）

不需要知道精确的 AWS ServiceCode，直接描述你的需求：

```csv
类型,规格,数量,备注
计算,8C16G,20,Web服务器
MySQL数据库,4C32G,2,业务库
Redis缓存,4G内存,3,Session缓存
对象存储,1TB,,文件存储
Kafka消息队列,,2,异步消息
```

```bash
# 转换为标准格式
python3 scripts/smart_import.py --input raw_workload.csv --output standardized.csv --region cn-north-1

# 或直接计算成本
python3 scripts/smart_import.py --input raw_workload.csv --region cn-north-1 --calculate
```

支持 80+ 条映射规则，覆盖全部 95 个中国区服务，自动识别：
- 引擎类型：“MySQL” → engine=MySQL，“Redis” → engine=Redis
- 实例规格：“8C16G” → vCPU=8, memory=16 → 自动推荐最优实例
- 存储容量：“1TB” → storage_gb=1024

### 1. 查询单个服务价格

```bash
# EC2 实例价格
python3 scripts/query_price.py -s AmazonEC2 -r cn-north-1 \
  -f instanceType=c6i.xlarge operatingSystem=Linux tenancy=Shared \
     capacitystatus=Used preInstalledSw=NA

# RDS 价格
python3 scripts/query_price.py -s AmazonRDS -r cn-north-1 \
  -f instanceType=db.r6g.xlarge databaseEngine=MySQL

# 完整费率对比（On-Demand vs RI vs Savings Plans）
python3 scripts/query_price.py -s AmazonEC2 -r cn-north-1 \
  -f instanceType=c6i.xlarge operatingSystem=Linux tenancy=Shared \
     capacitystatus=Used preInstalledSw=NA \
  --compare --savings-plans
```

### 2. 规格推荐

```bash
# 通用型，8 vCPU，32 GB 内存
python3 scripts/recommend_instance.py --vcpu 8 --memory 32 --region cn-north-1

# 计算密集型
python3 scripts/recommend_instance.py --vcpu 4 --memory 16 --workload compute --region cn-northwest-1
```

### 3. 批量成本计算

```bash
# 从 CSV 文件计算
python3 scripts/calculate_cost.py --input workload.csv --region cn-north-1

# 含 EDP/PPA 折扣
python3 scripts/calculate_cost.py --input workload.csv --region cn-north-1 \
  --discount-config discount-config.yaml

# 含 6% 增值税
python3 scripts/calculate_cost.py --input workload.csv --region cn-north-1 --include-tax
```

### 4. 生成 Excel 报价单

```bash
python3 scripts/generate_quote.py --input workload.csv --region cn-north-1 \
  --customer "客户公司名称" --validity 30 --output quote.xlsx
```

### 5. 更新价格缓存

```bash
# 更新某区域所有服务
python3 scripts/update_prices.py --region cn-north-1

# 只更新特定服务
python3 scripts/update_prices.py --region cn-north-1 --services AmazonEC2,AmazonRDS

# 强制重新下载
python3 scripts/update_prices.py --region cn-north-1 --force
```

> **重要**: Savings Plans 数据必须先通过 `update_prices.py` 下载，才能查询 SP 价格（SP 数据不在 Query API 中）。

## CSV 输入格式

```csv
service,region,instance_type,os,engine,quantity,hours_per_month,billing_mode,transfer_type,transfer_gb,notes
AmazonEC2,cn-north-1,c6i.xlarge,Linux,,10,730,on-demand,,,Web 服务器
AmazonEC2,cn-north-1,m6i.2xlarge,Linux,,5,730,ri-standard-1yr-partial,,,应用服务器
AmazonRDS,cn-north-1,db.r6g.xlarge,,MySQL,2,730,on-demand,,,数据库
AmazonEC2,cn-north-1,,,,1,,on-demand,out_to_internet,5000,出公网 5TB
```

完整字段说明见 [references/input-format.md](references/input-format.md)。

## 折扣配置

编辑 `discount-config.yaml`：

```yaml
edp:
  enabled: true
  discount_pct: 8  # 8% EDP 折扣

ppa:
  enabled: true
  rules:
    - service: AmazonEC2
      discount_pct: 10
    - service: AmazonRDS
      discount_pct: 5

discount_stack_order:
  - ppa   # 先应用 PPA
  - edp   # 再叠加 EDP

tax:
  vat_rate: 6
  include_tax: false  # 默认不含税
```

折扣模型详解见 [references/discount-models.md](references/discount-models.md)。

## 数据源优先级

| 优先级 | 数据源 | 说明 |
|--------|--------|------|
| 1 | Price List Query API | 实时精确查询 |
| 2 | 本地缓存 (Bulk API) | 预下载 + 索引化的 JSON 文件 |

两个数据源都无结果时，工具会提示运行 `update_prices.py` 更新缓存。

## 项目结构

```
aws-china-pricing/
├── SKILL.md                    # OpenClaw Skill 入口
├── discount-config.yaml        # EDP/PPA 折扣配置
├── scripts/
│   ├── smart_import.py         # 智能导入（自然语言 → AWS 服务映射）
│   ├── query_price.py          # 核心查价（API + 缓存降级）
│   ├── calculate_cost.py       # 批量成本计算引擎
│   ├── update_prices.py        # 价格数据更新（Bulk API + 索引）
│   ├── generate_quote.py       # Excel 报价单生成
│   └── recommend_instance.py   # 实例规格推荐
├── references/
│   ├── discount-models.md      # EDP/PPA/RI/SP 折扣模型详解
│   ├── service-catalog.md      # 中国区服务特殊说明
│   └── input-format.md         # CSV/Excel 输入格式规范
├── assets/                     # 模板文件
└── data/                       # 价格缓存（自动生成）
    ├── cache/                  # Bulk API 原始下载
    └── index/                  # 按实例族索引的小文件
```

## 覆盖区域

| 区域代码 | 名称 | 运营方 |
|----------|------|--------|
| cn-north-1 | 北京区 | 光环新网 (Sinnet) |
| cn-northwest-1 | 宁夏区 | 西云数据 (NWCD) |
| cn-north-1-pkx-1 | Auto Cloud Local Zone | — |

## 许可证

MIT
