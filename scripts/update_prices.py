#!/usr/bin/env python3
"""AWS 中国区价格数据更新工具

通过 Bulk API 下载价格文件并预处理为索引化小文件，实现快速本地查询。

用法:
  python3 update_prices.py --region cn-north-1
  python3 update_prices.py --region cn-north-1 --services AmazonEC2,AmazonRDS
  python3 update_prices.py --region cn-north-1 --list-versions
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

SCRIPT_DIR = Path(__file__).parent
DATA_DIR = SCRIPT_DIR.parent / "data"
CACHE_DIR = DATA_DIR / "cache"
INDEX_DIR = DATA_DIR / "index"
VERSION_FILE = DATA_DIR / "versions.json"

AWS_PROFILE = os.environ.get("AWS_PROFILE", "")
PRICING_REGION = "cn-northwest-1"


def run_aws_cli(args: list[str], timeout: int = 120) -> Optional[dict]:
    """执行 AWS CLI 命令并返回 JSON 结果"""
    cmd = ["aws"] + args + ["--region", PRICING_REGION, "--output", "json"]
    if AWS_PROFILE:
        cmd += ["--profile", AWS_PROFILE]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if result.returncode != 0:
            print(f"[ERROR] AWS CLI 错误: {result.stderr.strip()}", file=sys.stderr)
            return None
        return json.loads(result.stdout)
    except subprocess.TimeoutExpired:
        print(f"[ERROR] AWS CLI 超时 ({timeout}s)", file=sys.stderr)
        return None
    except (json.JSONDecodeError, FileNotFoundError) as e:
        print(f"[ERROR] AWS CLI 执行失败: {e}", file=sys.stderr)
        return None


def get_service_list() -> list[str]:
    """获取所有可用服务的 ServiceCode"""
    services = []
    next_token = None
    while True:
        args = ["pricing", "describe-services"]
        if next_token:
            args += ["--next-token", next_token]
        data = run_aws_cli(args, timeout=60)
        if not data:
            break
        for svc in data.get("Services", []):
            services.append(svc["ServiceCode"])
        next_token = data.get("NextToken")
        if not next_token:
            break
    return sorted(services)


def load_versions() -> dict:
    """加载本地版本记录"""
    if VERSION_FILE.exists():
        try:
            with open(VERSION_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {}


def save_versions(versions: dict):
    """保存版本记录"""
    VERSION_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(VERSION_FILE, "w") as f:
        json.dump(versions, f, indent=2)


def list_price_lists(service: str, region: str) -> list[dict]:
    """列出服务的 Price List 版本"""
    args = [
        "pricing", "list-price-lists",
        "--service-code", service,
        "--effective-date", "2025-01-01T00:00:00Z",
        "--currency-code", "CNY",
        "--region-code", region,
    ]
    data = run_aws_cli(args, timeout=30)
    if not data:
        return []
    return data.get("PriceLists", [])


def download_price_list(service: str, region: str, price_list_arn: str, file_format: str = "json") -> Optional[str]:
    """下载 Price List 文件"""
    # 获取下载 URL
    args = [
        "pricing", "get-price-list-file-url",
        "--price-list-arn", price_list_arn,
        "--file-format", file_format,
    ]
    data = run_aws_cli(args, timeout=30)
    if not data or "Url" not in data:
        return None

    url = data["Url"]

    # 下载文件
    cache_file = CACHE_DIR / f"{service}_{region}.json"
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    try:
        import requests
        print(f"  下载中: {service} ({region})...", file=sys.stderr)
        resp = requests.get(url, timeout=300, stream=True)
        resp.raise_for_status()

        with open(cache_file, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)

        size_mb = cache_file.stat().st_size / (1024 * 1024)
        print(f"  完成: {cache_file} ({size_mb:.1f} MB)", file=sys.stderr)
        return str(cache_file)
    except Exception as e:
        print(f"  [ERROR] 下载失败: {e}", file=sys.stderr)
        return None


def build_index(service: str, region: str, cache_file: str):
    """从缓存文件构建索引（按实例族拆分为小文件）"""
    index_base = INDEX_DIR / service / region
    index_base.mkdir(parents=True, exist_ok=True)

    print(f"  构建索引: {service} ({region})...", file=sys.stderr)

    try:
        with open(cache_file) as f:
            data = json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        print(f"  [ERROR] 读取缓存文件失败: {e}", file=sys.stderr)
        return

    # 提取产品和条款
    products_dict = data.get("products", {})
    terms = data.get("terms", {})

    # 按实例族分组
    families = {}
    for sku, product in products_dict.items():
        attrs = product.get("attributes", {})
        instance_type = attrs.get("instanceType", "")

        if instance_type:
            family = instance_type.split(".")[0]
        else:
            # 非实例类产品按 productFamily 分组
            family = attrs.get("productFamily", "other").replace(" ", "_").lower()

        if family not in families:
            families[family] = []

        # 合并产品信息和条款
        entry = {"product": product}

        # 关联 OnDemand 条款
        od_terms = terms.get("OnDemand", {}).get(sku, {})
        reserved_terms = terms.get("Reserved", {}).get(sku, {})

        entry["terms"] = {}
        if od_terms:
            entry["terms"]["OnDemand"] = od_terms
        if reserved_terms:
            entry["terms"]["Reserved"] = reserved_terms

        families[family].append(entry)

    # 写入索引文件
    total_files = 0
    for family, entries in families.items():
        index_file = index_base / f"{family}.json"
        with open(index_file, "w") as f:
            json.dump(entries, f, separators=(",", ":"))
        total_files += 1

    print(f"  索引完成: {total_files} 个文件", file=sys.stderr)


def update_service(service: str, region: str, versions: dict, force: bool = False) -> bool:
    """更新单个服务的价格数据"""
    version_key = f"{service}_{region}"

    # 获取远程版本
    price_lists = list_price_lists(service, region)
    if not price_lists:
        print(f"  [SKIP] {service}: 无 Price List 数据（可能该服务不支持 Bulk API）", file=sys.stderr)
        return False

    # 取最新版本
    latest = sorted(price_lists, key=lambda p: p.get("VersionId", ""), reverse=True)[0]
    remote_version = latest.get("VersionId", "")
    price_list_arn = latest.get("PriceListArn", "")

    local_version = versions.get(version_key, {}).get("version", "")

    if not force and remote_version == local_version:
        print(f"  [SKIP] {service}: 版本未变 ({remote_version})", file=sys.stderr)
        return False

    print(f"  [UPDATE] {service}: {local_version or '(无)'} → {remote_version}", file=sys.stderr)

    # 下载
    cache_file = download_price_list(service, region, price_list_arn)
    if not cache_file:
        return False

    # 构建索引
    build_index(service, region, cache_file)

    # 更新版本记录
    versions[version_key] = {
        "version": remote_version,
        "arn": price_list_arn,
        "cache_file": cache_file,
    }
    return True


def main():
    parser = argparse.ArgumentParser(description="AWS 中国区价格数据更新工具")
    parser.add_argument("--region", "-r", default="cn-north-1",
                       help="目标区域 (默认: cn-north-1)")
    parser.add_argument("--profile", default=None,
                       help="AWS CLI profile (默认: 不指定则用 AWS CLI 默认配置)")
    parser.add_argument("--services", "-s", help="指定服务（逗号分隔），不指定则更新所有")
    parser.add_argument("--force", "-f", action="store_true", help="强制更新（忽略版本检查）")
    parser.add_argument("--list-versions", action="store_true", help="列出本地缓存版本")
    parser.add_argument("--list-services", action="store_true", help="列出所有可用服务")
    parser.add_argument("--index-only", help="仅从已有缓存构建索引（指定缓存文件路径）")
    args = parser.parse_args()

    # 设置 profile
    global AWS_PROFILE
    if args.profile:
        AWS_PROFILE = args.profile

    # 确保目录存在
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    INDEX_DIR.mkdir(parents=True, exist_ok=True)

    versions = load_versions()

    if args.list_versions:
        if not versions:
            print("无本地缓存版本。")
            return
        print(f"本地缓存版本 ({len(versions)} 个):\n")
        for key, info in sorted(versions.items()):
            print(f"  {key}: {info.get('version', 'N/A')}")
        return

    if args.list_services:
        print("正在获取服务列表...", file=sys.stderr)
        services = get_service_list()
        print(f"\n可用服务 ({len(services)} 个):\n")
        for svc in services:
            print(f"  {svc}")
        return

    if args.index_only:
        # 从现有缓存构建索引
        service_region = Path(args.index_only).stem  # e.g., AmazonEC2_cn-north-1
        parts = service_region.rsplit("_", 1)
        if len(parts) == 2:
            build_index(parts[0], parts[1], args.index_only)
        else:
            print("错误: 缓存文件名格式应为 ServiceCode_region.json", file=sys.stderr)
        return

    # 确定要更新的服务（自动包含 Savings Plans）
    if args.services:
        service_codes = [s.strip() for s in args.services.split(",")]
        # 如果包含 EC2，自动加入 ComputeSavingsPlans
        if "AmazonEC2" in service_codes and "ComputeSavingsPlans" not in service_codes:
            service_codes.append("ComputeSavingsPlans")
    else:
        print("正在获取服务列表...", file=sys.stderr)
        service_codes = get_service_list()
        if not service_codes:
            print("错误: 无法获取服务列表", file=sys.stderr)
            sys.exit(1)

    print(f"准备更新 {len(service_codes)} 个服务 ({args.region}):\n", file=sys.stderr)

    updated = 0
    skipped = 0
    failed = 0

    for svc in service_codes:
        try:
            if update_service(svc, args.region, versions, force=args.force):
                updated += 1
                save_versions(versions)  # 每次成功后立即保存
            else:
                skipped += 1
        except Exception as e:
            print(f"  [ERROR] {svc}: {e}", file=sys.stderr)
            failed += 1

    print(f"\n更新完成: {updated} 更新, {skipped} 跳过, {failed} 失败", file=sys.stderr)


if __name__ == "__main__":
    main()
