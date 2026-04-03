# AWS China Pricing Skill

[🇨🇳 中文版](README_CN.md)

An OpenClaw Skill for querying AWS China region pricing, calculating costs, and generating quotes. Covers all 95+ services across Beijing (cn-north-1), Ningxia (cn-northwest-1), and Auto Cloud Local Zone (cn-north-1-pkx-1).

## Features

- **Smart Import** — Natural language service descriptions auto-mapped to AWS service codes (80+ rules)
- **Real-time Price Query** — Query any service via AWS Price List API
- **Full RI Coverage** — Standard & Convertible RI, 1yr/3yr, No/Partial/All Upfront (12 combinations)
- **Savings Plans** — Compute SP + EC2 Instance SP pricing and comparison
- **EDP/PPA Discounts** — Enterprise Discount Program & Private Pricing Addendum with configurable stacking
- **Batch Cost Calculation** — Import CSV/Excel workloads for total cost estimation
- **Excel Quote Generation** — Professional quotes with customer info, validity dates, and line items
- **Instance Recommendation** — Recommend instance types based on vCPU/memory requirements
- **Data Transfer Costs** — Internet egress (tiered), cross-AZ, same-region, CloudFront
- **Multi-Region Comparison** — Side-by-side pricing for Beijing vs Ningxia
- **Tax Support** — Optional 6% VAT (China cloud services tax rate)
- **Price Cache & Updates** — Bulk API download with indexed local cache, incremental updates

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

### 0. Smart Import (Natural Language Input)

Don't know the exact AWS service codes? Just describe what you need:

```csv
类型,规格,数量,备注
计算,8C16G,20,Web服务器
MySQL数据库,4C32G,2,业务库
Redis缓存,4G内存,3,Session缓存
对象存储,1TB,,文件存储
Kafka消息队列,,2,异步消息
```

```bash
# Convert to standardized format
python3 scripts/smart_import.py --input raw_workload.csv --output standardized.csv --region cn-north-1

# Or directly calculate costs
python3 scripts/smart_import.py --input raw_workload.csv --region cn-north-1 --calculate
```

Supports 80+ mapping rules covering all 95 China region services in Chinese/English, with auto-detection of:
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
├── SKILL.md                    # OpenClaw skill entry point
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
