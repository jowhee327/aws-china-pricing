---
name: aws-china-pricing
description: AWS 中国区定价查询、成本计算、报价生成、实例推荐工具，支持 95+ 服务、Savings Plans/RI/On-Demand 对比、数据传输费计算、EDP/PPA 折扣和 Excel 报价单输出。触发词：AWS 中国区价格、EC2 实例价格、成本估算、报价单、Savings Plans、预留实例、数据传输费、实例推荐、性价比
---

# AWS 中国区定价查询 Skill

## 概述

帮助用户查询 AWS 中国区服务价格、计算成本、生成正式报价单、推荐实例规格。覆盖中国区所有服务，支持按需/预留/Savings Plans 等多种计费模式，含数据传输费计算。

## 使用方法

### 1. 单服务价格查询

查询单个服务的 list price：

```bash
python3 scripts/query_price.py --service AmazonEC2 --region cn-north-1 \
  --filters instanceType=c6i.xlarge operatingSystem=Linux
```

常用快捷查询：
```bash
# EC2 实例价格
python3 scripts/query_price.py --service AmazonEC2 --region cn-north-1 \
  --filters instanceType=m6i.large operatingSystem=Linux

# RDS 实例价格
python3 scripts/query_price.py --service AmazonRDS --region cn-north-1 \
  --filters instanceType=db.r6g.large databaseEngine=MySQL

# S3 存储价格
python3 scripts/query_price.py --service AmazonS3 --region cn-north-1

# Lambda 价格
python3 scripts/query_price.py --service AWSLambda --region cn-north-1

# ElastiCache 价格
python3 scripts/query_price.py --service AmazonElastiCache --region cn-north-1 \
  --filters instanceType=cache.r6g.large cacheEngine=Redis

# EBS 卷价格
python3 scripts/query_price.py --service AmazonEC2 --region cn-north-1 \
  --filters productFamily="Storage" volumeType=gp3

# 数据传输费
python3 scripts/query_price.py --service AmazonEC2 --region cn-north-1 \
  --filters productFamily="Data Transfer"
```

### 2. 费率对比（SP vs RI vs On-Demand）

```bash
# 查看所有计费模式对比，含 Savings Plans
python3 scripts/query_price.py --service AmazonEC2 --region cn-north-1 \
  --filters instanceType=c6i.xlarge --compare

# 单独查询 Savings Plans 价格
python3 scripts/query_price.py --service AmazonEC2 --region cn-north-1 \
  --filters instanceType=m6i.large --savings-plans
```

### 3. 实例规格推荐

根据需求推荐最佳性价比实例：

```bash
# 通用推荐：8 vCPU, 32 GiB 内存
python3 scripts/recommend_instance.py --vcpu 8 --memory 32 --region cn-north-1

# 计算密集型推荐
python3 scripts/recommend_instance.py --vcpu 4 --memory 16 --workload compute --region cn-north-1

# 内存密集型推荐
python3 scripts/recommend_instance.py --vcpu 16 --memory 64 --workload memory --region cn-north-1

# GPU 实例推荐
python3 scripts/recommend_instance.py --vcpu 8 --memory 32 --workload gpu --region cn-north-1
```

用途类型（`--workload`）：
- `general` — 通用型 (m6i, m6g, m5, t3 等)
- `compute` — 计算密集型 (c6i, c6g, c5 等)
- `memory` — 内存密集型 (r6i, r6g, r5 等)
- `storage` — 存储密集型 (i3, d2, d3 等)
- `gpu` — GPU 实例 (p3, g4dn, g5 等)

### 4. 一键生成 Excel 报价单

输入任意格式的 Excel/CSV，直接输出 Excel 报价单，一步到位：

```bash
# 最简用法：输入 Excel，输出 {文件名}_报价单.xlsx
python3 scripts/smart_import.py --input workload.xlsx --region cn-north-1 --profile cn-north-1

# 指定客户名称
python3 scripts/smart_import.py --input workload.xlsx --region cn-north-1 --profile cn-north-1 \
  --customer "客户名称"

# 含税报价
python3 scripts/smart_import.py --input workload.xlsx --region cn-north-1 --profile cn-north-1 \
  --include-tax

# 指定输出路径
python3 scripts/smart_import.py --input workload.xlsx --output quote.xlsx --region cn-north-1 \
  --profile cn-north-1
```

> **重要**：这是默认且唯一推荐的报价方式。不要分步调用 calculate_cost.py 或 generate_quote.py。

### 5. 更新价格数据缓存

```bash
# 更新所有服务（含 Savings Plans）
python3 scripts/update_prices.py --region cn-north-1

# 只更新特定服务（EC2 会自动包含 ComputeSavingsPlans）
python3 scripts/update_prices.py --region cn-north-1 --services AmazonEC2,AmazonRDS
```

## 覆盖范围

- **区域**：cn-north-1（北京）、cn-northwest-1（宁夏）、cn-north-1-pkx-1（Auto Cloud Local Zone）
- **服务**：通过 API 动态发现，目前约 95 个服务
- **计费模式**：On-Demand、Reserved Instances（12种组合）、Savings Plans（Compute SP / Instance SP）、Serverless
- **数据传输**：出公网、跨 AZ、同区域、CloudFront 分发

## 折扣配置

编辑 `discount-config.yaml` 配置 EDP/PPA 折扣。增值税率为 6%（信息技术服务）。详见 `references/discount-models.md`。

## 输入格式

批量计算的 CSV 格式详见 `references/input-format.md`。

## 数据源优先级

1. Price List Query API（实时查询）
2. Bulk API 本地缓存（API 不可用时降级）

缓存也没数据时，提示运行 `update_prices.py` 更新。

## Token 优化

所有数据处理在 Python 脚本本地完成，只返回匹配的少量结果行。绝不将大 JSON 文件塞入上下文。
