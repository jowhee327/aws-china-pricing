#!/usr/bin/env python3
"""AWS 中国区实例规格推荐工具

根据用户的 vCPU、内存需求和用途类型，推荐最合适的 EC2 实例并按性价比排序。

用法:
  python3 recommend_instance.py --vcpu 8 --memory 32 --region cn-north-1
  python3 recommend_instance.py --vcpu 4 --memory 16 --workload compute --region cn-north-1
  python3 recommend_instance.py --vcpu 16 --memory 64 --workload memory --region cn-northwest-1
"""

import argparse
import json
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))
from query_price import run_aws_cli, extract_pricing

# 用途类型到 API instanceFamily 值的映射
WORKLOAD_INSTANCE_FAMILIES = {
    "general": "General purpose",
    "compute": "Compute optimized",
    "memory": "Memory optimized",
    "storage": "Storage optimized",
    "gpu": "GPU instance",
}


def _is_graviton(instance_type: str) -> bool:
    """判断实例类型是否为 Graviton (ARM) 架构。
    Graviton 实例族在代号后带 'g'：m6g, c7g, r6gd, t4g 等。"""
    family = instance_type.split(".")[0] if "." in instance_type else instance_type
    return bool(re.match(r'^[a-z]+\d+g', family))


def query_matching_instances(region: str, vcpu_min: int, memory_min: float,
                             workload: str, max_results: int = 50,
                             exclude_families: list[str] | None = None,
                             arch: str = "all") -> list[dict]:
    """查询匹配条件的实例

    Args:
        exclude_families: 排除的实例族前缀列表，如 ["t2", "t3", "t3a", "t4g"]
        arch: 架构过滤 - "x86"(排除Graviton), "arm"(仅Graviton), "all"(不过滤)
    """
    results = []

    instance_family = WORKLOAD_INSTANCE_FAMILIES.get(workload, "General purpose")

    filters = [
        {"Type": "TERM_MATCH", "Field": "regionCode", "Value": region},
        {"Type": "TERM_MATCH", "Field": "operatingSystem", "Value": "Linux"},
        {"Type": "TERM_MATCH", "Field": "tenancy", "Value": "Shared"},
        {"Type": "TERM_MATCH", "Field": "capacitystatus", "Value": "Used"},
        {"Type": "TERM_MATCH", "Field": "preInstalledSw", "Value": "NA"},
        {"Type": "TERM_MATCH", "Field": "instanceFamily", "Value": instance_family},
    ]

    args = [
        "pricing", "get-products",
        "--service-code", "AmazonEC2",
        "--filters", json.dumps(filters),
        "--max-results", str(max_results),
    ]
    data = run_aws_cli(args, timeout=60)
    if not data:
        return results

    for price_str in data.get("PriceList", []):
        product = json.loads(price_str) if isinstance(price_str, str) else price_str
        attrs = product.get("product", {}).get("attributes", {})

        instance_type = attrs.get("instanceType", "")
        if not instance_type:
            continue

        # 排除指定实例族
        if exclude_families:
            if any(instance_type.startswith(f + ".") for f in exclude_families):
                continue

        # 架构过滤
        if arch == "x86" and _is_graviton(instance_type):
            continue
        if arch == "arm" and not _is_graviton(instance_type):
            continue

        # 解析 vCPU 和内存
        try:
            inst_vcpu = int(attrs.get("vcpu", "0"))
        except (ValueError, TypeError):
            continue
        mem_str = attrs.get("memory", "0").replace(",", "").replace(" GiB", "").replace(" GB", "").strip()
        try:
            inst_memory = float(mem_str)
        except (ValueError, TypeError):
            continue

        # 过滤: 至少满足用户要求
        if inst_vcpu < vcpu_min or inst_memory < memory_min:
            continue

        # 提取价格
        pricing = extract_pricing(product)
        od = pricing.get("on_demand")
        if not od or od["price"] == "N/A":
            continue

        try:
            hourly_price = float(od["price"])
        except (ValueError, TypeError):
            continue

        if hourly_price <= 0:
            continue

        # 性价比: vCPU + 内存资源 / 价格
        # 加权: 1 vCPU = 1, 1 GB mem = 0.25
        resource_score = inst_vcpu + inst_memory * 0.25
        cost_efficiency = resource_score / hourly_price

        results.append({
            "instance_type": instance_type,
            "vcpu": inst_vcpu,
            "memory_gib": inst_memory,
            "storage": attrs.get("storage", "EBS Only"),
            "network": attrs.get("networkPerformance", ""),
            "processor": attrs.get("physicalProcessor", ""),
            "generation": attrs.get("currentGeneration", ""),
            "hourly_price": hourly_price,
            "monthly_price": round(hourly_price * 720, 2),
            "currency": od.get("currency", "CNY"),
            "cost_efficiency": round(cost_efficiency, 2),
        })

    return results


def format_recommendations(results: list[dict], vcpu_min: int, memory_min: float) -> str:
    """格式化推荐结果"""
    if not results:
        return "未找到匹配的实例类型。请检查区域或放宽筛选条件。"

    lines = []
    lines.append(f"推荐实例（需求: >= {vcpu_min} vCPU, >= {memory_min} GiB 内存）")
    lines.append(f"按性价比从高到低排序（共 {len(results)} 个匹配）")
    lines.append("")
    lines.append(f"{'排名':>4} {'实例类型':<20} {'vCPU':>6} {'内存(GiB)':>10} {'小时价':>14} {'月费用':>14} "
                 f"{'性价比':>8} {'网络':<20} {'处理器':<25}")
    lines.append("=" * 130)

    for i, r in enumerate(results, 1):
        lines.append(
            f"{i:>4} {r['instance_type']:<20} {r['vcpu']:>6} {r['memory_gib']:>10.1f} "
            f"{r['currency']} {r['hourly_price']:>9.4f} "
            f"{r['currency']} {r['monthly_price']:>10,.2f} "
            f"{r['cost_efficiency']:>8.1f} "
            f"{r['network']:<20} {r['processor']:<25}"
        )

    lines.append("")
    lines.append("注: 性价比 = (vCPU + 内存GiB×0.25) / 小时费率，越高越好")
    lines.append("    月费用按 720 小时/月计算")

    # Top 3 推荐
    if len(results) >= 3:
        lines.append("")
        lines.append("Top 3 推荐:")
        for i, r in enumerate(results[:3], 1):
            lines.append(f"  {i}. {r['instance_type']} — {r['vcpu']} vCPU, {r['memory_gib']} GiB, "
                        f"{r['currency']} {r['hourly_price']:.4f}/hr ({r['currency']} {r['monthly_price']:,.2f}/月)")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="AWS 中国区实例规格推荐工具")
    parser.add_argument("--vcpu", type=int, required=True, help="最低 vCPU 数")
    parser.add_argument("--memory", type=float, required=True, help="最低内存 (GiB)")
    parser.add_argument("--region", "-r", default="cn-north-1",
                       choices=["cn-north-1", "cn-northwest-1"],
                       help="区域 (默认: cn-north-1)")
    parser.add_argument("--workload", "-w", default="general",
                       choices=["general", "compute", "memory", "storage", "gpu"],
                       help="用途类型 (默认: general)")
    parser.add_argument("--top", "-n", type=int, default=10, help="显示前 N 个推荐 (默认: 10)")
    parser.add_argument("--profile", default=None,
                       help="AWS CLI profile (默认: 环境变量 AWS_PROFILE 或 default)")
    parser.add_argument("--exclude-families",
                       default="t2,t3,t3a,t4g,c4,c5,c5d,c5n,c5a,c5ad,m4,m5,m5d,m5n,m5dn,m5a,m5ad,r4,r5,r5d,r5n,r5dn,r5a,r5ad,c6a,m6a,r6a,c7a,m7a,r7a,i3,i3en,d2,h1,p3,g3,g3s,x1,x1e,z1d,hpc7a",
                       help="排除的实例族前缀，逗号分隔 (默认排除t系列/旧代Intel/AMD，传空字符串可清除)")
    parser.add_argument("--arch", default="x86",
                       choices=["x86", "arm", "all"],
                       help="架构过滤: x86(排除Graviton,默认), arm(仅Graviton), all(不过滤)")
    parser.add_argument("--json", action="store_true", help="JSON 格式输出")
    args = parser.parse_args()
    # 设置 profile
    if args.profile:
        import query_price
        query_price.AWS_PROFILE = args.profile

    exclude_families = [f.strip() for f in args.exclude_families.split(",") if f.strip()]

    family_name = WORKLOAD_INSTANCE_FAMILIES.get(args.workload, "General purpose")
    print(f"正在查询 {args.workload} 类型实例（{family_name}）@ {args.region} ...",
          file=sys.stderr)

    results = query_matching_instances(args.region, args.vcpu, args.memory, args.workload,
                                       exclude_families=exclude_families, arch=args.arch)

    # 按性价比排序
    results.sort(key=lambda r: r["cost_efficiency"], reverse=True)
    results = results[:args.top]

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        print(format_recommendations(results, args.vcpu, args.memory))


if __name__ == "__main__":
    main()
