# AWS 中国区服务目录与特殊说明

## 概述

AWS 中国区由光环新网（北京区域）和西云数据（宁夏区域）运营，与全球区域在合规和定价上有差异。

## 区域

| 区域代码 | 名称 | 运营方 |
|----------|------|--------|
| cn-north-1 | 北京 | 光环新网 (SINNET) |
| cn-northwest-1 | 宁夏 | 西云数据 (NWCD) |
| cn-north-1-pkx-1 | Auto Cloud Local Zone | — |

## 定价特殊说明

### 货币
- 中国区定价以 **CNY（人民币）** 为单位
- API 返回的 pricePerUnit 货币为 CNY

### 与全球区域的差异
- 定价结构相同，但具体价格不同（通常略高于全球区域）
- 部分服务在中国区不可用
- Savings Plans 类型有限制（无 ML SP 和 DB SP）
- 免费层有差异

### EC2 特殊说明
- 支持的实例系列可能与全球区域不同，需通过 API 动态发现
- 部分新一代实例可能延迟上线
- Windows 实例需要 BYOL 或使用 AWS 提供的许可

### S3 特殊说明
- 存储层级: Standard, Standard-IA, One Zone-IA, Glacier, Glacier Deep Archive
- 智能分层 (Intelligent-Tiering) 可用
- 请求和数据检索费用单独计费
- 数据传输出互联网按量阶梯计费

### 数据传输
- 同区域 AZ 间传输收费
- 跨区域（北京↔宁夏）传输收费
- 传出互联网阶梯定价:
  - 前 1GB/月免费（部分服务）
  - 1GB - 10TB
  - 10TB - 50TB
  - 50TB - 150TB
  - 150TB+

### RDS 特殊说明
- 支持引擎: MySQL, PostgreSQL, MariaDB, Oracle, SQL Server, Aurora (MySQL/PostgreSQL)
- Multi-AZ 部署价格约为单 AZ 的 2x
- 存储: gp2, gp3, io1, io2, magnetic

### Pricing API 特殊说明
- Pricing API endpoint 位于 cn-northwest-1
- 需要使用中国区 IAM 凭证
- ServiceCode 名称可通过 describe-services 获取
- 过滤器字段因服务而异，需通过 describe-services 的 AttributeNames 了解

## 服务发现

使用以下命令动态获取当前可用的所有服务:

```bash
aws pricing describe-services --region cn-northwest-1 --profile cn-north-1
```

不要硬编码服务列表，始终通过 API 动态发现。
