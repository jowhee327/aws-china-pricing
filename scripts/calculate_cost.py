#!/usr/bin/env python3
"""AWS 中国区批量成本计算引擎

从 CSV/Excel 导入工作负载，计算各种计费模式下的总成本，支持折扣叠加和多方案对比。

用法:
  python3 calculate_cost.py --input workload.csv --region cn-north-1
  python3 calculate_cost.py --input workload.csv --region cn-north-1 --discount-config ../discount-config.yaml
  python3 calculate_cost.py --input workload.csv --region cn-north-1 --compare on-demand,ri-standard-1yr-partial
  python3 calculate_cost.py --input workload.csv --region cn-north-1 --output result.csv --include-tax
"""

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Optional

try:
    import yaml
except ImportError:
    print("[ERROR] 需要 PyYAML 库: pip install pyyaml", file=sys.stderr)
    sys.exit(1)

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))
from query_price import (
    query_api, query_cache, extract_pricing,
    RI_TERM_MAP, SP_TERM_MAP, REGION_OVERRIDE, query_savings_plans,
    build_eks_extended_support_usagetype, build_rds_extended_support_usagetype,
    query_extended_support_price,
)

# RDS engine 别名 → 规范化大小写（与 smart_import.py 保持一致）
_RDS_ENGINE_ALIASES = {
    "postgresql": "PostgreSQL", "postgres": "PostgreSQL",
    "psql": "PostgreSQL", "pgsql": "PostgreSQL", "pg": "PostgreSQL",
    "mysql": "MySQL",
    "aurora mysql": "Aurora MySQL", "aurora-mysql": "Aurora MySQL",
    "auroramysql": "Aurora MySQL",
    "aurora postgresql": "Aurora PostgreSQL",
    "aurora-postgresql": "Aurora PostgreSQL",
    "aurora postgres": "Aurora PostgreSQL",
    "aurora-postgres": "Aurora PostgreSQL",
    "aurorapostgresql": "Aurora PostgreSQL",
    "mariadb": "MariaDB",
    "oracle": "Oracle",
    "sql server": "SQL Server", "sqlserver": "SQL Server", "mssql": "SQL Server",
}


def _normalize_rds_engine(engine: str) -> str:
    if not engine:
        return ""
    key = engine.strip().lower()
    if not key:
        return ""
    return _RDS_ENGINE_ALIASES.get(key, engine.strip())


# 从 instance_type 名称推断 vCPU（fallback，当 pricing API 缺 vcpu 属性时使用）
# 规则: {family}.{size}，size 对应 vCPU：large=2, xlarge=4, NxLarge=N*4
_SIZE_VCPU_MAP = {
    "nano": 1, "micro": 1, "small": 1, "medium": 2,
    "large": 2, "xlarge": 4,
}


def _vcpu_from_instance_type(instance_type: str) -> int:
    """从实例类型字符串推断 vCPU 数。失败返回 0。"""
    if not instance_type:
        return 0
    # db.r6g.2xlarge / r6g.xlarge / cache.m5.large
    parts = instance_type.split(".")
    if len(parts) < 2:
        return 0
    size = parts[-1].lower()
    if size in _SIZE_VCPU_MAP:
        return _SIZE_VCPU_MAP[size]
    # NxLarge 形式
    import re as _re
    m = _re.match(r"^(\d+)xlarge$", size)
    if m:
        return int(m.group(1)) * 4
    if size == "metal":
        return 0
    return 0


def load_discount_config(config_path: str) -> dict:
    """加载折扣配置"""
    try:
        with open(config_path) as f:
            config = yaml.safe_load(f)
        return config or {}
    except FileNotFoundError:
        print(f"折扣配置文件不存在: {config_path}", file=sys.stderr)
        print("[INFO] 将使用 list price（无折扣）。", file=sys.stderr)
        print(f"[INFO] 请编辑 {config_path} 配置 EDP/PPA 折扣。", file=sys.stderr)
        return {}
    except yaml.YAMLError as e:
        print(f"折扣配置文件格式错误: {e}", file=sys.stderr)
        return {}


def apply_discounts(price: float, service: str, instance_family: str, config: dict) -> tuple[float, list[str]]:
    """应用折扣并返回折后价和应用的折扣说明"""
    if not config:
        return price, []

    applied = []
    stack_order = config.get("discount_stack_order", ["ppa", "edp"])
    current_price = price

    for discount_type in stack_order:
        if discount_type == "edp":
            edp = config.get("edp", {})
            if edp.get("enabled") and edp.get("discount_pct", 0) > 0:
                pct = edp["discount_pct"]
                current_price *= (1 - pct / 100)
                applied.append(f"EDP {pct}%")

        elif discount_type == "ppa":
            ppa = config.get("ppa", {})
            if ppa.get("enabled"):
                for rule in ppa.get("rules", []):
                    if rule.get("service") and rule["service"] != service:
                        continue
                    if rule.get("instance_family") and instance_family and \
                       rule["instance_family"] != instance_family:
                        continue
                    pct = rule.get("discount_pct", 0)
                    if pct > 0:
                        current_price *= (1 - pct / 100)
                        scope = rule.get("instance_family", rule.get("service", "全局"))
                        applied.append(f"PPA {scope} {pct}%")
                        break  # 一个 PPA 规则匹配即止

    return round(current_price, 6), applied


def load_workload(input_path: str) -> list[dict]:
    """加载 CSV 或 Excel 工作负载文件"""
    path = Path(input_path)
    if path.suffix in (".xlsx", ".xls"):
        try:
            import openpyxl
            wb = openpyxl.load_workbook(path, read_only=True)
            ws = wb.active
            rows = list(ws.iter_rows(values_only=True))
            if not rows:
                return []
            headers = [str(h).strip().lower() if h else "" for h in rows[0]]
            items = []
            for row in rows[1:]:
                item = {}
                for i, h in enumerate(headers):
                    if not h:
                        continue
                    item[h] = str(row[i]).strip() if i < len(row) and row[i] is not None else ""
                items.append(item)
            wb.close()
            return items
        except ImportError:
            print("[ERROR] 需要 openpyxl 库来读取 Excel 文件: pip install openpyxl", file=sys.stderr)
            sys.exit(1)
    else:
        items = []
        with open(path, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                items.append({k.strip().lower(): v.strip() for k, v in row.items()
                              if k is not None and v is not None})
        return items


def normalize_billing_mode(mode: str) -> str:
    """将简化的计费模式名称标准化为完整名称（与smart_import.py保持一致）"""
    # 处理简化名称：ri-1y-no-upfront -> ri-standard-1yr-no
    if mode.startswith("ri-") and not mode.startswith("ri-sp-") and not mode.startswith("ri-standard-") and not mode.startswith("ri-convertible-"):
        # 默认为 standard RI
        mode = mode.replace("ri-", "ri-standard-")
    if mode.startswith("sp-") and not mode.startswith("sp-compute-") and not mode.startswith("sp-instance-"):
        # 默认为 compute SP
        mode = mode.replace("sp-", "sp-compute-")
    # 标准化年份表示：1y -> 1yr, 3y -> 3yr
    # 移除 -upfront 后缀（如果存在）
    return mode.replace("1y-", "1yr-").replace("3y-", "3yr-").replace("-upfront", "")


def get_price_for_item(item: dict, billing_mode: str = "on-demand") -> Optional[dict]:
    """查询单个条目的价格"""
    service = item.get("service", "")
    region = item.get("region", "cn-north-1")
    instance_type = item.get("instance_type", "")

    if not service:
        return None

    # 标准化计费模式格式
    normalized_mode = normalize_billing_mode(billing_mode)

    # 区域映射：某些服务只在特定区域有价格数据
    if service in REGION_OVERRIDE:
        override = REGION_OVERRIDE[service]
        if override != region:
            print(f"[INFO] {service} 使用 {override} 区域价格数据", file=sys.stderr)
            region = override

    # 构建过滤器
    user_filters = {}

    # EBS Storage: 使用 productFamily + volumeApiName 过滤
    # 兼容 CSV 加载后 key 被 lowercase 的情况
    product_family = item.get("productFamily") or item.get("productfamily") or ""

    # EBS 映射：当 service=="AmazonEBS" 时，查价用 "AmazonEC2" + productFamily="Storage"
    query_service = service
    if service == "AmazonEBS":
        query_service = "AmazonEC2"
        product_family = "Storage"
        # EBS Storage 不支持 RI/SP，强制使用 on-demand
        if normalized_mode != "on-demand":
            print(f"[WARN] EBS Storage 不支持 {normalized_mode}，改用 on-demand", file=sys.stderr)
            normalized_mode = "on-demand"

    if product_family == "Storage" and (service == "AmazonEC2" or service == "AmazonEBS"):
        user_filters["productFamily"] = "Storage"
        volume_api_name = (item.get("volumeApiName")
                           or item.get("volumeapiname") or "gp3")
        user_filters["volumeApiName"] = volume_api_name
    else:
        # 通用 productFamily 过滤器（如 NAT Gateway, Load Balancer 等）
        if product_family:
            user_filters["productFamily"] = product_family
        if instance_type:
            user_filters["instanceType"] = instance_type
        if item.get("os"):
            user_filters["operatingSystem"] = item["os"]

    if item.get("engine"):
        if service == "AmazonElastiCache":
            user_filters["cacheEngine"] = item["engine"]
        else:
            user_filters["databaseEngine"] = item["engine"]

    # RDS: 部署模式过滤器，默认 Single-AZ（避免查到 Multi-AZ 价格两倍）
    if service == "AmazonRDS":
        deployment_option = (item.get("deployment_option") or "").strip()
        if not deployment_option:
            deployment_option = "Single-AZ"
        user_filters["deploymentOption"] = deployment_option

    # S3 存储类别过滤器（AWS Pricing API 中 S3 用 volumeType 字段表示存储类别）
    if service == "AmazonS3" and item.get("storageClass"):
        user_filters["volumeType"] = item["storageClass"]

    # 查询 API，无结果时降级到本地缓存
    products = query_api(query_service, region, user_filters, max_results=3)
    if not products:
        products = query_cache(query_service, region, user_filters)
    if not products:
        return None

    pricing = extract_pricing(products[0])

    result = {
        "attributes": pricing["attributes"],
        "on_demand_hourly": None,
        "ri_hourly": None,
        "ri_upfront": None,
        "sp_hourly": None,
        "billing_mode": billing_mode,
    }

    # 提取按需价格
    od = pricing.get("on_demand")
    if od and od["price"] != "N/A":
        try:
            result["on_demand_hourly"] = float(od["price"])
            result["currency"] = od.get("currency", "CNY")
        except (ValueError, TypeError):
            pass

    # 如果请求 RI 价格
    if normalized_mode.startswith("ri-"):
        ri_config = RI_TERM_MAP.get(normalized_mode)
        if ri_config:
            offering_class, lease, purchase_option = ri_config
            for ri in pricing.get("reserved", []):
                if (ri["offering_class"].lower() == offering_class.lower() and
                    lease.replace("yr", "") in ri["lease_length"] and
                    ri["purchase_option"].lower() == purchase_option.lower()):
                    upfront = 0.0
                    hourly = 0.0
                    for dim in ri["price_dimensions"]:
                        try:
                            p = float(dim["price"])
                            if dim["unit"] == "Quantity" or "upfront" in dim.get("description", "").lower():
                                upfront = p
                            else:
                                hourly = p
                        except (ValueError, TypeError):
                            continue
                    years = 3 if "3" in lease else 1
                    effective = (upfront / (years * 8760)) + hourly
                    result["ri_hourly"] = round(effective, 6)
                    result["ri_upfront"] = upfront
                    break

    # 如果请求 SP 价格
    if normalized_mode.startswith("sp-"):
        sp_config = SP_TERM_MAP.get(normalized_mode)
        # SP 适用于 EC2, Lambda, ECS (与 smart_import.py 的 SP_APPLICABLE_SERVICES 保持一致)
        if sp_config and service in {"AmazonEC2", "AWSLambda", "AmazonECS"}:
            sp_type, lease, purchase_option = sp_config
            # 查询 Savings Plans 价格
            sp_data = query_savings_plans(region, instance_type)
            for sp in sp_data:
                if (sp["sp_type"] == sp_type and
                    lease.replace("yr", "") in sp["term"] and
                    sp["purchase_option"].lower() == purchase_option.lower()):
                    result["sp_hourly"] = sp["hourly_rate"]
                    break

    return result


def calculate_item_cost(item: dict, price_data: dict, discount_config: dict,
                       include_tax: bool = False) -> dict:
    """计算单个条目的成本"""
    quantity = int(item.get("quantity", 1) or 1)
    usage_hours = float(item.get("usage_hours", 720) or 720)
    billing_mode = item.get("billing_mode", "on-demand") or "on-demand"
    service = item.get("service", "")
    instance_type = item.get("instance_type", "")
    instance_family = instance_type.split(".")[0] if instance_type else ""

    result = {
        "service": service,
        "instance_type": instance_type,
        "region": item.get("region", "cn-north-1"),
        "quantity": quantity,
        "usage_hours": usage_hours,
        "engine": item.get("engine", ""),
        "engine_version": item.get("engine_version", ""),
        "os": item.get("os", ""),
        "storage_gb": item.get("storage_gb", ""),
        "productFamily": item.get("productFamily") or item.get("productfamily", ""),
        "volumeApiName": item.get("volumeApiName") or item.get("volumeapiname", ""),
        "storageClass": item.get("storageClass") or item.get("storageclass", ""),
        "deployment_option": item.get("deployment_option", ""),
        "billing_mode": billing_mode,
        "notes": item.get("notes", ""),
        "original_request": item.get("original_request", ""),
        "currency": price_data.get("currency", "CNY"),
        "sheet_name": item.get("sheet_name", ""),
        "section": item.get("section", ""),
    }

    # 确定小时费率
    if billing_mode.startswith("ri-") and price_data.get("ri_hourly") is not None:
        hourly = price_data["ri_hourly"]
        upfront_per_unit = price_data.get("ri_upfront", 0)
    elif billing_mode.startswith("sp-") and price_data.get("sp_hourly") is not None:
        hourly = price_data["sp_hourly"]
        upfront_per_unit = 0  # SP upfront 取决于承诺金额，不是每实例固定
    else:
        hourly = price_data.get("on_demand_hourly", 0) or 0
        upfront_per_unit = 0
        # 如果找不到指定计费模式的价格，静默使用按需价格
        if billing_mode != "on-demand" and (billing_mode.startswith("ri-") or billing_mode.startswith("sp-")):
            billing_mode = "on-demand"

    # 应用折扣
    hourly_after_discount, applied_discounts = apply_discounts(
        hourly, service, instance_family, discount_config
    )

    # 对 upfront_per_unit 也应用折扣（EDP 折扣适用于全部账单包括 RI 预付）
    upfront_per_unit_after_discount, _ = apply_discounts(
        upfront_per_unit, service, instance_family, discount_config
    )

    # 计算成本
    product_family = item.get("productFamily") or item.get("productfamily") or ""
    STORAGE_SERVICES = {"AmazonEBS", "AmazonS3", "AmazonEFS", "AmazonFSx", "AmazonGlacier"}
    is_storage_service = (
        service in STORAGE_SERVICES
        or (product_family == "Storage" and service in ("AmazonEC2", "AmazonEBS"))
    )

    if is_storage_service:
        # 存储服务: 价格单位是 per GB-month，不是 per hour
        storage_gb = float(item.get("storage_gb", 0) or 0)
        monthly_per_unit = hourly_after_discount * max(storage_gb, 1)
    else:
        monthly_per_unit = hourly_after_discount * usage_hours
    monthly_total = monthly_per_unit * quantity
    upfront_total = upfront_per_unit_after_discount * quantity

    if include_tax:
        vat_rate = discount_config.get("tax", {}).get("vat_rate", 6) / 100
        monthly_total *= (1 + vat_rate)
        upfront_total *= (1 + vat_rate)

    # ── Extended Support 附加费用 ──
    es_mode = (item.get("extended_support") or "").strip().lower()
    es_monthly_total = 0.0
    es_hourly = 0.0
    es_usagetype = ""
    es_unit = ""
    es_error = ""
    if es_mode in ("yr1-2", "yr3") and service in ("AmazonEKS", "AmazonRDS"):
        es_region = item.get("region", "cn-north-1")
        if service in REGION_OVERRIDE:
            es_region = REGION_OVERRIDE[service]

        if service == "AmazonEKS":
            es_usagetype = build_eks_extended_support_usagetype(es_region)
            es_data = query_extended_support_price("AmazonEKS", es_region, es_usagetype)
            if es_data:
                es_hourly = es_data["price"]
                es_unit = es_data.get("unit", "Hours")
                # EKS: per cluster per hour
                es_monthly_per_unit = es_hourly * usage_hours
                es_monthly_total = es_monthly_per_unit * quantity
            else:
                es_error = f"price not found ({es_usagetype})"
        elif service == "AmazonRDS":
            engine = _normalize_rds_engine(item.get("engine", ""))
            engine_version = (item.get("engine_version") or "").strip()
            if not engine:
                es_error = "missing engine"
            elif not engine_version:
                es_error = "missing engine_version"
            else:
                es_usagetype = build_rds_extended_support_usagetype(
                    es_region, es_mode, engine, engine_version
                )
                if not es_usagetype:
                    es_error = f"unknown engine/version ({engine} {engine_version})"
                else:
                    es_data = query_extended_support_price("AmazonRDS", es_region, es_usagetype)
                    if not es_data:
                        es_error = f"price not found ({es_usagetype})"
                    else:
                        es_hourly = es_data["price"]
                        es_unit = es_data.get("unit", "vCPU-hour")
                        # RDS: per vCPU per hour
                        vcpu_attr = price_data.get("attributes", {}).get("vcpu", "")
                        try:
                            vcpu = int(vcpu_attr) if vcpu_attr else 0
                        except (ValueError, TypeError):
                            vcpu = 0
                        if vcpu <= 0:
                            vcpu = _vcpu_from_instance_type(instance_type)
                        if vcpu > 0:
                            es_monthly_per_unit = es_hourly * usage_hours * vcpu
                            es_monthly_total = es_monthly_per_unit * quantity
                        else:
                            es_error = f"missing vcpu (instance_type={instance_type})"

        if es_monthly_total > 0 and include_tax:
            vat_rate = discount_config.get("tax", {}).get("vat_rate", 6) / 100
            es_monthly_total *= (1 + vat_rate)

        if es_error:
            print(f"[WARN] Extended Support 查价失败 ({service} {instance_type}): {es_error}",
                  file=sys.stderr)

    result.update({
        "hourly_list": hourly,
        "hourly_after_discount": hourly_after_discount,
        "monthly_per_unit": round(monthly_per_unit, 2),
        "monthly_total": round(monthly_total, 2),
        "upfront_total": round(upfront_total, 2),
        "yearly_total": round(monthly_total * 12, 2),
        "applied_discounts": applied_discounts,
        "include_tax": include_tax,
        "extended_support": es_mode,
        "extended_support_hourly": round(es_hourly, 6) if es_hourly else 0,
        "extended_support_usagetype": es_usagetype,
        "extended_support_unit": es_unit,
        "extended_support_monthly_total": round(es_monthly_total, 2),
        "extended_support_yearly_total": round(es_monthly_total * 12, 2),
        "extended_support_error": es_error,
    })

    return result


def format_results(results: list[dict]) -> str:
    """格式化计算结果"""
    lines = []
    lines.append(f"{'服务':<15} {'实例类型':<18} {'区域':<16} {'数量':>4} {'计费模式':<30} "
                 f"{'小时费率':>12} {'月费用/台':>14} {'月费用合计':>14} {'年费用合计':>14} {'折扣':>20}")
    lines.append("=" * 170)

    total_monthly = 0
    total_yearly = 0
    total_upfront = 0
    total_es_monthly = 0
    total_es_yearly = 0
    currency = "CNY"

    for r in results:
        currency = r.get("currency", "CNY")
        discounts_str = ", ".join(r.get("applied_discounts", [])) or "-"
        warning = ""  # 不再显示警告

        lines.append(
            f"{r['service']:<15} {r['instance_type']:<18} {r['region']:<16} {r['quantity']:>4} "
            f"{r['billing_mode']:<30} "
            f"{currency} {r['hourly_after_discount']:>8.4f} "
            f"{currency} {r['monthly_per_unit']:>10,.2f} "
            f"{currency} {r['monthly_total']:>10,.2f} "
            f"{currency} {r['yearly_total']:>10,.2f} "
            f"{discounts_str:>20}{warning}"
        )
        total_monthly += r["monthly_total"]
        total_yearly += r["yearly_total"]
        total_upfront += r.get("upfront_total", 0)

        # Extended Support 单独一行
        es_monthly = r.get("extended_support_monthly_total", 0) or 0
        if es_monthly > 0:
            es_label = f"{r['service']} Extended Support ({r.get('extended_support', '')})"
            es_yearly = r.get("extended_support_yearly_total", es_monthly * 12)
            lines.append(
                f"  ↳ {es_label:<55} "
                f"{currency} {r.get('extended_support_hourly', 0):>8.4f} "
                f"{'':<14} "
                f"{currency} {es_monthly:>10,.2f} "
                f"{currency} {es_yearly:>10,.2f}"
            )
            total_es_monthly += es_monthly
            total_es_yearly += es_yearly

    lines.append("=" * 170)
    lines.append(f"{'合计':<15} {'':<18} {'':<16} {'':<4} {'':<30} "
                 f"{'':>12} {'':<14} "
                 f"{currency} {total_monthly:>10,.2f} "
                 f"{currency} {total_yearly:>10,.2f}")

    if total_es_monthly > 0:
        lines.append(f"{'Extended Support 合计':<15} {'':<18} {'':<16} {'':<4} {'':<30} "
                     f"{'':>12} {'':<14} "
                     f"{currency} {total_es_monthly:>10,.2f} "
                     f"{currency} {total_es_yearly:>10,.2f}")
        grand_monthly = total_monthly + total_es_monthly
        grand_yearly = total_yearly + total_es_yearly
        lines.append(f"{'总计（含ES）':<15} {'':<18} {'':<16} {'':<4} {'':<30} "
                     f"{'':>12} {'':<14} "
                     f"{currency} {grand_monthly:>10,.2f} "
                     f"{currency} {grand_yearly:>10,.2f}")

    if total_upfront > 0:
        lines.append(f"\n预付总额: {currency} {total_upfront:,.2f}")

    tax_note = " (含税)" if results and results[0].get("include_tax") else " (不含税)"
    lines.append(f"\n注: 以上金额{tax_note}")

    # 检查折扣配置
    has_discounts = any(r.get("applied_discounts") for r in results)
    if not has_discounts:
        lines.append("\n💡 提示: 未配置任何折扣。如有 EDP/PPA 折扣，请编辑 discount-config.yaml。")

    return "\n".join(lines)


def save_csv(results: list[dict], output_path: str):
    """保存结果到 CSV"""
    if not results:
        return

    fieldnames = [
        "sheet_name", "service", "instance_type", "region", "quantity", "usage_hours",
        "billing_mode", "currency", "hourly_list", "hourly_after_discount",
        "monthly_per_unit", "monthly_total", "upfront_total", "yearly_total",
        "engine", "engine_version", "os", "storage_gb",
        "productFamily", "volumeApiName", "storageClass",
        "deployment_option",
        "extended_support", "extended_support_hourly", "extended_support_usagetype",
        "extended_support_monthly_total", "extended_support_yearly_total",
        "extended_support_error",
        "applied_discounts", "notes", "original_request", "section", "warning",
    ]

    with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for r in results:
            row = dict(r)
            row["applied_discounts"] = ", ".join(r.get("applied_discounts", []))
            writer.writerow(row)

    print(f"\n结果已保存到: {output_path}", file=sys.stderr)


# --- 数据传输费计算 ---

# 中国区出公网流量阶梯定价 (CNY/GB, cn-north-1 参考价)
DATA_TRANSFER_OUT_TIERS = [
    (1, 0.0),          # 前 1GB 免费
    (10 * 1024, 0.933),    # 1GB - 10TB
    (50 * 1024, 0.856),    # 10TB - 50TB
    (150 * 1024, 0.782),   # 50TB - 150TB
    (float("inf"), 0.724), # 150TB+
]

# 跨 AZ 传输费 (CNY/GB)
CROSS_AZ_PRICE = 0.0625

# CloudFront 分发费 (CNY/GB, 阶梯定价)
CLOUDFRONT_TIERS = [
    (10 * 1024, 0.546),     # 前 10TB
    (50 * 1024, 0.507),     # 10TB - 50TB
    (150 * 1024, 0.429),    # 50TB - 150TB
    (500 * 1024, 0.390),    # 150TB - 500TB
    (float("inf"), 0.312),  # 500TB+
]


def _calc_tiered_cost(gb: float, tiers: list[tuple]) -> float:
    """按阶梯计算费用"""
    remaining = gb
    cost = 0.0
    prev_limit = 0
    for limit, price_per_gb in tiers:
        tier_size = limit - prev_limit
        used = min(remaining, tier_size)
        cost += used * price_per_gb
        remaining -= used
        prev_limit = limit
        if remaining <= 0:
            break
    return round(cost, 2)


def calculate_data_transfer_cost(item: dict, discount_config: dict, include_tax: bool = False) -> Optional[dict]:
    """计算数据传输费"""
    transfer_type = item.get("transfer_type", "")
    gb = float(item.get("transfer_gb", 0) or 0)
    if gb <= 0 or not transfer_type:
        return None

    region = item.get("region", "cn-north-1")
    currency = "CNY"
    cost = 0.0
    description = ""

    if transfer_type == "out_to_internet":
        cost = _calc_tiered_cost(gb, DATA_TRANSFER_OUT_TIERS)
        description = "出公网流量（阶梯定价）"
    elif transfer_type == "cross_az":
        cost = round(gb * CROSS_AZ_PRICE, 2)
        description = "跨 AZ 传输"
    elif transfer_type == "same_region":
        cost = 0.0
        description = "同区域内传输（免费）"
    elif transfer_type == "cloudfront":
        cost = _calc_tiered_cost(gb, CLOUDFRONT_TIERS)
        description = "CloudFront 分发"
    else:
        description = f"未知传输类型: {transfer_type}"
        return None

    # 应用折扣
    service = "AWSDataTransfer"
    cost_after_discount, applied_discounts = apply_discounts(cost, service, "", discount_config)

    if include_tax:
        vat_rate = discount_config.get("tax", {}).get("vat_rate", 6) / 100
        cost_after_discount *= (1 + vat_rate)
        cost_after_discount = round(cost_after_discount, 2)

    return {
        "service": "DataTransfer",
        "instance_type": "",
        "region": region,
        "quantity": 1,
        "usage_hours": 0,
        "billing_mode": transfer_type,
        "notes": f"{description} ({gb:.1f} GB)",
        "currency": currency,
        "hourly_list": 0,
        "hourly_after_discount": 0,
        "monthly_per_unit": cost_after_discount,
        "monthly_total": cost_after_discount,
        "upfront_total": 0,
        "yearly_total": round(cost_after_discount * 12, 2),
        "applied_discounts": applied_discounts,
        "include_tax": include_tax,
        "transfer_type": transfer_type,
        "transfer_gb": gb,
        "transfer_cost_before_discount": cost,
        "sheet_name": item.get("sheet_name", ""),
        "section": item.get("section", ""),
        "original_request": item.get("original_request", ""),
    }


def compare_modes(items: list[dict], modes: list[str], discount_config: dict,
                  include_tax: bool = False) -> str:
    """多方案对比"""
    lines = []
    lines.append("方案对比:")
    lines.append("=" * 100)

    mode_totals = {mode: {"monthly": 0, "yearly": 0, "upfront": 0} for mode in modes}

    for item in items:
        instance_type = item.get("instance_type", "")
        lines.append(f"\n  {item.get('service', '')} {instance_type} x{item.get('quantity', 1)}:")

        for mode in modes:
            item_copy = dict(item)
            item_copy["billing_mode"] = mode
            price_data = get_price_for_item(item_copy, billing_mode=mode)
            if not price_data:
                lines.append(f"    {mode:<35} 无数据")
                continue

            cost = calculate_item_cost(item_copy, price_data, discount_config, include_tax)
            mode_totals[mode]["monthly"] += cost["monthly_total"]
            mode_totals[mode]["yearly"] += cost["yearly_total"]
            mode_totals[mode]["upfront"] += cost.get("upfront_total", 0)

            currency = cost.get("currency", "CNY")
            lines.append(
                f"    {mode:<35} 月费: {currency} {cost['monthly_total']:>10,.2f}  "
                f"年费: {currency} {cost['yearly_total']:>10,.2f}"
            )

    lines.append("\n" + "=" * 100)
    lines.append("合计对比:")
    od_yearly = mode_totals.get("on-demand", {}).get("yearly", 0)
    for mode in modes:
        t = mode_totals[mode]
        savings = ""
        if od_yearly > 0 and mode != "on-demand":
            pct = (1 - t["yearly"] / od_yearly) * 100
            savings = f"  (vs按需: {pct:+.1f}%)"
        upfront_str = f"  预付: CNY {t['upfront']:,.2f}" if t["upfront"] > 0 else ""
        lines.append(
            f"  {mode:<35} 月费: CNY {t['monthly']:>10,.2f}  "
            f"年费: CNY {t['yearly']:>10,.2f}{upfront_str}{savings}"
        )

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="AWS 中国区批量成本计算引擎")
    parser.add_argument("--input", "-i", required=True, help="输入文件 (CSV 或 Excel)")
    parser.add_argument("--region", "-r", default="cn-north-1", help="默认区域")
    parser.add_argument("--discount-config", "-d",
                       default=str(SCRIPT_DIR.parent / "discount-config.yaml"),
                       help="折扣配置文件路径")
    parser.add_argument("--output", "-o", help="输出 CSV 文件路径")
    parser.add_argument("--compare", "-c", help="多方案对比，逗号分隔的计费模式")
    parser.add_argument("--include-tax", action="store_true", help="含 6%% 增值税")
    parser.add_argument("--json", action="store_true", help="JSON 格式输出")
    parser.add_argument("--profile", default=None,
                       help="AWS CLI profile (默认: 不指定则用 AWS CLI 默认配置)")
    args = parser.parse_args()
    # 设置 profile
    if args.profile:
        import query_price
        query_price.AWS_PROFILE = args.profile

    # 加载折扣配置
    discount_config = load_discount_config(args.discount_config)

    # 加载工作负载
    items = load_workload(args.input)
    if not items:
        print("错误: 输入文件为空或格式不正确", file=sys.stderr)
        sys.exit(1)

    print(f"已加载 {len(items)} 个工作负载条目", file=sys.stderr)

    # 为未指定区域的条目填充默认区域
    for item in items:
        if not item.get("region"):
            item["region"] = args.region

    # 多方案对比模式
    if args.compare:
        modes = [m.strip() for m in args.compare.split(",")]
        print(compare_modes(items, modes, discount_config, args.include_tax))
        return

    # 逐条计算
    results = []
    data_transfer_results = []
    all_results = []
    for item in items:
        # 处理数据传输费条目
        if item.get("transfer_type"):
            dt_result = calculate_data_transfer_cost(item, discount_config, args.include_tax)
            if dt_result:
                data_transfer_results.append(dt_result)
                all_results.append(dt_result)
            continue

        billing_mode = item.get("billing_mode", "on-demand") or "on-demand"
        print(f"  查询 {item.get('service', '')} {item.get('instance_type', '')} ...", file=sys.stderr)
        price_data = get_price_for_item(item, billing_mode=billing_mode)
        if not price_data:
            results.append({
                "service": item.get("service", ""),
                "instance_type": item.get("instance_type", ""),
                "region": item.get("region", ""),
                "quantity": int(item.get("quantity", 1) or 1),
                "billing_mode": billing_mode,
                "hourly_list": 0, "hourly_after_discount": 0,
                "monthly_per_unit": 0, "monthly_total": 0,
                "upfront_total": 0, "yearly_total": 0,
                "applied_discounts": [],
                "notes": item.get("notes", ""),
                "original_request": item.get("original_request", ""),
                "currency": "CNY",
                "sheet_name": item.get("sheet_name", ""),
                "section": item.get("section", ""),
            })
            all_results.append(results[-1])
            continue

        cost = calculate_item_cost(item, price_data, discount_config, args.include_tax)
        results.append(cost)
        all_results.append(cost)

    # 输出
    if args.json:
        for r in all_results:
            if isinstance(r.get("applied_discounts"), list):
                r["applied_discounts"] = ", ".join(r.get("applied_discounts", []))
        print(json.dumps(all_results, ensure_ascii=False, indent=2))
    else:
        print("\n" + format_results(results))
        if data_transfer_results:
            print("\n数据传输费明细:")
            print("=" * 80)
            dt_total = 0
            for dt in data_transfer_results:
                print(f"  {dt['notes']:<40} {dt['currency']} {dt['monthly_total']:>10,.2f}/月  "
                      f"{dt['currency']} {dt['yearly_total']:>10,.2f}/年")
                dt_total += dt["monthly_total"]
            print("-" * 80)
            print(f"  {'数据传输费合计':<40} CNY {dt_total:>10,.2f}/月  CNY {dt_total * 12:>10,.2f}/年")

    if args.output:
        if args.output.endswith('.xlsx'):
            from generate_quote import generate_quote
            gen_config = {
                "customer": "",
                "validity": 30,
                "include_tax": args.include_tax,
            }
            wb = generate_quote(items, all_results, gen_config)
            wb.save(args.output)
            print(f"\n报价单已生成: {args.output}", file=sys.stderr)
        else:
            save_csv(all_results, args.output)


if __name__ == "__main__":
    main()
