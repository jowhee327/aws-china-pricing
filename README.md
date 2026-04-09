# AWS 中国区定价查询 Skill

[🇺🇸 English](README_EN.md)

一个 Skill，用于查询 AWS 中国区服务价格、计算成本和生成报价单。覆盖北京区 (cn-north-1)、宁夏区 (cn-northwest-1) 和 Auto Cloud Local Zone (cn-north-1-pkx-1) 的 87 个服务。

## 功能特性

- **智能导入** — 任意格式 Excel/CSV 自动识别
- **实时价格查询** — 87 个服务
- **RI/SP 支持** — Standard/Convertible RI + Compute/Instance SP
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

# 指定计费模式（30 种模式）
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

## 30 种计费模式

支持以下 30 种计费模式，通过 `--billing-mode` 参数指定：

### Reserved Instances (12 种)
- `ri-standard-1yr-no` - Standard RI 1年期 无预付
- `ri-standard-1yr-partial` - Standard RI 1年期 部分预付  
- `ri-standard-1yr-all` - Standard RI 1年期 全预付
- `ri-standard-3yr-no` - Standard RI 3年期 无预付
- `ri-standard-3yr-partial` - Standard RI 3年期 部分预付
- `ri-standard-3yr-all` - Standard RI 3年期 全预付
- `ri-convertible-1yr-no` - Convertible RI 1年期 无预付
- `ri-convertible-1yr-partial` - Convertible RI 1年期 部分预付
- `ri-convertible-1yr-all` - Convertible RI 1年期 全预付
- `ri-convertible-3yr-no` - Convertible RI 3年期 无预付
- `ri-convertible-3yr-partial` - Convertible RI 3年期 部分预付
- `ri-convertible-3yr-all` - Convertible RI 3年期 全预付

### Savings Plans (4 种)
- `sp-compute-1yr` - Compute Savings Plans 1年期
- `sp-compute-3yr` - Compute Savings Plans 3年期
- `sp-instance-1yr` - EC2 Instance Savings Plans 1年期
- `sp-instance-3yr` - EC2 Instance Savings Plans 3年期

### 其他模式 (12 种)
- `on-demand` - 按需付费（默认）
- `spot` - Spot 实例
- `dedicated-host` - 专用主机
- `dedicated-instance` - 专用实例
- `mixed-ri-od` - 混合模式：RI + On-Demand
- `mixed-sp-od` - 混合模式：SP + On-Demand
- `mixed-ri-spot` - 混合模式：RI + Spot
- `mixed-sp-spot` - 混合模式：SP + Spot
- `prepaid` - 预付费
- `postpaid` - 后付费
- `pay-per-use` - 按量计费
- `serverless` - Serverless 计费

> **智能适配**: 只有支持 RI/SP 的服务（如 EC2、RDS）才会使用指定的 RI/SP 模式，不支持的服务自动 fallback 到按需价格。

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

## 存储服务特性

### S3 存储类别智能检测

支持 7 种 S3 存储类别的价格查询：

| 存储类别 | `storageClass` 值 | 用途 |
|----------|-------------------|------|
| 标准存储 | Standard | 频繁访问数据 |
| 智能分层 | IntelligentTiering | 自动优化存储成本 |
| 标准-低频 | StandardInfrequentAccess | 不频繁访问 |
| 单区域-低频 | OneZoneInfrequentAccess | 单AZ不频繁访问 |
| Glacier 即时检索 | GlacierInstantRetrieval | 毫秒级检索归档 |
| Glacier 灵活检索 | GlacierFlexibleRetrieval | 分钟到小时检索 |
| Glacier 深度归档 | GlacierDeepArchive | 12小时检索长期归档 |

### EBS 独立服务

EBS 作为独立服务 (ServiceCode: AmazonEBS)，支持卷类型检测：

| 卷类型 | `volumeType` 值 | 特性 |
|--------|----------------|------|
| 通用型 SSD | gp3 | 默认类型，性价比最优 |
| 通用型 SSD | gp2 | 传统通用型 |
| 预配置 IOPS SSD | io2 | 高性能数据库 |
| 预配置 IOPS SSD | io1 | 传统高性能 |
| 吞吐优化 HDD | st1 | 大数据分析 |
| Cold HDD | sc1 | 低频访问数据 |

### 存储计费统一

所有存储服务统一按 **GB/月** 计费：
- **S3**: 各存储类别按实际用量
- **EFS**: 按文件系统大小  
- **FSx**: 按文件系统容量
- **EBS**: 按卷大小
- **Glacier**: 按归档数据量

## 按量计费服务

以下服务标注为"按量计费"，不使用按小时计费：

- **Lambda**: 按请求次数和执行时间
- **API Gateway**: 按 API 调用次数
- **SQS**: 按消息数量
- **SNS**: 按通知数量
- **DynamoDB**: 按读写容量单位
- **CloudWatch**: 按指标和日志量
- **S3**: 按存储量和请求数
- **CloudFront**: 按数据传输量

这些服务在报价单中显示默认用量估算值，避免 $0 价格误导。

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

## 版本历史

### v1.7.3 (最新)
- ✅ 30 种计费模式支持，智能适用性判断
- ✅ EBS 独立服务，gp3 默认卷类型
- ✅ S3 七种存储类别智能检测
- ✅ 存储服务统一 per-GB-month 计费
- ✅ 按量计费服务标注和默认用量
- ✅ EDP 折扣显示在报价单头部
- ✅ 87 个服务统一显示名规范
- ✅ 自动使用 AWS CLI 默认 profile

### v1.5.4
- ✅ 基础价格查询和 RI/SP 支持
- ✅ 智能导入和 Excel 报价单生成
- ✅ EDP/PPA 折扣配置

## 许可证

MIT