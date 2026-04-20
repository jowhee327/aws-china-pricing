# AWS 中国区定价查询 Skill

[🇺🇸 English](README_EN.md)

一个 Agent Skill，用于查询 AWS 中国区服务价格、计算成本和生成报价单。覆盖北京区 (cn-north-1)、宁夏区 (cn-northwest-1) 和 Auto Cloud Local Zone (cn-north-1-pkx-1) 的 87 个服务。

## 功能特性

- **智能导入** — 任意格式 Excel/CSV 自动识别
- **实时价格查询** — 87 个服务
- **RI/SP 支持** — Standard/Convertible RI + Compute/Instance SP
- **Extended Support 延长支持** — EKS / RDS / ElastiCache / OpenSearch 共 4 个服务的 ES 附加费自动计算
- **折扣支持** — EDP/PPA
- **Excel 报价单生成**
- **实例推荐**

## 前置条件

- **AWS CLI** 已配置并有中国区访问权限
- **Python 3.10+**
- **pip 依赖**: `openpyxl`, `pyyaml`

```bash
pip install openpyxl pyyaml
```

> **说明**: 工具自动使用 AWS CLI 默认 profile，无需手动指定 --profile。Pricing API 的 endpoint 在 `cn-northwest-1`，使用任一中国区域的凭证即可。

## 快速开始

### 0. 一键生成 Excel 报价单（推荐）

输入 Excel/CSV，一条命令直接输出正式 Excel 报价单：

```bash
# 最简用法：输入 Excel，输出 {文件名}_报价单.xlsx
python3 scripts/smart_import.py --input workload.xlsx --region cn-north-1

# 指定客户名称
python3 scripts/smart_import.py --input workload.xlsx --region cn-north-1 \
  --customer "客户公司名称"

# 含 6% 增值税
python3 scripts/smart_import.py --input workload.xlsx --region cn-north-1 \
  --include-tax

# 指定计费模式
python3 scripts/smart_import.py --input workload.xlsx --region cn-north-1 \
  --billing-mode ri-standard-1yr-partial
```

不需要知道精确的 AWS ServiceCode，直接描述你的需求：

```csv
类型,规格,数量,备注
计算,8C16G,20,Web服务器
MySQL数据库,4C32G,2,业务库
Redis缓存,4G内存,3,Session缓存
对象存储 Standard,1TB,,文件存储
EBS gp3,500GB,,系统盘
Kafka消息队列,,2,异步消息
Lambda 函数,,1000万次/月,按量计费
```

支持 80+ 条映射规则，覆盖全部 87 个中国区服务，自动识别：
- 引擎类型："MySQL" → engine=MySQL，"Redis" → engine=Redis
- 实例规格："8C16G" → vCPU=8, memory=16 → 自动推荐最优实例
- 存储容量："1TB" → storage_gb=1024
- S3 存储类别："Standard"/"IA"/"Glacier" 等
- EBS 卷类型："gp3"/"io2"/"st1" 等

### 1. 查询单个服务价格

```bash
# EC2 实例价格
python3 scripts/query_price.py -s AmazonEC2 -r cn-north-1 \
  -f instanceType=c6i.xlarge operatingSystem=Linux tenancy=Shared \
     capacitystatus=Used preInstalledSw=NA

# RDS 价格
python3 scripts/query_price.py -s AmazonRDS -r cn-north-1 \
  -f instanceType=db.r6g.xlarge databaseEngine=MySQL

# EBS 价格（独立服务）
python3 scripts/query_price.py -s AmazonEBS -r cn-north-1 \
  -f volumeType=gp3

# S3 不同存储类别价格
python3 scripts/query_price.py -s AmazonS3 -r cn-north-1 \
  -f storageClass=Standard
python3 scripts/query_price.py -s AmazonS3 -r cn-north-1 \
  -f storageClass=StandardInfrequentAccess

# 完整费率对比（On-Demand vs RI vs Savings Plans）
python3 scripts/query_price.py -s AmazonEC2 -r cn-north-1 \
  -f instanceType=c6i.xlarge operatingSystem=Linux tenancy=Shared \
     capacitystatus=Used preInstalledSw=NA \
  --compare --savings-plans

# 指定计费模式查询
python3 scripts/query_price.py -s AmazonEC2 -r cn-north-1 \
  -f instanceType=c6i.xlarge operatingSystem=Linux \
  --billing-mode ri-convertible-3yr-all
```

### 2. 规格推荐

```bash
# 通用型，8 vCPU，32 GB 内存
python3 scripts/recommend_instance.py --vcpu 8 --memory 32 --region cn-north-1

# 计算密集型，指定计费模式
python3 scripts/recommend_instance.py --vcpu 4 --memory 16 --workload compute \
  --region cn-northwest-1 --billing-mode sp-compute-1yr
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

# 指定默认计费模式
python3 scripts/calculate_cost.py --input workload.csv --region cn-north-1 \
  --billing-mode ri-standard-1yr-partial
```

### 4. 生成 Excel 报价单

```bash
python3 scripts/generate_quote.py --input workload.csv --region cn-north-1 \
  --customer "客户公司名称" --validity 30 --output quote.xlsx \
  --billing-mode ri-standard-1yr-partial
```

### 5. 更新价格缓存

```bash
# 更新某区域所有服务
python3 scripts/update_prices.py --region cn-north-1

# 只更新特定服务
python3 scripts/update_prices.py --region cn-north-1 --services AmazonEC2,AmazonRDS,AmazonEBS

# 强制重新下载
python3 scripts/update_prices.py --region cn-north-1 --force
```

> **重要**: Savings Plans 数据必须先通过 `update_prices.py` 下载，才能查询 SP 价格（SP 数据不在 Query API 中）。


## CSV 输入格式

```csv
service,region,instance_type,os,engine,quantity,hours_per_month,billing_mode,storage_gb,storage_class,volume_type,transfer_type,transfer_gb,notes
AmazonEC2,cn-north-1,c6i.xlarge,Linux,,10,730,ri-standard-1yr-partial,,,,,,"Web 服务器"
AmazonRDS,cn-north-1,db.r6g.xlarge,,MySQL,2,730,on-demand,,,,,,"数据库"
AmazonEBS,cn-north-1,,,,5,,on-demand,500,,gp3,,,"系统盘"
AmazonS3,cn-north-1,,,,1,,on-demand,1024,Standard,,,,"对象存储"
AmazonS3,cn-north-1,,,,1,,on-demand,500,StandardInfrequentAccess,,,,"归档存储"
AWSLambda,cn-north-1,,,,10000000,,pay-per-use,,,,,,"按量计费函数"
AmazonEC2,cn-north-1,,,,1,,on-demand,,,,,out_to_internet,5000,"出公网 5TB"
```

完整字段说明见 [references/input-format.md](references/input-format.md)。



## Extended Support（延长支持）

中国区 **EKS / RDS / ElastiCache / OpenSearch** 四个服务支持 Extended Support 延长支持附加费，在 on-demand/RI/SP 单价基础上叠加。

### 覆盖服务

| 服务 | 计费维度 | Yr1-Yr2 单价（北京示例） | Yr3 单价 |
|------|----------|---------------------------|----------|
| EKS | cluster-hour | ¥3.44/hr/cluster | ¥3.44/hr/cluster |
| RDS | vCPU × hour | ¥0.974/vCPU-hr | ¥1.948/vCPU-hr（× 2）|
| ElastiCache | node × hour | cache.r6g.large ¥1.584/hr | Yr1-Yr2 × 2 |
| OpenSearch | NIH × hour（flat，无年限分档）| 北京 ¥0.0603/NIH，宁夏 ¥0.0432/NIH | — |

### 支持的引擎/版本

- **RDS**：MySQL 5.7、PostgreSQL 10/11/12、Aurora MySQL 2、Aurora PostgreSQL 11/12
- **ElastiCache**：Redis 6.x / 5.x 等旧版本（Memcached、Valkey 会自动识别并阻断 ES 附加费）
- **OpenSearch**：支持 `.search` 和 `.elasticsearch` 后缀，裸名（如 `r5.large`）自动补全

### CSV/Excel 触发方式

新增以下列即可自动计算 ES 附加费：

| 列名 | 取值 | 说明 |
|------|------|------|
| `extended_support` | `yr1-2` / `yr3` | 延长支持档位；OpenSearch 忽略档位 |
| `engine_version` | `5.7` / `11` / `12` / `6.x` 等 | 引擎版本，用于匹配 ES SKU |
| `deployment_option` | `Single-AZ`（默认） / `Multi-AZ` | RDS 专用 |

兼容的中文列名：`延长支持`、`扩展支持`、`引擎版本`、`版本`。

示例：

```csv
service,region,instance_type,engine,engine_version,extended_support,quantity,hours_per_month,billing_mode
AmazonRDS,cn-north-1,db.r6g.xlarge,MySQL,5.7,yr1-2,2,730,on-demand
AmazonElastiCache,cn-north-1,cache.r6g.large,Redis,6.x,yr1-2,3,730,on-demand
AmazonEKS,cn-north-1,,,,yr1-2,1,730,on-demand
AmazonOpenSearchService,cn-north-1,r5.xlarge.search,,,yr1-2,2,730,on-demand
```

### 智能识别

`smart_import.py` 会根据关键词自动识别 ES：

- 关键词：`延长支持`、`扩展支持`、`Extended Support`、`Ext Support`
- 档位：`Yr3`、`第3年` → `yr3`；默认 `yr1-2`
- 如检测到旧引擎版本（如 MySQL 5.7）但未标注 ES，会输出 warning 提示

### 报价单输出

ES 作为独立的明细行列出（服务名显示 `XXX Extended Support (Yr1-Yr2/Yr3)`），并使用 Excel 公式 `=H*F` 让金额随数量/时长自动联动。ES 查价独立于基础实例查价 —— 即使基础价查不到，ES 附加费也不会被静默丢失。

## 折扣配置

编辑 `discount-config.yaml`：

```yaml
edp:
  enabled: true
  discount_pct: 8  # 8% EDP 折扣，显示在报价单头部

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

## 87 个中国区服务

支持所有 87 个 AWS 中国区服务的价格查询，统一显示名规范：

| 服务类别 | 主要服务 | 显示名 |
|----------|----------|--------|
| 计算 | AmazonEC2 | EC2 |
| | AWSLambda | Lambda |
| | AmazonECS | ECS |
| 数据库 | AmazonRDS | RDS |
| | AmazonDynamoDB | DynamoDB |
| | AmazonElastiCache | ElastiCache |
| 存储 | AmazonS3 | S3 |
| | AmazonEBS | EBS |
| | AmazonEFS | EFS |
| 网络 | AmazonVPC | VPC |
| | AmazonCloudFront | CloudFront |
| | ElasticLoadBalancing | ELB |

完整服务列表见 [references/service-catalog.md](references/service-catalog.md)。

## 项目结构

```
aws-china-pricing/
├── SKILL.md                    # Skill 入口
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


## Changelog

### v1.10.1（修复）
- ES 查价独立于基础实例查价：基础价查不到时，ES 附加费不再静默丢失
- 报价单 ES 行金额列改为 Excel 公式 `=H*F`，数量/时长变动自动联动

### v1.10（ElastiCache + OpenSearch Extended Support）
- **ElastiCache Extended Support**：Redis 6.x/5.x 等旧版本，按 per-node-hour 计费；Yr1-Yr2 / Yr3（Yr3 = Yr1-Yr2 × 2）；CNN1 128 个 SKU + CNW1 108 个 SKU 全覆盖；Memcached / Valkey 自动识别并阻断 ES
- **OpenSearch Extended Support**：flat SKU（无年限分档），北京 ¥0.0603/NIH、宁夏 ¥0.0432/NIH；NIH 归一化（large=4、xlarge=8、2xlarge=16…）；支持 `.search`/`.elasticsearch` 后缀，裸名自动补全

### v1.9（EKS + RDS Extended Support）
- **EKS Extended Support**：¥3.44/cluster-hr
- **RDS Extended Support**：按 vCPU × hr 计费；两档 Yr1-Yr2 / Yr3；支持 MySQL 5.7、PostgreSQL 10/11/12、Aurora MySQL 2、Aurora PG 11/12
- 自动检测旧引擎版本并 warn（例如 MySQL 5.7）
- CSV 新增字段：`extended_support`（none / yr1-2 / yr3）、`engine_version`、`deployment_option`
- RDS `deployment_option` 默认 Single-AZ，可通过字段覆盖为 Multi-AZ

### v1.8.5
- 支持裸实例类型名自动识别（如 `r6g.large`、`m5.large`，不带 `db.` / `cache.` 前缀也能匹配）


## 许可证

MIT
