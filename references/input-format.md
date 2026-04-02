# 批量计算输入格式规范

## CSV 输入格式

### 基本格式

```csv
service,instance_type,region,quantity,usage_hours,os,engine,storage_gb,billing_mode,notes
AmazonEC2,c6i.xlarge,cn-north-1,10,730,Linux,,,on-demand,Web服务器
AmazonEC2,m6i.2xlarge,cn-north-1,5,730,Linux,,,ri-standard-1yr-partial,应用服务器
AmazonRDS,db.r6g.large,cn-north-1,2,730,,MySQL,500,on-demand,数据库
AmazonS3,,cn-north-1,1,,,,1000,,对象存储(GB)
AWSLambda,,cn-north-1,1,,,,,,"100万次/月,128MB,200ms"
```

### 字段说明

| 字段 | 必填 | 说明 |
|------|------|------|
| service | 是 | AWS ServiceCode，如 AmazonEC2, AmazonRDS |
| instance_type | 视服务 | EC2/RDS 等需要，S3/Lambda 不需要 |
| region | 是 | cn-north-1 或 cn-northwest-1 |
| quantity | 是 | 实例数量 |
| usage_hours | 否 | 月使用小时数，默认 730（全月） |
| os | 否 | 操作系统，默认 Linux |
| engine | 否 | 数据库引擎（RDS 用） |
| storage_gb | 否 | 存储容量 GB |
| billing_mode | 否 | 计费模式，默认 on-demand |
| notes | 否 | 备注 |

### billing_mode 可选值

| 值 | 说明 |
|----|------|
| on-demand | 按需 |
| ri-standard-1yr-no | Standard RI, 1年, No Upfront |
| ri-standard-1yr-partial | Standard RI, 1年, Partial Upfront |
| ri-standard-1yr-all | Standard RI, 1年, All Upfront |
| ri-standard-3yr-no | Standard RI, 3年, No Upfront |
| ri-standard-3yr-partial | Standard RI, 3年, Partial Upfront |
| ri-standard-3yr-all | Standard RI, 3年, All Upfront |
| ri-convertible-1yr-no | Convertible RI, 1年, No Upfront |
| ri-convertible-1yr-partial | Convertible RI, 1年, Partial Upfront |
| ri-convertible-1yr-all | Convertible RI, 1年, All Upfront |
| ri-convertible-3yr-no | Convertible RI, 3年, No Upfront |
| ri-convertible-3yr-partial | Convertible RI, 3年, Partial Upfront |
| ri-convertible-3yr-all | Convertible RI, 3年, All Upfront |
| sp-compute-1yr-no | Compute SP, 1年, No Upfront |
| sp-compute-1yr-partial | Compute SP, 1年, Partial Upfront |
| sp-compute-1yr-all | Compute SP, 1年, All Upfront |
| sp-compute-3yr-no | Compute SP, 3年, No Upfront |
| sp-compute-3yr-partial | Compute SP, 3年, Partial Upfront |
| sp-compute-3yr-all | Compute SP, 3年, All Upfront |
| sp-instance-1yr-no | Instance SP, 1年, No Upfront |
| sp-instance-1yr-partial | Instance SP, 1年, Partial Upfront |
| sp-instance-1yr-all | Instance SP, 1年, All Upfront |
| sp-instance-3yr-no | Instance SP, 3年, No Upfront |
| sp-instance-3yr-partial | Instance SP, 3年, Partial Upfront |
| sp-instance-3yr-all | Instance SP, 3年, All Upfront |

### S3 特殊字段

对于 S3，storage_gb 表示存储量。额外计费项在 notes 中注明：
```csv
AmazonS3,,cn-north-1,1,,,,10000,,标准存储
AmazonS3,,cn-north-1,1,,,,5000,,Standard-IA存储
```

### Lambda 特殊字段

Lambda 在 notes 中指定请求数、内存和执行时长：
```csv
AWSLambda,,cn-north-1,1,,,,,,"requests=1000000,memory_mb=128,duration_ms=200"
```

### 数据传输费

数据传输使用专用字段 `transfer_type` 和 `transfer_gb`：

```csv
service,instance_type,region,quantity,usage_hours,os,engine,storage_gb,billing_mode,notes,transfer_type,transfer_gb
DataTransfer,,cn-north-1,1,,,,,,,out_to_internet,500
DataTransfer,,cn-north-1,1,,,,,,,cross_az,1000
DataTransfer,,cn-north-1,1,,,,,,,same_region,2000
DataTransfer,,cn-north-1,1,,,,,,,cloudfront,5000
```

| transfer_type | 说明 | 定价方式 |
|---------------|------|----------|
| out_to_internet | 出公网流量 | 阶梯定价（前1GB免费，1GB-10TB, 10TB-50TB, 50TB-150TB, 150TB+） |
| cross_az | 跨可用区传输 | 固定费率 ¥0.0625/GB |
| same_region | 同区域内传输 | 免费 |
| cloudfront | CloudFront 分发 | 阶梯定价 |

**混合示例**（计算实例 + 数据传输）:
```csv
service,instance_type,region,quantity,usage_hours,os,engine,storage_gb,billing_mode,notes,transfer_type,transfer_gb
AmazonEC2,c6i.xlarge,cn-north-1,10,730,Linux,,,on-demand,Web服务器,,
AmazonRDS,db.r6g.large,cn-north-1,2,730,,MySQL,500,on-demand,数据库,,
DataTransfer,,cn-north-1,1,,,,,,,out_to_internet,500
DataTransfer,,cn-north-1,1,,,,,,,cross_az,1000
```

## Excel 输入格式

Excel 文件使用与 CSV 相同的列名，第一行为表头。支持 .xlsx 格式。

## 多方案对比

使用 --compare 参数指定多种计费方案进行对比：

```bash
python3 scripts/calculate_cost.py --input workload.csv --region cn-north-1 \
  --compare on-demand,ri-standard-1yr-partial,ri-standard-3yr-all,sp-compute-1yr-partial
```

输出将包含每种方案的月度成本和年度成本对比。
