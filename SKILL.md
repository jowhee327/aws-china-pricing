---
name: aws-china-pricing
description: AWS 中国区定价查询、成本计算、报价生成、实例推荐工具，支持 95+ 服务、Savings Plans/RI/On-Demand 对比、数据传输费计算、EDP/PPA 折扣和 Excel 报价单输出。触发词：AWS 中国区价格、EC2 实例价格、成本估算、报价单、Savings Plans、预留实例、数据传输费、实例推荐、性价比
---

# ⚠️ **CRITICAL - MANDATORY RULES FOR AI AGENTS** ⚠️

## 🚨 **WARNING: 生成AWS报价单的强制规则 - 必须严格遵守！**

**AI Agent（包括但不限于 Kiro、Claude Code 等）在处理"根据Excel文件报AWS价格"、"生成报价单"等任务时，必须严格遵守以下规则：**

### 🔥 **RULE #1 - 唯一入口点**
- ✅ **只能使用 `smart_import.py` 作为唯一入口**
- ❌ **绝对禁止**手动读取 Excel 文件
- ❌ **绝对禁止**手动创建 CSV 文件
- ❌ **绝对禁止**手动调用 `calculate_cost.py`
- ❌ **绝对禁止**手动调用 `generate_quote.py`
- ❌ **绝对禁止**分步处理工作流

### 🔥 **RULE #2 - 直接传递原始Excel**
- ✅ **直接把用户的原始 Excel 文件传给 `smart_import.py --input`**
- ✅ **`smart_import.py` 会自动处理任意格式的 Excel**
- ❌ **绝对禁止**自己解析 Excel 内容
- ❌ **绝对禁止**使用 openpyxl、pandas 等手动读 Excel
- ❌ **绝对禁止**自己做服务映射
- ❌ **绝对禁止**创建中间文件

### 🔥 **RULE #3 - 保持Sheet独立**
- ✅ **`smart_import.py` 会自动保持每个 Sheet 独立处理**
- ❌ **绝对禁止**合并多个 Sheet
- ❌ **绝对禁止**手动处理多 Sheet 逻辑

### 🔥 **RULE #4 - 计费模式映射**
用户说的关键词自动映射：
- 用户说 "RI" → 传递 `--billing-mode ri-1y-no-upfront`（或其他 ri-xxx）
- 用户说 "SP" → 传递 `--billing-mode sp-1y-no-upfront`（或其他 sp-xxx）  
- 用户说 "RI和SP"、"混合" → 传递 `--billing-mode ri-sp-1y-no-upfront`（或其他 ri-sp-xxx）
- 没说明 → 默认 `on-demand`

### 🔥 **RULE #5 - EDP折扣处理**
- 用户说 "EDP xx%" → **先**修改 `discount-config.yaml` 设置 EDP 折扣
- **然后**调用 `smart_import.py`，折扣会自动应用

### 🔥 **RULE #6 - 区域映射**
用户说的区域自动映射：
- "北京" → `cn-north-1`
- "宁夏" → `cn-northwest-1`
- "北京本地扩展区" → `cn-north-1-pkx-1`

### 🔥 **RULE #7 - 标准调用格式**
```bash
# 标准格式（必须遵守）
python3 scripts/smart_import.py --input {用户提供的Excel文件} --region {区域} [其他选项]

# 示例
python3 scripts/smart_import.py --input workload.xlsx --region cn-north-1 --billing-mode ri-sp-1y-no-upfront --customer "客户ABC"
```

---

## 🚨 **这些规则的目的**
- 避免生成 CSV 而不是 Excel
- 避免多个 Sheet 被错误合并  
- 确保 RI/SP 正确使用
- 保证输出格式和内容的一致性
- 减少错误和用户困惑

**违反这些规则会导致错误的输出和用户体验！**

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
python3 scripts/smart_import.py --input workload.xlsx --region cn-north-1

# 指定客户名称
python3 scripts/smart_import.py --input workload.xlsx --region cn-north-1 \
  --customer "客户名称"

# 含税报价
python3 scripts/smart_import.py --input workload.xlsx --region cn-north-1 \
  --include-tax

# 指定输出路径
python3 scripts/smart_import.py --input workload.xlsx --output quote.xlsx --region cn-north-1

# 使用 1年期无预付的 RI 和 SP 混合模式计算（EC2 用 SP，其他服务用 RI）
python3 scripts/smart_import.py --input workload.xlsx --region cn-north-1 \
  --billing-mode ri-sp-1y-no-upfront

# 使用标准 RI 1年部分预付
python3 scripts/smart_import.py --input workload.xlsx --region cn-north-1 \
  --billing-mode ri-1y-partial

# 使用计算型 Savings Plans 1年无预付
python3 scripts/smart_import.py --input workload.xlsx --region cn-north-1 \
  --billing-mode sp-1y-no-upfront

# 简化参数：-b 是 --billing-mode 的缩写
python3 scripts/smart_import.py --input workload.xlsx -r cn-north-1 -b ri-3y-partial
```

**计费模式说明**：
- `on-demand` — 按需付费（默认）
- `ri-1y-no-upfront` — 标准RI 1年无预付
- `ri-1y-partial` — 标准RI 1年部分预付  
- `ri-1y-all` — 标准RI 1年全预付
- `ri-3y-no-upfront` / `ri-3y-partial` / `ri-3y-all` — 标准RI 3年各种预付方式
- `sp-1y-no-upfront` / `sp-1y-partial` / `sp-1y-all` — 计算型SP 1年各种预付方式
- `sp-3y-no-upfront` / `sp-3y-partial` / `sp-3y-all` — 计算型SP 3年各种预付方式
- `ri-sp-1y-no-upfront` — 混合模式：EC2 用 SP，其他服务用 RI（1年无预付）
- `ri-sp-1y-partial` / `ri-sp-1y-all` — 混合模式 1年部分/全预付
- `ri-sp-3y-no-upfront` / `ri-sp-3y-partial` / `ri-sp-3y-all` — 混合模式 3年各种预付方式

> **注意**：简化名称会自动映射到标准名称（如 `ri-1y-partial` → `ri-standard-1yr-partial`，`sp-1y-no-upfront` → `sp-compute-1yr-no-upfront`）
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
