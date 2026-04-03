#!/usr/bin/env python3
"""AWS 中国区价格查询工具

数据源优先级:
1. Price List Query API（实时查询）
2. Bulk API 本地缓存（API 不可用时降级）

用法:
  python3 query_price.py --service AmazonEC2 --region cn-north-1 \
    --filters instanceType=c6i.xlarge operatingSystem=Linux

  python3 query_price.py --service AmazonRDS --region cn-north-1 \
    --filters instanceType=db.r6g.large databaseEngine=MySQL

  python3 query_price.py --service AmazonS3 --region cn-north-1

  python3 query_price.py --list-services
"""

import argparse
import json
import os
import sys
import subprocess
from pathlib import Path
from typing import Optional

SCRIPT_DIR = Path(__file__).parent
DATA_DIR = SCRIPT_DIR.parent / "data"
CACHE_DIR = DATA_DIR / "cache"
INDEX_DIR = DATA_DIR / "index"

AWS_PROFILE = os.environ.get("AWS_PROFILE", "default")
PRICING_REGION = "cn-northwest-1"

# 服务定价区域映射：某些服务只在特定区域有价格数据
REGION_OVERRIDE = {
    # 仅北京区有价格
    "AWSCodeCommit": "cn-north-1",
    "AWSGreengrass": "cn-north-1",
    "AWSIoTAnalytics": "cn-north-1",
    "AWSIoTEvents": "cn-north-1",
    "AWSIoTSiteWise": "cn-north-1",
    "AmazonKinesisVideo": "cn-north-1",
    "AmazonPersonalize": "cn-north-1",
    "AmazonQuickSight": "cn-north-1",
    # 仅宁夏区有价格
    "AWSCostExplorer": "cn-northwest-1",
    "AWSElementalMediaConvert": "cn-northwest-1",
    "AmazonPolly": "cn-northwest-1",
    "AmazonWorkSpaces": "cn-northwest-1",
}

# EC2 默认过滤器（查询实例价格时补全常用默认值）
EC2_DEFAULT_FILTERS = {
    "operatingSystem": "Linux",
    "tenancy": "Shared",
    "capacitystatus": "Used",
    "preInstalledSw": "NA",
}

# RI 类型映射
RI_TERM_MAP = {
    "ri-standard-1yr-no": ("Standard", "1yr", "No Upfront"),
    "ri-standard-1yr-partial": ("Standard", "1yr", "Partial Upfront"),
    "ri-standard-1yr-all": ("Standard", "1yr", "All Upfront"),
    "ri-standard-3yr-no": ("Standard", "3yr", "No Upfront"),
    "ri-standard-3yr-partial": ("Standard", "3yr", "Partial Upfront"),
    "ri-standard-3yr-all": ("Standard", "3yr", "All Upfront"),
    "ri-convertible-1yr-no": ("Convertible", "1yr", "No Upfront"),
    "ri-convertible-1yr-partial": ("Convertible", "1yr", "Partial Upfront"),
    "ri-convertible-1yr-all": ("Convertible", "1yr", "All Upfront"),
    "ri-convertible-3yr-no": ("Convertible", "3yr", "No Upfront"),
    "ri-convertible-3yr-partial": ("Convertible", "3yr", "Partial Upfront"),
    "ri-convertible-3yr-all": ("Convertible", "3yr", "All Upfront"),
}


def run_aws_cli(args: list[str], timeout: int = 30, profile: str = None) -> Optional[dict]:
    """执行 AWS CLI 命令并返回 JSON 结果"""
    _profile = profile or AWS_PROFILE
    cmd = ["aws"] + args + ["--region", PRICING_REGION, "--profile", _profile, "--output", "json"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if result.returncode != 0:
            print(f"[WARN] AWS CLI 错误: {result.stderr.strip()}", file=sys.stderr)
            return None
        return json.loads(result.stdout)
    except subprocess.TimeoutExpired:
        print(f"[WARN] AWS CLI 超时 ({timeout}s)", file=sys.stderr)
        return None
    except (json.JSONDecodeError, FileNotFoundError) as e:
        print(f"[WARN] AWS CLI 执行失败: {e}", file=sys.stderr)
        return None


def list_services() -> list[dict]:
    """列出所有可用服务"""
    services = []
    next_token = None
    while True:
        args = ["pricing", "describe-services"]
        if next_token:
            args += ["--next-token", next_token]
        data = run_aws_cli(args, timeout=60)
        if not data:
            break
        services.extend(data.get("Services", []))
        next_token = data.get("NextToken")
        if not next_token:
            break
    return services


def build_api_filters(service: str, region: str, user_filters: dict) -> list[dict]:
    """构建 API 过滤器列表"""
    filters = [
        {"Type": "TERM_MATCH", "Field": "regionCode", "Value": region},
    ]

    # 对 EC2 实例查询补全默认过滤器
    if service == "AmazonEC2" and "instanceType" in user_filters:
        merged = {**EC2_DEFAULT_FILTERS, **user_filters}
    else:
        merged = dict(user_filters)

    for field, value in merged.items():
        filters.append({"Type": "TERM_MATCH", "Field": field, "Value": value})

    return filters


def query_api(service: str, region: str, user_filters: dict, max_results: int = 20) -> Optional[list[dict]]:
    """通过 Price List Query API 查询价格"""
    filters = build_api_filters(service, region, user_filters)
    args = [
        "pricing", "get-products",
        "--service-code", service,
        "--filters", json.dumps(filters),
        "--max-results", str(max_results),
    ]

    data = run_aws_cli(args, timeout=30)
    if not data:
        return None

    products = []
    for price_str in data.get("PriceList", []):
        if isinstance(price_str, str):
            products.append(json.loads(price_str))
        else:
            products.append(price_str)
    return products


def query_cache(service: str, region: str, user_filters: dict) -> Optional[list[dict]]:
    """从本地缓存查询价格"""
    # 尝试索引文件
    if "instanceType" in user_filters:
        instance_type = user_filters["instanceType"]
        family = instance_type.split(".")[0]
        index_file = INDEX_DIR / service / region / f"{family}.json"
        if index_file.exists():
            try:
                with open(index_file) as f:
                    indexed = json.load(f)
                # 在索引中过滤匹配项
                return _filter_products(indexed, user_filters)
            except (json.JSONDecodeError, IOError) as e:
                print(f"[WARN] 读取索引文件失败: {e}", file=sys.stderr)

    # 尝试完整缓存文件
    cache_file = CACHE_DIR / f"{service}_{region}.json"
    if cache_file.exists():
        try:
            # 流式读取大文件，只提取匹配项
            return _search_cache_file(cache_file, user_filters)
        except (json.JSONDecodeError, IOError) as e:
            print(f"[WARN] 读取缓存文件失败: {e}", file=sys.stderr)

    return None


def _filter_products(products: list[dict], user_filters: dict) -> list[dict]:
    """根据过滤器筛选产品"""
    matched = []
    for product in products:
        attrs = product.get("product", {}).get("attributes", {})
        match = True
        for field, value in user_filters.items():
            if attrs.get(field, "").lower() != value.lower():
                match = False
                break
        if match:
            matched.append(product)
    return matched


def _search_cache_file(cache_file: Path, user_filters: dict, limit: int = 20) -> list[dict]:
    """在缓存文件中搜索匹配产品（避免一次性加载大文件到内存）"""
    matched = []
    with open(cache_file) as f:
        data = json.load(f)

    products = data.get("products", data) if isinstance(data, dict) else data
    if isinstance(products, dict):
        products = list(products.values())

    for product in products:
        attrs = product.get("product", product).get("attributes", {})
        match = True
        for field, value in user_filters.items():
            if attrs.get(field, "").lower() != value.lower():
                match = False
                break
        if match:
            matched.append(product)
            if len(matched) >= limit:
                break
    return matched


# --- Savings Plans 查询 ---

SP_TERM_MAP = {
    "sp-compute-1yr-no": ("ComputeSavingsPlans", "1yr", "No Upfront"),
    "sp-compute-1yr-partial": ("ComputeSavingsPlans", "1yr", "Partial Upfront"),
    "sp-compute-1yr-all": ("ComputeSavingsPlans", "1yr", "All Upfront"),
    "sp-compute-3yr-no": ("ComputeSavingsPlans", "3yr", "No Upfront"),
    "sp-compute-3yr-partial": ("ComputeSavingsPlans", "3yr", "Partial Upfront"),
    "sp-compute-3yr-all": ("ComputeSavingsPlans", "3yr", "All Upfront"),
    "sp-instance-1yr-no": ("EC2InstanceSavingsPlans", "1yr", "No Upfront"),
    "sp-instance-1yr-partial": ("EC2InstanceSavingsPlans", "1yr", "Partial Upfront"),
    "sp-instance-1yr-all": ("EC2InstanceSavingsPlans", "1yr", "All Upfront"),
    "sp-instance-3yr-no": ("EC2InstanceSavingsPlans", "3yr", "No Upfront"),
    "sp-instance-3yr-partial": ("EC2InstanceSavingsPlans", "3yr", "Partial Upfront"),
    "sp-instance-3yr-all": ("EC2InstanceSavingsPlans", "3yr", "All Upfront"),
}


def query_savings_plans(region: str, instance_type: str = "", operation: str = "RunInstances") -> list[dict]:
    """从 Bulk API 缓存文件查询 Savings Plans 价格。

    SP 数据不在 Query API 中（返回空），必须用 Bulk API 下载的文件。
    文件路径: data/cache/ComputeSavingsPlans_{region}.json

    Args:
        region: 区域代码 (cn-north-1 / cn-northwest-1)
        instance_type: 完整实例类型 (如 c6i.xlarge)
        operation: 运行操作，默认 RunInstances (Linux Shared)
    Returns:
        SP 费率列表，每项包含 sp_type, term, purchase_option, hourly_rate
    """
    cache_file = CACHE_DIR / f"ComputeSavingsPlans_{region}.json"
    if not cache_file.exists():
        print(f"[WARN] SP 缓存文件不存在: {cache_file}", file=sys.stderr)
        print(f"  运行: python3 {SCRIPT_DIR}/update_prices.py --region {region} --services ComputeSavingsPlans", file=sys.stderr)
        return []

    with open(cache_file) as f:
        data = json.load(f)

    # 提取实例族 (如 c6i.xlarge -> c6i)
    instance_family = instance_type.split(".")[0] if instance_type and "." in instance_type else ""

    # 构建 SKU -> product 映射
    sku_to_product = {p["sku"]: p for p in data.get("products", [])}

    results = []
    for term in data.get("terms", {}).get("savingsPlan", []):
        sku = term.get("sku", "")
        product = sku_to_product.get(sku)
        if not product:
            continue

        sp_type = product.get("productFamily", "")  # ComputeSavingsPlans or EC2InstanceSavingsPlans
        attrs = product.get("attributes", {})
        purchase_option = attrs.get("purchaseOption", "")
        purchase_term = attrs.get("purchaseTerm", "")

        # Instance SP: 按实例族过滤
        if sp_type == "EC2InstanceSavingsPlans" and instance_family:
            if attrs.get("instanceType", "") != instance_family:
                continue

        # 在 rates 中找匹配的实例类型和操作
        for rate in term.get("rates", []):
            discounted_type = rate.get("discountedInstanceType", "")
            discounted_usage = rate.get("discountedUsageType", "")
            discounted_op = rate.get("discountedOperation", "")

            # 匹配实例类型
            if instance_type and discounted_type != instance_type:
                continue

            # 匹配 Linux Shared (BoxUsage + RunInstances 无后缀)
            if "BoxUsage" not in discounted_usage:
                continue
            if discounted_op != operation:
                continue

            price = float(rate.get("discountedRate", {}).get("price", "0"))
            if price <= 0:
                continue

            results.append({
                "sp_type": sp_type,
                "term": purchase_term,
                "purchase_option": purchase_option,
                "hourly_rate": price,
                "currency": rate.get("discountedRate", {}).get("currency", "CNY"),
                "instance_type": discounted_type,
                "usage_type": discounted_usage,
            })

    # 去重并排序
    seen = set()
    unique = []
    for r in results:
        key = (r["sp_type"], r["term"], r["purchase_option"])
        if key not in seen:
            seen.add(key)
            unique.append(r)
    unique.sort(key=lambda x: x["hourly_rate"])
    return unique


def format_sp_output(sp_data: list[dict], on_demand_hourly: float = 0) -> str:
    """格式化 SP 价格输出"""
    if not sp_data:
        return "无 Savings Plans 数据（请先运行 update_prices.py 下载 SP 缓存）"

    lines = []
    lines.append("Savings Plans 价格:")
    lines.append("-" * 60)

    for sp in sp_data:
        sp_type_short = "Compute SP" if sp["sp_type"] == "ComputeSavingsPlans" else "Instance SP"
        label = f"{sp_type_short} {sp['term']} {sp['purchase_option']}"
        monthly = sp["hourly_rate"] * 730
        saving = ""
        if on_demand_hourly > 0:
            pct = (on_demand_hourly - sp["hourly_rate"]) / on_demand_hourly * 100
            saving = f" [省 {pct:.1f}%]"
        lines.append(f"  {label}: CNY {sp['hourly_rate']:.4f}/hr (¥{monthly:,.2f}/月){saving}")

    return "\n".join(lines)


def _format_sp_for_comparison(sp_data: list[dict]) -> list[dict]:
    """将 SP 数据转换为对比表格式。

    SP 定价模型说明：
    - SP 是按每小时承诺消费金额购买的
    - No/Partial/All Upfront 影响的是承诺费用的支付方式
    - discountedRate 已经反映了不同 upfront 选项的价格差异
    - 表中预付列显示 '*' 表示 SP 预付取决于承诺金额，不是每实例固定金额
    """
    rates = []
    for sp in sp_data:
        sp_type_short = "Compute SP" if sp["sp_type"] == "ComputeSavingsPlans" else "Instance SP"
        label = f"SP {sp_type_short} {sp['term']} {sp['purchase_option']}"
        rates.append({
            "mode": label,
            "hourly": sp["hourly_rate"],
            "monthly": round(sp["hourly_rate"] * 730, 2),
            "yearly": round(sp["hourly_rate"] * 8760, 2),
            "upfront": -1,  # -1 = SP upfront depends on commitment, not per-instance
            "currency": sp.get("currency", "CNY"),
        })
    return rates


# Legacy compat
def extract_sp_pricing(products):
    return []


def extract_pricing(product: dict) -> dict:
    """从产品数据中提取定价信息"""
    result = {
        "attributes": {},
        "on_demand": None,
        "reserved": [],
    }

    # 提取属性
    attrs = product.get("product", {}).get("attributes", {})
    key_attrs = [
        "servicecode", "instanceType", "vcpu", "memory", "storage",
        "networkPerformance", "operatingSystem", "databaseEngine",
        "location", "regionCode", "productFamily", "usagetype",
        "instanceFamily", "physicalProcessor", "currentGeneration",
    ]
    for k in key_attrs:
        if k in attrs:
            result["attributes"][k] = attrs[k]

    terms = product.get("terms", {})

    # On-Demand 价格
    on_demand = terms.get("OnDemand", {})
    for term_key, term_data in on_demand.items():
        for dim_key, dim_data in term_data.get("priceDimensions", {}).items():
            price_per_unit = dim_data.get("pricePerUnit", {})
            cny = price_per_unit.get("CNY", price_per_unit.get("USD", "N/A"))
            currency = "CNY" if "CNY" in price_per_unit else "USD" if "USD" in price_per_unit else "N/A"
            result["on_demand"] = {
                "price": cny,
                "currency": currency,
                "unit": dim_data.get("unit", ""),
                "description": dim_data.get("description", ""),
            }
            break
        break

    # Reserved 价格
    reserved = terms.get("Reserved", {})
    for term_key, term_data in reserved.items():
        term_attrs = term_data.get("termAttributes", {})
        ri_info = {
            "offering_class": term_attrs.get("OfferingClass", ""),
            "lease_length": term_attrs.get("LeaseContractLength", ""),
            "purchase_option": term_attrs.get("PurchaseOption", ""),
            "price_dimensions": [],
        }
        for dim_key, dim_data in term_data.get("priceDimensions", {}).items():
            price_per_unit = dim_data.get("pricePerUnit", {})
            cny = price_per_unit.get("CNY", price_per_unit.get("USD", "N/A"))
            currency = "CNY" if "CNY" in price_per_unit else "USD" if "USD" in price_per_unit else "N/A"
            ri_info["price_dimensions"].append({
                "price": cny,
                "currency": currency,
                "unit": dim_data.get("unit", ""),
                "description": dim_data.get("description", ""),
            })
        result["reserved"].append(ri_info)

    return result


def format_output(pricing: dict, verbose: bool = False) -> str:
    """格式化输出"""
    lines = []
    attrs = pricing["attributes"]

    # 标题行
    title_parts = []
    if "instanceType" in attrs:
        title_parts.append(attrs["instanceType"])
    if "servicecode" in attrs:
        title_parts.append(f"[{attrs['servicecode']}]")
    if "regionCode" in attrs:
        title_parts.append(f"({attrs['regionCode']})")
    lines.append(" ".join(title_parts) if title_parts else "产品信息")
    lines.append("=" * 60)

    # 实例规格
    spec_fields = [
        ("vCPU", "vcpu"), ("内存", "memory"), ("存储", "storage"),
        ("网络", "networkPerformance"), ("操作系统", "operatingSystem"),
        ("数据库引擎", "databaseEngine"), ("产品族", "productFamily"),
        ("实例族", "instanceFamily"), ("当前代", "currentGeneration"),
    ]
    specs = [(label, attrs[key]) for label, key in spec_fields if key in attrs]
    if specs:
        lines.append("规格: " + " | ".join(f"{l}: {v}" for l, v in specs))
        lines.append("")

    # On-Demand 价格
    od = pricing["on_demand"]
    if od:
        lines.append(f"按需价格: {od['currency']} {od['price']} / {od['unit']}")
        if verbose and od.get("description"):
            lines.append(f"  说明: {od['description']}")
        lines.append("")

    # Reserved 价格
    if pricing["reserved"]:
        lines.append("预留实例价格:")
        lines.append("-" * 60)
        # 按类型和期限排序
        sorted_ri = sorted(pricing["reserved"],
                          key=lambda r: (r["offering_class"], r["lease_length"], r["purchase_option"]))
        for ri in sorted_ri:
            label = f"  {ri['offering_class']} {ri['lease_length']} {ri['purchase_option']}:"
            dims = ri["price_dimensions"]
            if len(dims) == 1:
                d = dims[0]
                lines.append(f"{label} {d['currency']} {d['price']} / {d['unit']}")
            else:
                lines.append(label)
                for d in dims:
                    unit_label = d["unit"]
                    desc = d.get("description", "")
                    if "Upfront" in desc or "upfront" in unit_label.lower() or unit_label == "Quantity":
                        lines.append(f"    预付: {d['currency']} {d['price']}")
                    else:
                        lines.append(f"    小时费: {d['currency']} {d['price']} / {d['unit']}")
        lines.append("")

    return "\n".join(lines)


def calculate_effective_hourly(pricing: dict) -> list[dict]:
    """计算各种计费模式的有效小时费率，便于对比"""
    results = []
    od = pricing["on_demand"]
    if od and od["price"] != "N/A":
        try:
            od_hourly = float(od["price"])
            results.append({
                "mode": "On-Demand",
                "hourly": od_hourly,
                "monthly": od_hourly * 730,
                "yearly": od_hourly * 8760,
                "currency": od["currency"],
            })
        except (ValueError, TypeError):
            pass

    for ri in pricing.get("reserved", []):
        upfront = 0.0
        hourly = 0.0
        currency = "CNY"
        for dim in ri["price_dimensions"]:
            try:
                price = float(dim["price"])
                currency = dim.get("currency", currency)
                if dim["unit"] == "Quantity" or "upfront" in dim.get("description", "").lower():
                    upfront = price
                else:
                    hourly = price
            except (ValueError, TypeError):
                continue

        lease = ri["lease_length"]
        years = 3 if "3" in lease else 1
        total_hours = years * 8760
        effective_hourly = (upfront / total_hours) + hourly if total_hours > 0 else hourly

        mode = f"RI {ri['offering_class']} {lease} {ri['purchase_option']}"
        results.append({
            "mode": mode,
            "hourly": round(effective_hourly, 6),
            "monthly": round(effective_hourly * 730, 2),
            "yearly": round(effective_hourly * 8760, 2),
            "upfront": upfront,
            "currency": currency,
        })

    # 按有效小时费率排序
    results.sort(key=lambda r: r["hourly"])
    return results


def format_comparison(rates: list[dict]) -> str:
    """格式化费率对比表"""
    if not rates:
        return "无可用定价数据"

    lines = []
    lines.append(f"{'计费模式':<45} {'小时费率':>12} {'月费用':>14} {'年费用':>14} {'预付':>14} {'vs按需':>8}")
    lines.append("-" * 110)

    od_hourly = next((r["hourly"] for r in rates if r["mode"] == "On-Demand"), None)

    for r in rates:
        upfront_str = f"{r.get('upfront', 0):,.2f}" if r.get("upfront", 0) > 0 else ("*" if r.get("upfront") == -1 else "-")
        savings = ""
        if od_hourly and od_hourly > 0 and r["mode"] != "On-Demand":
            pct = (1 - r["hourly"] / od_hourly) * 100
            savings = f"{pct:+.1f}%"

        lines.append(
            f"{r['mode']:<45} "
            f"{r['currency']} {r['hourly']:>9.4f} "
            f"{r['currency']} {r['monthly']:>10,.2f} "
            f"{r['currency']} {r['yearly']:>10,.2f} "
            f"{upfront_str:>14} "
            f"{savings:>8}"
        )

    # Add footnote if SP data present
    has_sp = any(r.get("upfront") == -1 for r in rates)
    if has_sp:
        lines.append("")
        lines.append("* SP 预付取决于承诺消费金额，非每实例固定预付。No Upfront=按月付，Partial/All Upfront=预付部分或全部承诺金额。")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="AWS 中国区价格查询工具")
    parser.add_argument("--service", "-s", help="服务代码 (如 AmazonEC2, AmazonRDS)")
    parser.add_argument("--region", "-r", default="cn-north-1",
                       choices=["cn-north-1", "cn-northwest-1", "cn-north-1-pkx-1"],
                       help="区域代码 (默认: cn-north-1)")
    parser.add_argument("--profile", default=None,
                       help="AWS CLI profile (默认: 环境变量 AWS_PROFILE 或 default)")
    parser.add_argument("--filters", "-f", nargs="*", default=[],
                       help="过滤器 key=value 格式 (如 instanceType=c6i.xlarge)")
    parser.add_argument("--list-services", action="store_true", help="列出所有可用服务")
    parser.add_argument("--compare", "-c", action="store_true", help="显示各计费模式费率对比（含 SP vs RI vs On-Demand）")
    parser.add_argument("--savings-plans", "--sp", action="store_true", help="同时查询 Savings Plans 价格")
    parser.add_argument("--verbose", "-v", action="store_true", help="显示详细信息")
    parser.add_argument("--max-results", "-n", type=int, default=5, help="最大返回条数 (默认: 5)")
    parser.add_argument("--json", action="store_true", help="以 JSON 格式输出")
    args = parser.parse_args()

    # 设置 profile
    global AWS_PROFILE
    if args.profile:
        AWS_PROFILE = args.profile

    # 列出服务
    if args.list_services:
        print("正在获取中国区可用服务列表...")
        services = list_services()
        if not services:
            print("错误: 无法获取服务列表", file=sys.stderr)
            sys.exit(1)
        print(f"\nAWS 中国区可用服务 (共 {len(services)} 个):\n")
        for svc in sorted(services, key=lambda s: s["ServiceCode"]):
            print(f"  {svc['ServiceCode']}")
        return

    if not args.service:
        parser.error("请指定 --service 或使用 --list-services")

    # 解析过滤器
    user_filters = {}
    for f in args.filters:
        if "=" in f:
            key, value = f.split("=", 1)
            user_filters[key] = value
        else:
            print(f"[WARN] 忽略无效过滤器: {f}", file=sys.stderr)

    # 区域映射：某些服务只在特定区域有价格
    query_region = args.region
    if args.service in REGION_OVERRIDE:
        override_region = REGION_OVERRIDE[args.service]
        if override_region != args.region:
            print(f"⚠️ {args.service} 统一按 {override_region} 计价（该服务仅在此区域有价格数据）", file=sys.stderr)
            query_region = override_region

    # 数据源 1: Query API
    print(f"正在查询 {args.service} @ {query_region} ...", file=sys.stderr)
    products = query_api(args.service, query_region, user_filters, max_results=args.max_results)

    # 数据源 2: 本地缓存降级
    if not products:
        print("[INFO] API 查询无结果，尝试本地缓存...", file=sys.stderr)
        products = query_cache(args.service, query_region, user_filters)

    if not products:
        print(f"\n未找到 {args.service} 在 {query_region} 的匹配价格数据。", file=sys.stderr)
        print("请检查:", file=sys.stderr)
        print(f"  1. 服务代码是否正确（使用 --list-services 查看）", file=sys.stderr)
        print(f"  2. 过滤器是否正确", file=sys.stderr)
        print(f"  3. 该服务是否在 {query_region} 可用", file=sys.stderr)
        print(f"\n建议运行以下命令更新本地缓存:", file=sys.stderr)
        print(f"  python3 {SCRIPT_DIR}/update_prices.py --region {query_region} --services {args.service}",
              file=sys.stderr)
        sys.exit(1)

    if not products:
        print("未找到匹配的价格数据。")
        sys.exit(1)

    # 查询 Savings Plans（如果请求或在对比模式下）
    sp_data = []
    if args.savings_plans or args.compare:
        instance_type = user_filters.get("instanceType", "")
        if args.service == "AmazonEC2" and instance_type:
            print(f"正在查询 Savings Plans ...", file=sys.stderr)
            sp_data = query_savings_plans(query_region, instance_type)
            if not sp_data:
                print("[INFO] 未找到 SP 数据，请先运行 update_prices.py 下载 SP 缓存", file=sys.stderr)

    # 输出结果
    if args.json:
        all_pricing = [extract_pricing(p) for p in products]
        output = {"products": all_pricing}
        if sp_data:
            output["savings_plans"] = sp_data
        print(json.dumps(output, ensure_ascii=False, indent=2))
    elif args.compare:
        for product in products[:1]:  # 对比模式只取第一个匹配
            pricing = extract_pricing(product)
            print(format_output(pricing, verbose=args.verbose))
            rates = calculate_effective_hourly(pricing)
            # 将 SP 费率加入对比
            if sp_data:
                rates.extend(_format_sp_for_comparison(sp_data))
                rates.sort(key=lambda r: r["hourly"])
            if rates:
                print("费率对比 (SP vs RI vs On-Demand):")
                print(format_comparison(rates))
    else:
        for i, product in enumerate(products):
            if i > 0:
                print("\n" + "=" * 60 + "\n")
            pricing = extract_pricing(product)
            on_demand_hr = float(pricing.get("on_demand", {}).get("price", 0)) if pricing.get("on_demand") else 0
            print(format_output(pricing, verbose=args.verbose))
        if sp_data:
            print("\n" + format_sp_output(sp_data, on_demand_hourly=on_demand_hr))


if __name__ == "__main__":
    main()
