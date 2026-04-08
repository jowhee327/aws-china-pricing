#!/usr/bin/env python3
"""AWS 中国区智能工作负载导入工具

将自然语言服务描述（中英文）映射为标准 AWS ServiceCode，提取规格信息，
输出标准化 CSV 供 calculate_cost.py 使用。

用法:
  python3 smart_import.py --input raw_workload.csv --output standardized.csv --region cn-north-1
  python3 smart_import.py --input raw_workload.csv --region cn-north-1 --calculate
"""

import argparse
import csv
import re
import subprocess
import sys
from pathlib import Path

# ── 映射表 ──────────────────────────────────────────────────────────────────
# 每条规则: (关键词列表, ServiceCode, 附加字段 dict)
# 关键词全部小写，匹配时也先 lower()
SERVICE_RULES: list[tuple[list[str], str, dict]] = [
    # ── 计算类 ──
    (["compute", "计算", "服务器", "虚拟机", "vm", "server", "ec2"], "AmazonEC2", {}),
    (["container", "容器", "ecs", "fargate"], "AmazonECS", {}),
    (["k8s", "kubernetes", "eks"], "AmazonEKS", {}),
    (["serverless", "无服务器", "lambda", "函数计算", "function"], "AWSLambda", {}),

    # ── 数据库类 ──
    (["documentdb", "文档数据库", "mongodb"], "AmazonDocDB", {}),
    (["neptune", "图数据库", "graph"], "AmazonNeptune", {}),
    (["timestream", "时序数据库", "timeseries"], "AmazonTimestream", {}),
    (["dynamodb", "nosql", "键值数据库", "key-value"], "AmazonDynamoDB", {}),
    (["redshift", "数仓", "数据仓库", "data warehouse"], "AmazonRedshift", {}),
    (["memorydb", "内存数据库"], "AmazonMemoryDB", {}),
    # RDS 按引擎区分（具体引擎优先，通用关键词兜底默认 MySQL）
    (["aurora mysql", "aurora-mysql"], "AmazonRDS", {"engine": "Aurora MySQL"}),
    (["aurora postgresql", "aurora-postgresql", "aurora postgres"], "AmazonRDS", {"engine": "Aurora PostgreSQL"}),
    (["aurora"], "AmazonRDS", {"engine": "Aurora MySQL"}),
    (["mysql", "mysql数据库"], "AmazonRDS", {"engine": "MySQL"}),
    (["postgresql", "postgres", "pg数据库"], "AmazonRDS", {"engine": "PostgreSQL"}),
    (["mariadb"], "AmazonRDS", {"engine": "MariaDB"}),
    (["oracle", "oracle数据库"], "AmazonRDS", {"engine": "Oracle"}),
    (["sql server", "sqlserver", "mssql"], "AmazonRDS", {"engine": "SQL Server"}),
    (["rds", "database", "数据库", "关系数据库"], "AmazonRDS", {"engine": "MySQL"}),

    # ── 缓存类 ──
    (["dax", "dynamodb加速"], "AmazonDAX", {}),
    # ElastiCache 按引擎区分（具体引擎优先，通用关键词兜底默认 Redis）
    (["valkey"], "AmazonElastiCache", {"engine": "Valkey"}),
    (["memcached"], "AmazonElastiCache", {"engine": "Memcached"}),
    (["redis"], "AmazonElastiCache", {"engine": "Redis"}),
    (["缓存", "elasticache", "cache"], "AmazonElastiCache", {"engine": "Redis"}),

    # ── 存储类 ──
    (["glacier", "归档", "冷存储", "archive"], "AmazonGlacier", {}),
    (["fsx", "windows文件", "lustre"], "AmazonFSx", {}),
    (["efs", "文件存储", "nfs", "file storage"], "AmazonEFS", {}),
    (["ebs", "块存储", "云盘", "block storage"], "AmazonEC2", {"productFamily": "Storage"}),
    (["对象存储", "s3", "oss", "object storage"], "AmazonS3", {}),

    # ── 网络类 ──
    (["cdn", "加速", "cloudfront", "内容分发"], "AmazonCloudFront", {}),
    (["负载均衡", "lb", "alb", "nlb", "elb", "load balancer"], "AWSELB", {}),
    (["vpn", "专线", "direct connect", "直连"], "AWSDirectConnect", {}),
    (["dns", "route53", "域名"], "AMAZONROUTE53REGIONALCHINA", {}),
    (["waf", "web防火墙"], "awswaf", {}),
    (["network firewall", "网络防火墙"], "AWSNetworkFirewall", {}),
    (["vpc"], "AmazonVPC", {}),

    # ── 消息/流式 ──
    (["sqs", "消息队列", "队列", "message queue"], "AWSQueueService", {}),
    (["sns", "通知", "推送", "notification"], "AmazonSNS", {}),
    (["kafka", "msk", "消息流"], "AmazonMSK", {}),
    # MQ 按引擎区分（默认 RabbitMQ）
    (["rabbitmq"], "AmazonMQ", {"engine": "RabbitMQ"}),
    (["activemq"], "AmazonMQ", {"engine": "ActiveMQ"}),
    (["mq", "消息代理"], "AmazonMQ", {"engine": "RabbitMQ"}),
    (["eventbridge", "事件"], "AWSEvents", {}),
    (["kinesis firehose", "数据投递"], "AmazonKinesisFirehose", {}),
    (["kinesis analytics", "流分析"], "AmazonKinesisAnalytics", {}),
    (["kinesis video", "视频流"], "AmazonKinesisVideo", {}),
    (["kinesis", "实时流", "streaming"], "AmazonKinesis", {}),

    # ── 大数据/分析 ──
    (["emr", "spark", "mapreduce", "大数据"], "ElasticMapReduce", {}),
    (["athena", "sql查询", "交互式查询"], "AmazonAthena", {}),
    (["glue", "etl", "数据集成"], "AWSGlue", {}),
    (["quicksight", "bi", "报表", "可视化"], "AmazonQuickSight", {}),

    # ── AI/ML ──
    (["sagemaker", "机器学习", "ml", "ai"], "AmazonSageMaker", {}),
    (["polly", "语音合成", "tts"], "AmazonPolly", {}),
    (["transcribe", "语音转文字", "str", "asr"], "transcribe", {}),
    (["personalize", "推荐"], "AmazonPersonalize", {}),

    # ── 安全类 ──
    (["kms", "密钥管理", "加密"], "awskms", {}),
    (["acm", "证书", "ssl", "https"], "ACM", {}),
    (["guardduty", "安全审计", "威胁检测"], "AmazonGuardDuty", {}),
    (["inspector", "漏洞扫描"], "AmazonInspectorV2", {}),
    (["secrets manager", "密钥存储", "密码管理"], "AWSSecretsManager", {}),
    (["security hub", "安全中心"], "AWSSecurityHub", {}),
    (["firewall manager", "防火墙管理"], "AWSFMS", {}),
    (["iam access analyzer"], "AWSIAMAccessAnalyzer", {}),

    # ── 运维/管理 ──
    (["cloudwatch", "监控", "告警"], "AmazonCloudWatch", {}),
    (["cloudtrail", "日志审计"], "AWSCloudTrail", {}),
    (["backup", "备份"], "AWSBackup", {}),
    (["workspaces", "桌面", "云桌面", "vdi"], "AmazonWorkSpaces", {}),
    (["dms", "数据迁移", "数据库迁移"], "AWSDatabaseMigrationSvc", {}),
    (["datasync", "数据同步"], "AWSDataSync", {}),
    (["snowball", "数据搬迁"], "IngestionServiceSnowball", {}),
    (["iot analytics"], "AWSIoTAnalytics", {}),
    (["iot events"], "AWSIoTEvents", {}),
    (["iot sitewise"], "AWSIoTSiteWise", {}),
    (["iot", "物联网"], "AWSIoT", {}),
    (["step functions", "工作流", "状态机"], "AmazonStates", {}),
    (["systems manager", "运维管理"], "AWSSystemsManager", {}),
    (["config", "配置审计"], "AWSConfig", {}),
    (["service catalog", "服务目录"], "AWSServiceCatalog", {}),
    (["cloudformation", "iac", "基础设施即代码"], "AWSCloudFormation", {}),
    (["codebuild", "构建"], "CodeBuild", {}),
    (["codecommit", "代码仓库"], "AWSCodeCommit", {}),
    (["codedeploy", "部署"], "AWSCodeDeploy", {}),
    (["codepipeline", "流水线", "ci/cd"], "AWSCodePipeline", {}),
    (["x-ray", "链路追踪", "tracing"], "AWSXRay", {}),
    (["appsync", "graphql"], "AWSAppSync", {}),
    (["api gateway", "api网关"], "AmazonApiGateway", {}),
    (["transfer family", "sftp", "ftp"], "AWSTransfer", {}),
    (["greengrass", "边缘计算"], "AWSGreengrass", {}),
    (["storage gateway", "混合存储"], "AWSStorageGateway", {}),
    (["mediaconvert", "媒体转码"], "AWSElementalMediaConvert", {}),
    (["gamelift", "游戏服务器"], "AmazonGameLift", {}),
    (["cost explorer", "成本分析"], "AWSCostExplorer", {}),
    (["budgets", "预算"], "AWSBudgets", {}),
    (["compute optimizer", "优化建议"], "AWSComputeOptimizer", {}),
    (["cloudmap", "服务发现"], "AWSCloudMap", {}),
    (["verified permissions", "授权"], "AmazonVerifiedPermissions", {}),
    (["mwaa", "airflow", "工作流调度"], "AmazonMWAA", {}),
    (["opensearch", "elasticsearch", "搜索", "es"], "AmazonES", {}),
    (["swf", "简单工作流"], "AmazonSWF", {}),
]

# 引擎提示：从输入文本中推断 engine / cacheEngine
ENGINE_HINTS = {
    "aurora mysql": ("engine", "Aurora MySQL"),
    "aurora postgresql": ("engine", "Aurora PostgreSQL"),
    "aurora postgres": ("engine", "Aurora PostgreSQL"),
    "aurora": ("engine", "Aurora MySQL"),
    "mysql": ("engine", "MySQL"),
    "postgresql": ("engine", "PostgreSQL"),
    "postgres": ("engine", "PostgreSQL"),
    "mariadb": ("engine", "MariaDB"),
    "oracle": ("engine", "Oracle"),
    "sql server": ("engine", "SQL Server"),
    "redis": ("cacheEngine", "Redis"),
    "memcached": ("cacheEngine", "Memcached"),
    "valkey": ("cacheEngine", "Valkey"),
}

# ── 输入列名映射（宽松列名 → 标准列名）──
COLUMN_ALIASES = {
    "类型": "service", "服务": "service", "service": "service", "服务类型": "service",
    "规格": "spec", "配置": "spec", "spec": "spec", "实例": "spec", "instance": "spec",
    "instance_type": "instance_type",
    "数量": "quantity", "qty": "quantity", "quantity": "quantity", "台数": "quantity",
    "备注": "notes", "note": "notes", "notes": "notes", "说明": "notes", "描述": "notes",
    "region": "region", "区域": "region",
    "os": "os", "操作系统": "os",
    "engine": "engine", "引擎": "engine",
    "storage_gb": "storage_gb", "存储": "storage_gb",
    "billing_mode": "billing_mode", "计费模式": "billing_mode",
    "usage_hours": "usage_hours", "使用时长": "usage_hours",
}


# ── 核心匹配逻辑 ──────────────────────────────────────────────────────────

def match_service(text: str) -> list[tuple[str, str, dict, int]]:
    """对输入文本进行服务匹配，返回 [(matched_keyword, service_code, extra_fields, score)] 按 score 降序"""
    text_lower = text.lower()
    matches = []

    for keywords, service_code, extra in SERVICE_RULES:
        best_kw = None
        best_score = 0
        for kw in keywords:
            kw_lower = kw.lower()
            if kw_lower in text_lower:
                # 越长的关键词得分越高（精确度高）
                score = len(kw_lower) * 10
                # 完全匹配加分
                if text_lower.strip() == kw_lower:
                    score += 100
                if score > best_score:
                    best_score = score
                    best_kw = kw
        if best_kw:
            matches.append((best_kw, service_code, extra, best_score))

    # 去重同一 service_code，保留最高分
    seen = {}
    for kw, sc, extra, score in matches:
        if sc not in seen or score > seen[sc][3]:
            seen[sc] = (kw, sc, extra, score)

    result = sorted(seen.values(), key=lambda x: -x[3])
    return result


def extract_spec(text: str) -> dict:
    """从规格描述中提取 vCPU、内存、存储等信息"""
    info = {}
    if not text:
        return info

    # 匹配 "8C16G", "8核16G", "8c16g", "8 vCPU 16 GiB" 等
    m = re.search(r'(\d+)\s*[cC核vV]\s*[pP]?[uU]?\s*(\d+)\s*[gG]', text)
    if m:
        info["vcpu"] = int(m.group(1))
        info["memory"] = int(m.group(2))

    # 匹配 "4G内存", "4G" (独立的内存描述，无 CPU 信息时)
    if "memory" not in info:
        m = re.search(r'(\d+)\s*[gG][iI]?[bB]?\s*(?:内存|memory)?', text)
        if m:
            info["memory"] = int(m.group(1))

    # 匹配存储容量 "1TB", "500GB", "500G存储"
    m = re.search(r'(\d+)\s*[tT][bB]', text)
    if m:
        info["storage_gb"] = int(m.group(1)) * 1024
    else:
        m = re.search(r'(\d+)\s*[gG][bB]?\s*(?:存储|storage|磁盘|disk)', text)
        if m:
            info["storage_gb"] = int(m.group(1))

    return info


def detect_engine(text: str) -> dict:
    """从文本中检测数据库/缓存引擎"""
    text_lower = text.lower()
    for hint, (field, value) in ENGINE_HINTS.items():
        if hint in text_lower:
            return {field: value}
    return {}


def normalize_columns(row: dict) -> dict:
    """将宽松列名映射到标准列名"""
    result = {}
    for key, value in row.items():
        normalized = COLUMN_ALIASES.get(key.strip().lower(), key.strip().lower())
        result[normalized] = value
    return result


def is_standard_format(headers: list[str]) -> bool:
    """检查是否已经是标准格式（含 service 列且值看起来像 ServiceCode）"""
    return "service" in [h.lower() for h in headers]


# ── 主处理逻辑 ──────────────────────────────────────────────────────────────

def load_input(input_path: str) -> tuple[list[dict], list[str]]:
    """加载 CSV 或 Excel，返回 (行列表, 原始列名)"""
    path = Path(input_path)
    if path.suffix in (".xlsx", ".xls"):
        try:
            import openpyxl
            wb = openpyxl.load_workbook(path, read_only=True)
            ws = wb.active
            rows = list(ws.iter_rows(values_only=True))
            if not rows:
                return [], []
            headers = [str(h).strip() if h else "" for h in rows[0]]
            items = []
            for row in rows[1:]:
                item = {}
                for i, h in enumerate(headers):
                    item[h] = str(row[i]).strip() if i < len(row) and row[i] is not None else ""
                items.append(item)
            wb.close()
            return items, headers
        except ImportError:
            print("[ERROR] 需要 openpyxl 库来读取 Excel: pip install openpyxl", file=sys.stderr)
            sys.exit(1)
    else:
        items = []
        with open(path, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames or []
            for row in reader:
                items.append({k.strip(): v.strip() for k, v in row.items()})
        return items, headers


def process_row(row: dict, region: str) -> dict:
    """处理单行，返回标准化的 calculate_cost.py 输入格式"""
    norm = normalize_columns(row)

    # 保留客户原始需求描述
    orig_svc = norm.get("service", "")
    orig_spec = norm.get("spec", "")
    original_request = " ".join(filter(None, [orig_svc, orig_spec])).strip()

    # 如果已有标准 service 列且值是已知 ServiceCode，直接透传
    service_raw = orig_svc
    known_codes = {sc for _, sc, _ in SERVICE_RULES}
    if service_raw and service_raw in known_codes:
        # 已经是标准格式，补充默认值
        result = {
            "service": service_raw,
            "instance_type": norm.get("instance_type", norm.get("spec", "")),
            "region": norm.get("region", region),
            "quantity": norm.get("quantity", "1") or "1",
            "usage_hours": norm.get("usage_hours", "720"),
            "os": norm.get("os", ""),
            "engine": norm.get("engine", ""),
            "storage_gb": norm.get("storage_gb", ""),
            "billing_mode": norm.get("billing_mode", "on-demand"),
            "notes": norm.get("notes", ""),
            "original_request": original_request,
        }
        return result

    # 先用 service 列匹配（权重最高），再用其他列补充
    svc_text = norm.get("service", "")
    extra_text = " ".join(filter(None, [norm.get("spec", ""), norm.get("notes", "")]))
    all_text = " ".join(filter(None, [svc_text, extra_text]))

    if not all_text.strip():
        return None

    # 优先用 service 列匹配
    matches = match_service(svc_text) if svc_text else []
    if not matches:
        # 回退到全文匹配
        matches = match_service(all_text)
    service_code = ""
    extra_fields = {}
    warning = ""

    if len(matches) == 0:
        service_code = norm.get("service", all_text.split()[0] if all_text.strip() else "UNKNOWN")
        warning = f"[WARN] 无法识别服务: '{all_text.strip()}'"
        print(warning, file=sys.stderr)
    elif len(matches) == 1:
        _, service_code, extra_fields, _ = matches[0]
    else:
        # 多个匹配：取得分最高的
        top = matches[0]
        second = matches[1]
        if top[3] > second[3]:
            # 最高分明显胜出
            _, service_code, extra_fields, _ = top
        else:
            # 得分接近，取最高的但警告
            _, service_code, extra_fields, _ = top
            alternatives = ", ".join(f"{m[1]}(via '{m[0]}')" for m in matches[:3])
            warning = f"[WARN] 多个匹配: {alternatives}，已选择 {service_code}"
            print(warning, file=sys.stderr)

    # 提取规格
    spec_text = norm.get("spec", "")
    spec_info = extract_spec(spec_text)
    # 也从服务描述和备注中提取
    for t in [norm.get("service", ""), norm.get("notes", "")]:
        for k, v in extract_spec(t).items():
            if k not in spec_info:
                spec_info[k] = v

    # 检测引擎
    engine_info = detect_engine(all_text)

    # 构建输出行
    result = {
        "service": service_code,
        "instance_type": norm.get("instance_type", ""),
        "region": norm.get("region", region),
        "quantity": norm.get("quantity", "1") or "1",
        "usage_hours": norm.get("usage_hours", "720"),
        "os": norm.get("os", "Linux") if service_code == "AmazonEC2" else norm.get("os", ""),
        "engine": norm.get("engine", "") or engine_info.get("engine", ""),
        "storage_gb": norm.get("storage_gb", ""),
        "billing_mode": norm.get("billing_mode", "on-demand"),
        "notes": norm.get("notes", ""),
        "original_request": original_request,
    }

    # 应用附加字段（仅在未显式设置时作为默认值）
    for k, v in extra_fields.items():
        if not result.get(k):
            result[k] = v

    # 应用缓存引擎
    if "cacheEngine" in engine_info and service_code == "AmazonElastiCache":
        result["engine"] = engine_info["cacheEngine"]

    # 存储容量
    if spec_info.get("storage_gb") and not result["storage_gb"]:
        result["storage_gb"] = str(spec_info["storage_gb"])

    # 如果有 vCPU/memory 但没有 instance_type，记录到 notes 供后续推荐
    if spec_info.get("vcpu") and not result["instance_type"]:
        vcpu = spec_info["vcpu"]
        mem = spec_info.get("memory", 0)
        result["notes"] = f"recommend:{vcpu}c{mem}g" + (f" {result['notes']}" if result["notes"] else "")

    if warning:
        result["notes"] = (warning + " " + result["notes"]).strip()

    return result


def resolve_instance_recommendations(items: list[dict], region: str) -> list[dict]:
    """对含有 recommend:XcYg 的条目，调用 recommend_instance 逻辑推荐实例"""
    script_dir = Path(__file__).parent

    for item in items:
        notes = item.get("notes", "")
        m = re.search(r'recommend:(\d+)c(\d+)g', notes)
        if not m:
            continue
        vcpu = m.group(1)
        memory = m.group(2)
        service = item["service"]

        # 只对 EC2 类做实例推荐
        if service != "AmazonEC2":
            item["notes"] = notes.replace(m.group(0), f"需要{vcpu}vCPU/{memory}GiB").strip()
            continue

        # 调用 recommend_instance.py
        try:
            cmd = [
                sys.executable, str(script_dir / "recommend_instance.py"),
                "--vcpu", vcpu, "--memory", memory,
                "--region", region, "--json",
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            if result.returncode == 0:
                import json
                recs = json.loads(result.stdout)
                if recs and len(recs) > 0:
                    top = recs[0]
                    item["instance_type"] = top.get("instance_type", "")
                    item["notes"] = notes.replace(
                        m.group(0),
                        f"推荐实例:{item['instance_type']}({vcpu}vCPU/{memory}GiB)"
                    ).strip()
                    continue
        except Exception as e:
            print(f"[WARN] 实例推荐失败: {e}", file=sys.stderr)

        # 推荐失败，保留提示
        item["notes"] = notes.replace(m.group(0), f"需手动选择实例({vcpu}vCPU/{memory}GiB)").strip()

    return items


def save_csv(items: list[dict], output_path: str):
    """保存标准化 CSV"""
    if not items:
        print("[WARN] 没有数据可输出", file=sys.stderr)
        return

    fieldnames = [
        "service", "instance_type", "region", "quantity", "usage_hours",
        "os", "engine", "storage_gb", "billing_mode", "notes", "original_request",
    ]
    # 添加可能存在的额外字段
    for item in items:
        for k in item:
            if k not in fieldnames:
                fieldnames.append(k)

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(items)

    print(f"[OK] 已输出标准化 CSV: {output_path} ({len(items)} 条)", file=sys.stderr)


def print_csv(items: list[dict]):
    """输出标准化 CSV 到 stdout"""
    if not items:
        return

    fieldnames = [
        "service", "instance_type", "region", "quantity", "usage_hours",
        "os", "engine", "storage_gb", "billing_mode", "notes", "original_request",
    ]

    writer = csv.DictWriter(sys.stdout, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(items)


def main():
    parser = argparse.ArgumentParser(description="AWS 中国区智能工作负载导入 - 自然语言到 ServiceCode 映射")
    parser.add_argument("--input", "-i", required=True, help="输入 CSV/Excel 文件路径")
    parser.add_argument("--output", "-o", help="输出标准化 CSV 路径（不指定则输出到 stdout）")
    parser.add_argument("--region", "-r", default="cn-north-1", help="默认区域 (默认: cn-north-1)")
    parser.add_argument("--calculate", action="store_true", help="预处理后直接调用 calculate_cost.py 计算")
    parser.add_argument("--no-recommend", action="store_true", help="跳过实例推荐（加速处理）")
    args = parser.parse_args()

    # 加载输入
    rows, headers = load_input(args.input)
    if not rows:
        print("[ERROR] 输入文件为空", file=sys.stderr)
        sys.exit(1)

    print(f"[INFO] 读取 {len(rows)} 条记录", file=sys.stderr)

    # 逐行处理
    items = []
    for i, row in enumerate(rows, 1):
        result = process_row(row, args.region)
        if result:
            items.append(result)
        else:
            print(f"[WARN] 第 {i} 行为空，已跳过", file=sys.stderr)

    if not items:
        print("[ERROR] 没有有效数据", file=sys.stderr)
        sys.exit(1)

    # 实例推荐
    if not args.no_recommend:
        items = resolve_instance_recommendations(items, args.region)

    # 输出映射摘要
    print("\n[映射结果]", file=sys.stderr)
    for i, item in enumerate(items, 1):
        svc = item["service"]
        inst = item.get("instance_type", "")
        qty = item.get("quantity", "1")
        extra = []
        if item.get("engine"):
            extra.append(f"engine={item['engine']}")
        if item.get("storage_gb"):
            extra.append(f"storage={item['storage_gb']}GB")
        if inst:
            extra.append(f"instance={inst}")
        extra_str = f" ({', '.join(extra)})" if extra else ""
        print(f"  {i}. {svc} x{qty}{extra_str}", file=sys.stderr)
    print("", file=sys.stderr)

    # 输出
    if args.calculate:
        # 管道模式：先保存临时文件，再调用 calculate_cost.py
        import tempfile
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8") as tmp:
            tmp_path = tmp.name
            fieldnames = [
                "service", "instance_type", "region", "quantity", "usage_hours",
                "os", "engine", "storage_gb", "billing_mode", "notes", "original_request",
            ]
            writer = csv.DictWriter(tmp, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(items)

        script_dir = Path(__file__).parent
        calc_script = script_dir / "calculate_cost.py"
        cmd = [sys.executable, str(calc_script), "--input", tmp_path, "--region", args.region]
        print(f"[INFO] 调用: {' '.join(cmd)}", file=sys.stderr)
        result = subprocess.run(cmd)

        # 清理临时文件
        Path(tmp_path).unlink(missing_ok=True)
        sys.exit(result.returncode)

    elif args.output:
        save_csv(items, args.output)
    else:
        print_csv(items)


if __name__ == "__main__":
    main()
