# AWS China Pricing Skill

[🇨🇳 中文版](README.md)

A Skill for querying AWS China region pricing, calculating costs, and generating quotes. Covers all 87 services across Beijing (cn-north-1), Ningxia (cn-northwest-1), and Auto Cloud Local Zone (cn-north-1-pkx-1).

## Features

- **Smart Import** — Auto-mapping Excel/CSV with any format
- **Real-time Price Query** — 87 services
- **RI/SP Support** — Standard/Convertible RI + Compute/Instance SP
- **Discount Support** — EDP/PPA
- **Excel Quote Generation**
- **Instance Recommendation**

## Prerequisites

- **AWS CLI** configured with a China region profile
- **Python 3.10+**
- **pip packages**: `openpyxl`, `pyyaml`

```bash
pip install openpyxl pyyaml
```

### AWS CLI Configuration

The skill expects a profile named `cn-north-1` with access to the Pricing API:

```ini
# ~/.aws/credentials
[cn-north-1]
aws_access_key_id = YOUR_KEY
aws_secret_access_key = YOUR_SECRET

# ~/.aws/config
[profile cn-north-1]
region = cn-north-1
```

> **Note**: The Pricing API endpoint is in `cn-northwest-1`, but works with credentials from either China region.

## Quick Start

### 0. One-Click Excel Quote (Recommended)

Input Excel/CSV with natural language descriptions, output a professional Excel quote in one command:

```bash
# Simplest: input Excel → output {filename}_报价单.xlsx
python3 scripts/smart_import.py --input workload.xlsx --region cn-north-1

# With customer name
python3 scripts/smart_import.py --input workload.xlsx --region cn-north-1 \
  --customer "ACME Corp"

# Include 6% VAT
python3 scripts/smart_import.py --input workload.xlsx --region cn-north-1 \
  --include-tax
```

Don't know the exact AWS service codes? Just describe what you need:

```csv
类型,规格,数量,备注
计算,8C16G,20,Web服务器
MySQL数据库,4C32G,2,业务库
Redis缓存,4G内存,3,Session缓存
对象存储,1TB,,文件存储
Kafka消息队列,,2,异步消息
```

Supports 80+ mapping rules covering all 87 China region services in Chinese/English, with auto-detection of:
- Engine type: "MySQL" → `engine=MySQL`, "Redis" → `engine=Redis`
- Instance specs: "8C16G" → `vCPU=8, memory=16` → recommends best-fit instance
- Storage sizes: "1TB" → `storage_gb=1024`

### 1. Query a Single Service

```bash
# EC2 instance pricing
python3 scripts/query_price.py -s AmazonEC2 -r cn-north-1 \
  -f instanceType=c6i.xlarge operatingSystem=Linux tenancy=Shared \
     capacitystatus=Used preInstalledSw=NA

# RDS pricing
python3 scripts/query_price.py -s AmazonRDS -r cn-north-1 \
  -f instanceType=db.r6g.xlarge databaseEngine=MySQL

# Full comparison (On-Demand vs RI vs Savings Plans)
python3 scripts/query_price.py -s AmazonEC2 -r cn-north-1 \
  -f instanceType=c6i.xlarge operatingSystem=Linux tenancy=Shared \
     capacitystatus=Used preInstalledSw=NA \
  --compare --savings-plans
```

### 2. Recommend Instances

```bash
# General purpose, 8 vCPU, 32 GB RAM
python3 scripts/recommend_instance.py --vcpu 8 --memory 32 --region cn-north-1

# Compute optimized
python3 scripts/recommend_instance.py --vcpu 4 --memory 16 --workload compute --region cn-northwest-1
```

### 3. Batch Cost Calculation

```bash
# Calculate from CSV
python3 scripts/calculate_cost.py --input workload.csv --region cn-north-1

# With EDP/PPA discounts
python3 scripts/calculate_cost.py --input workload.csv --region cn-north-1 \
  --discount-config discount-config.yaml

# Include 6% VAT
python3 scripts/calculate_cost.py --input workload.csv --region cn-north-1 --include-tax
```

### 4. Generate Excel Quote

```bash
python3 scripts/generate_quote.py --input workload.csv --region cn-north-1 \
  --customer "ACME Corp" --validity 30 --output quote.xlsx
```

### 5. Update Price Cache

```bash
# Update all services for a region
python3 scripts/update_prices.py --region cn-north-1

# Update specific services
python3 scripts/update_prices.py --region cn-north-1 --services AmazonEC2,AmazonRDS

# Force re-download
python3 scripts/update_prices.py --region cn-north-1 --force
```

> **Important**: Savings Plans data must be downloaded via `update_prices.py` before SP queries work (SP data is not available through the Query API).

## 30 Billing Modes

Supports the following 30 billing modes via the `--billing-mode` parameter:

### Reserved Instances (12 modes)
- `ri-standard-1yr-no` - Standard RI 1-year No Upfront
- `ri-standard-1yr-partial` - Standard RI 1-year Partial Upfront  
- `ri-standard-1yr-all` - Standard RI 1-year All Upfront
- `ri-standard-3yr-no` - Standard RI 3-year No Upfront
- `ri-standard-3yr-partial` - Standard RI 3-year Partial Upfront
- `ri-standard-3yr-all` - Standard RI 3-year All Upfront
- `ri-convertible-1yr-no` - Convertible RI 1-year No Upfront
- `ri-convertible-1yr-partial` - Convertible RI 1-year Partial Upfront
- `ri-convertible-1yr-all` - Convertible RI 1-year All Upfront
- `ri-convertible-3yr-no` - Convertible RI 3-year No Upfront
- `ri-convertible-3yr-partial` - Convertible RI 3-year Partial Upfront
- `ri-convertible-3yr-all` - Convertible RI 3-year All Upfront

### Savings Plans (4 modes)
- `sp-compute-1yr` - Compute Savings Plans 1-year
- `sp-compute-3yr` - Compute Savings Plans 3-year
- `sp-instance-1yr` - EC2 Instance Savings Plans 1-year
- `sp-instance-3yr` - EC2 Instance Savings Plans 3-year

### Other Modes (12 modes)
- `on-demand` - On-Demand pricing (default)
- `spot` - Spot instances
- `dedicated-host` - Dedicated hosts
- `dedicated-instance` - Dedicated instances
- `mixed-ri-od` - Mixed mode: RI + On-Demand
- `mixed-sp-od` - Mixed mode: SP + On-Demand
- `mixed-ri-spot` - Mixed mode: RI + Spot
- `mixed-sp-spot` - Mixed mode: SP + Spot
- `prepaid` - Prepaid
- `postpaid` - Postpaid
- `pay-per-use` - Pay-per-use
- `serverless` - Serverless pricing

> **Smart Adaptation**: Only services that support RI/SP (like EC2, RDS) will use the specified RI/SP mode. Unsupported services automatically fall back to on-demand pricing.

## Storage Service Features

### S3 Storage Class Detection

Supports pricing queries for 7 S3 storage classes:

| Storage Class | `storageClass` Value | Use Case |
|---------------|---------------------|----------|
| Standard | Standard | Frequently accessed data |
| Intelligent Tiering | IntelligentTiering | Automatic cost optimization |
| Standard-IA | StandardInfrequentAccess | Infrequently accessed |
| One Zone-IA | OneZoneInfrequentAccess | Single-AZ infrequent access |
| Glacier Instant Retrieval | GlacierInstantRetrieval | Millisecond retrieval archive |
| Glacier Flexible Retrieval | GlacierFlexibleRetrieval | Minutes to hours retrieval |
| Glacier Deep Archive | GlacierDeepArchive | 12-hour retrieval long-term archive |

### EBS as Independent Service

EBS as an independent service (ServiceCode: AmazonEBS) with volume type detection:

| Volume Type | `volumeType` Value | Features |
|-------------|-------------------|----------|
| General Purpose SSD | gp3 | Default type, best price-performance |
| General Purpose SSD | gp2 | Legacy general purpose |
| Provisioned IOPS SSD | io2 | High-performance databases |
| Provisioned IOPS SSD | io1 | Legacy high-performance |
| Throughput Optimized HDD | st1 | Big data analytics |
| Cold HDD | sc1 | Infrequent access data |

### Unified Storage Billing

All storage services use unified **GB/month** billing:
- **S3**: Per storage class by actual usage
- **EFS**: By file system size  
- **FSx**: By file system capacity
- **EBS**: By volume size
- **Glacier**: By archived data volume

## Pay-per-Use Services

The following services are marked as "pay-per-use" and don't use hourly billing:

- **Lambda**: By request count and execution time
- **API Gateway**: By API call count
- **SQS**: By message count
- **SNS**: By notification count
- **DynamoDB**: By read/write capacity units
- **CloudWatch**: By metrics and log volume
- **S3**: By storage volume and requests
- **CloudFront**: By data transfer volume

These services show default usage estimates in quotes to avoid misleading $0 prices.

## 87 AWS China Services

Supports pricing queries for all 87 AWS China region services with unified display names:

| Service Category | Main Services | Display Name |
|------------------|---------------|--------------|
| Compute | AmazonEC2 | EC2 |
| | AWSLambda | Lambda |
| | AmazonECS | ECS |
| Database | AmazonRDS | RDS |
| | AmazonDynamoDB | DynamoDB |
| | AmazonElastiCache | ElastiCache |
| Storage | AmazonS3 | S3 |
| | AmazonEBS | EBS |
| | AmazonEFS | EFS |
| Network | AmazonVPC | VPC |
| | AmazonCloudFront | CloudFront |
| | ElasticLoadBalancing | ELB |

See [references/service-catalog.md](references/service-catalog.md) for the complete service list.

## Version History

### v1.7.3 (Latest)
- ✅ 30 billing modes support with smart applicability judgment
- ✅ EBS independent service, gp3 default volume type
- ✅ S3 seven storage classes smart detection
- ✅ Unified per-GB-month billing for storage services
- ✅ Pay-per-use service annotation and default usage
- ✅ EDP discount display in quote header
- ✅ 87 services unified display name standards
- ✅ Automatic use of AWS CLI default profile

### v1.5.4
- ✅ Basic price query and RI/SP support
- ✅ Smart import and Excel quote generation
- ✅ EDP/PPA discount configuration

## CSV Input Format

```csv
service,region,instance_type,os,engine,quantity,hours_per_month,billing_mode,transfer_type,transfer_gb,notes
AmazonEC2,cn-north-1,c6i.xlarge,Linux,,10,730,on-demand,,,Web servers
AmazonEC2,cn-north-1,m6i.2xlarge,Linux,,5,730,ri-standard-1yr-partial,,,App servers
AmazonRDS,cn-north-1,db.r6g.xlarge,,MySQL,2,730,on-demand,,,Database
AmazonEC2,cn-north-1,,,,1,,on-demand,out_to_internet,5000,Egress 5TB
```

See [references/input-format.md](references/input-format.md) for full field documentation.

## Discount Configuration

Edit `discount-config.yaml`:

```yaml
edp:
  enabled: true
  discount_pct: 8  # 8% EDP discount

ppa:
  enabled: true
  rules:
    - service: AmazonEC2
      discount_pct: 10
    - service: AmazonRDS
      discount_pct: 5

discount_stack_order:
  - ppa   # Apply PPA first
  - edp   # Then EDP on top

tax:
  vat_rate: 6
  include_tax: false  # Default: prices exclude VAT
```

See [references/discount-models.md](references/discount-models.md) for detailed discount model documentation.

## Data Sources

| Priority | Source | Description |
|----------|--------|-------------|
| 1 | Price List Query API | Real-time, per-product queries |
| 2 | Local Cache (Bulk API) | Pre-downloaded & indexed JSON files |

When both sources return no results, the tool prompts you to run `update_prices.py`.

## Project Structure

```
aws-china-pricing/
├── SKILL.md                    # Skill entry point
├── discount-config.yaml        # EDP/PPA discount configuration
├── scripts/
│   ├── smart_import.py         # Natural language → AWS service mapping
│   ├── query_price.py          # Core pricing query (API + cache fallback)
│   ├── calculate_cost.py       # Batch cost calculation engine
│   ├── update_prices.py        # Price data updater (Bulk API + indexing)
│   ├── generate_quote.py       # Excel quote generator
│   └── recommend_instance.py   # Instance type recommender
├── references/
│   ├── discount-models.md      # EDP/PPA/RI/SP discount models
│   ├── service-catalog.md      # China region service notes
│   └── input-format.md         # CSV/Excel input format spec
├── assets/                     # Template files
└── data/                       # Price cache (auto-generated)
    ├── cache/                  # Raw Bulk API downloads
    └── index/                  # Indexed per-instance-family files
```

## Regions Covered

| Region Code | Name | Operator |
|-------------|------|----------|
| cn-north-1 | Beijing | Sinnet (光环新网) |
| cn-northwest-1 | Ningxia | NWCD (西云数据) |
| cn-north-1-pkx-1 | Auto Cloud Local Zone | — |

## License

MIT