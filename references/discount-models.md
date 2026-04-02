# AWS 中国区折扣模型详解

## 1. On-Demand（按需付费）

无承诺、无折扣，按小时或按秒计费。适合短期、不可预测的工作负载。

## 2. Reserved Instances (RI)

### 类型
- **Standard RI**：折扣最高（最多约 40-60%），不能更改实例族
- **Convertible RI**：折扣稍低（最多约 30-50%），可更改实例族/OS/租户

### 期限与预付方式（12种组合）

| 类型 | 期限 | 预付方式 | 折扣力度 |
|------|------|----------|----------|
| Standard RI | 1年 | No Upfront | ★★☆☆☆ |
| Standard RI | 1年 | Partial Upfront | ★★★☆☆ |
| Standard RI | 1年 | All Upfront | ★★★☆☆ |
| Standard RI | 3年 | No Upfront | ★★★☆☆ |
| Standard RI | 3年 | Partial Upfront | ★★★★☆ |
| Standard RI | 3年 | All Upfront | ★★★★★ |
| Convertible RI | 1年 | No Upfront | ★★☆☆☆ |
| Convertible RI | 1年 | Partial Upfront | ★★☆☆☆ |
| Convertible RI | 1年 | All Upfront | ★★★☆☆ |
| Convertible RI | 3年 | No Upfront | ★★★☆☆ |
| Convertible RI | 3年 | Partial Upfront | ★★★★☆ |
| Convertible RI | 3年 | All Upfront | ★★★★☆ |

### RI 定价结构
- **Upfront Fee**：一次性预付金额
- **Recurring Fee**：每小时/月的固定费用
- 有效小时费率 = (Upfront / 总小时数) + Recurring hourly

## 3. Savings Plans (SP)

### 中国区可用类型
- **Compute Savings Plans**：最灵活，覆盖 EC2、Fargate、Lambda
- **EC2 Instance Savings Plans**：折扣更高，锁定实例族和区域

### 中国区暂不可用
- ML Savings Plans
- Database Savings Plans（如 SageMaker SP、RDS SP）

### SP 定价结构
- 承诺每小时消费金额（$/hr）
- 超出承诺部分按 On-Demand 计费
- 期限: 1年 或 3年
- 预付: No Upfront / Partial Upfront / All Upfront

## 4. EDP (Enterprise Discount Program)

- 全账单折扣，适用于所有 AWS 服务
- 通常要求年度承诺消费额
- 折扣范围: 3% - 15%
- 在所有其他折扣之后叠加（或根据配置调整顺序）

## 5. PPA (Private Pricing Addendum)

- 按服务或实例族的私有折扣
- 需要与 AWS 商务团队谈判
- 可针对特定服务（如 EC2 c6i 系列 10%、S3 5%）
- 通常用于大客户的特定使用场景

## 6. 折扣叠加规则

折扣可以叠加，叠加顺序在 `discount-config.yaml` 中配置。

**示例**：list price ¥100/hr，PPA 10%，EDP 8%

- 顺序 PPA → EDP: ¥100 × 0.90 × 0.92 = ¥82.80/hr
- 顺序 EDP → PPA: ¥100 × 0.92 × 0.90 = ¥82.80/hr（乘法可交换，结果相同）

注意：虽然乘法可交换，但实际合同中的叠加方式可能影响计费细节，建议按合同约定配置。

## 7. 免费额度

部分服务有免费额度，计算成本时应先扣除：
- Lambda: 每月 100 万次请求 + 40 万 GB-秒
- S3: 无永久免费层（中国区）
- DynamoDB: 25GB 存储 + 25 WCU + 25 RCU
- CloudWatch: 10 自定义指标 + 10 告警

## 8. 增值税

- 中国区云服务增值税率: 6%（信息技术服务）
- 报价可选含税/不含税
- 含税价 = 不含税价 × 1.06
