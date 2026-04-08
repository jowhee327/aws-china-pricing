#!/usr/bin/env python3
"""AWS 中国区智能工作负载导入工具

将自然语言服务描述（中英文）映射为标准 AWS ServiceCode，提取规格信息，
输出标准化 CSV 供 calculate_cost.py 使用。

支持任意格式的客户 Excel 文件：
- 多行表头自动合并
- 同一 sheet 中多个子表（标题行分隔）
- 智能列角色检测（类型/配置/数量等）
- Excel 公式、文本数量的容错处理

用法:
  python3 smart_import.py --input raw_workload.csv --output standardized.csv --region cn-north-1
  python3 smart_import.py --input customer_file.xlsx --output standardized.csv --region cn-north-1
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
    (["compute", "计算", "服务器", "虚拟机", "vm", "server", "ec2", "ecs", "云服务器", "通用型ecs"], "AmazonEC2", {}),
    # 应用层服务（实际跑在 EC2 上）
    (["gps脱密服务", "eureka", "nacos", "网关服务", "收容服务", "protal服务", "portal服务", "monitor服务"], "AmazonEC2", {"notes_hint": "应用层服务，运行在EC2上"}),
    (["container", "容器", "fargate"], "AmazonECS", {}),
    (["ecr", "容器镜像", "镜像仓库"], "AmazonECR", {}),
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
    (["efs", "弹性文件服务", "文件存储", "nfs", "nas", "file storage"], "AmazonEFS", {}),
    (["ebs", "弹性块存储", "ssd存储", "块存储", "云盘", "block storage"], "AmazonEC2", {"productFamily": "Storage"}),
    (["对象存储", "s3", "oss", "object storage"], "AmazonS3", {}),

    # ── 网络类 ──
    (["cdn", "加速", "cloudfront", "内容分发"], "AmazonCloudFront", {}),
    (["负载均衡", "lb", "alb", "nlb", "elb", "load balancer", "network load balancer"], "AWSELB", {}),
    (["专线相关费用", "专线", "direct connect", "合规专线"], "AWSDirectConnect", {}),
    (["vpn", "虚拟专用网络"], "AmazonVPC", {"notes_hint": "VPN"}),
    (["vpcendpoint", "vpc endpoint"], "AmazonVPC", {"notes_hint": "VPC Endpoint"}),
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

    # ── 无直接 AWS 对应 ──
    (["云堡垒机", "堡垒机"], "AWSSystemsManager", {"notes_hint": "非AWS标准服务，建议用 Systems Manager Session Manager"}),

    # ── 运维/管理 ──
    (["日志服务", "云监控", "cloudwatch", "监控", "告警"], "AmazonCloudWatch", {}),
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

# ── 智能列角色检测关键词 ──
COLUMN_ROLE_KEYWORDS = {
    "service_col": ["类型", "云产品分类", "云产品", "产品", "服务", "资源类型", "type", "service"],
    "spec_col": ["配置", "规格", "详情", "spec", "config", "configuration"],
    "quantity_col": ["数量", "个数", "台数", "最低个数", "count", "quantity", "num"],
    "unit_col": ["单位", "unit"],
    "desc_col": ["描述", "备注", "说明", "场景", "用途", "对应", "description"],
    "name_col": ["名称", "name"],
}

# 表头行关键词（用于 classify_row 判断是否为表头）
HEADER_KEYWORDS = {"类型", "配置", "数量", "个数", "台数", "最低个数", "规格", "名称",
                   "单位", "描述", "备注", "说明", "场景", "用途", "详情",
                   "type", "service", "spec", "config", "quantity", "count",
                   "name", "unit", "description", "云产品分类", "云产品", "产品",
                   "服务", "资源类型", "num", "configuration"}


# ── 智能行分类 & 列检测 ──────────────────────────────────────────────────

def _cell_str(cell) -> str:
    """将单元格值转为字符串，None → ''"""
    if cell is None:
        return ""
    return str(cell).strip()


def classify_row(row: tuple, has_col_map: bool = False) -> str:
    """对 Excel 行进行分类: 'empty' | 'title' | 'header' | 'data'

    当 has_col_map=True 时，表示已经有了列映射，优先当 data 处理，
    只有明确是 title 行时才重置表头。
    """
    cells = [_cell_str(c) for c in row]

    # empty: 全部空
    if all(c == "" or c.lower() == "none" for c in cells):
        return "empty"

    non_empty = [(i, c) for i, c in enumerate(cells) if c and c.lower() != "none"]

    # title: 只有第 1 列有值
    if len(non_empty) == 1 and non_empty[0][0] == 0:
        return "title"

    # header: 用子串匹配检测表头关键词
    hits = 0
    for c in cells:
        cl = c.lower() if c else ""
        if not cl or cl == "none":
            continue
        for kw in HEADER_KEYWORDS:
            if kw in cl:
                hits += 1
                break  # 每个单元格最多计 1 次
    if hits >= 2 and not has_col_map:
        return "header"

    # data: 其他非空行
    return "data"


def detect_columns(header_cells: list[str]) -> dict:
    """根据表头单元格内容检测各列的角色，返回 {role: col_index}"""
    col_map = {}
    for idx, cell in enumerate(header_cells):
        cell_lower = cell.lower().strip() if cell else ""
        if not cell_lower or cell_lower == "none":
            continue
        for role, keywords in COLUMN_ROLE_KEYWORDS.items():
            for kw in keywords:
                if kw in cell_lower:
                    # 优先匹配更精确的关键词（更长）
                    if role not in col_map or len(kw) > col_map[role][1]:
                        col_map[role] = (idx, len(kw))
                    break
    # 返回 {role: col_index}
    return {role: val[0] for role, val in col_map.items()}


def _parse_quantity(raw) -> tuple[str, str]:
    """解析数量字段，返回 (quantity_str, extra_notes)
    处理: 数字、None/空、Excel 公式、文本如 '100M'、'按量付费'等"""
    if raw is None:
        return "1", ""
    s = str(raw).strip()
    if not s or s.lower() == "none":
        return "1", ""
    # 纯数字（含小数）
    try:
        val = float(s)
        return str(int(val)) if val == int(val) else s, ""
    except (ValueError, OverflowError):
        pass
    # Excel 公式
    if s.startswith("=") or "SUM(" in s.upper():
        return "1", f"原始为Excel公式: {s}"
    # 特殊文本
    if "按量" in s or "按需" in s:
        return "1", f"原始数量: {s}"
    # 含数字的文本（如 "12c32g500G，按照年度计算"）
    m = re.match(r'^(\d+)', s)
    if m:
        return m.group(1), f"原始数量: {s}" if not s.isdigit() else ""
    # 无法解析
    return "1", f"原始数量: {s}"


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

def _load_excel_smart(input_path: str) -> list[dict]:
    """智能加载任意格式 Excel，返回标准化行列表（含 sheet_name/section）"""
    try:
        import openpyxl
    except ImportError:
        print("[ERROR] 需要 openpyxl 库来读取 Excel: pip install openpyxl", file=sys.stderr)
        sys.exit(1)

    wb = openpyxl.load_workbook(input_path, read_only=True, data_only=False)
    all_items = []

    for ws in wb:
        sheet_name = ws.title
        current_section = sheet_name
        col_map = None
        pending_header_rows = []  # 用于合并多行表头

        print(f"[INFO] 处理 sheet: {sheet_name}", file=sys.stderr)

        for row_tuple in ws.iter_rows(values_only=True):
            row_type = classify_row(row_tuple, has_col_map=col_map is not None)

            if row_type == "empty":
                continue

            if row_type == "title":
                current_section = _cell_str(row_tuple[0])
                col_map = None
                pending_header_rows = []
                continue

            if row_type == "header":
                pending_header_rows.append(row_tuple)
                # 合并多行表头：将非空单元格向上填充
                merged = list(_cell_str(c) for c in pending_header_rows[0])
                for extra_row in pending_header_rows[1:]:
                    for i, c in enumerate(extra_row):
                        cs = _cell_str(c)
                        if cs and cs.lower() != "none" and i < len(merged):
                            if merged[i]:
                                merged[i] = merged[i] + "/" + cs
                            else:
                                merged[i] = cs
                col_map = detect_columns(merged)
                if not col_map.get("service_col") and col_map:
                    # 没检测到 service 列，可能表头还没合并完
                    pass
                continue

            if row_type == "data":
                if not col_map:
                    # 没遇到表头行，尝试用第一列作为 service
                    cells = [_cell_str(c) for c in row_tuple]
                    if cells[0]:
                        item = {
                            "sheet_name": sheet_name,
                            "section": current_section,
                            "service": cells[0],
                            "spec": cells[1] if len(cells) > 1 else "",
                            "quantity": "1",
                            "quantity_notes": "",
                            "unit": "",
                            "name": "",
                            "desc": "",
                        }
                        all_items.append(item)
                    continue

                cells = [_cell_str(c) for c in row_tuple]

                # 用 col_map 提取数据
                svc_idx = col_map.get("service_col")
                service_text = cells[svc_idx] if svc_idx is not None and svc_idx < len(cells) else ""

                spec_idx = col_map.get("spec_col")
                spec_text = cells[spec_idx] if spec_idx is not None and spec_idx < len(cells) else ""

                qty_idx = col_map.get("quantity_col")
                raw_qty = row_tuple[qty_idx] if qty_idx is not None and qty_idx < len(row_tuple) else None
                quantity_str, qty_notes = _parse_quantity(raw_qty)

                unit_idx = col_map.get("unit_col")
                unit_text = cells[unit_idx] if unit_idx is not None and unit_idx < len(cells) else ""

                name_idx = col_map.get("name_col")
                name_text = cells[name_idx] if name_idx is not None and name_idx < len(cells) else ""

                desc_idx = col_map.get("desc_col")
                desc_text = cells[desc_idx] if desc_idx is not None and desc_idx < len(cells) else ""

                if not service_text and not name_text:
                    continue

                item = {
                    "sheet_name": sheet_name,
                    "section": current_section,
                    "service": service_text,
                    "spec": spec_text,
                    "quantity": quantity_str,
                    "quantity_notes": qty_notes,
                    "unit": unit_text,
                    "name": name_text,
                    "desc": desc_text,
                }
                all_items.append(item)

    wb.close()
    return all_items


def load_input(input_path: str, region: str) -> tuple[list[dict], bool]:
    """加载 CSV 或 Excel，返回 (标准化行列表, is_excel)
    Excel 走智能解析; CSV 走原来的 DictReader 路径。"""
    path = Path(input_path)
    if path.suffix in (".xlsx", ".xls"):
        return _load_excel_smart(input_path), True
    else:
        items = []
        with open(path, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames or []
            for row in reader:
                items.append({k.strip(): v.strip() for k, v in row.items()})
        return items, False


def process_excel_row(row: dict, region: str) -> dict:
    """处理智能 Excel 解析出的行，返回标准化的 calculate_cost.py 输入格式"""
    # 合并 service 和 name 列用于匹配
    svc_text = row.get("service", "")
    name_text = row.get("name", "")
    spec_text = row.get("spec", "")
    desc_text = row.get("desc", "")

    # 原始请求
    original_request = " ".join(filter(None, [svc_text, name_text, spec_text])).strip()

    # 匹配文本: 先 service 列 + name 列，再补 spec 和 desc
    primary_text = " ".join(filter(None, [svc_text, name_text]))
    all_text = " ".join(filter(None, [svc_text, name_text, spec_text, desc_text]))

    if not all_text.strip():
        return None

    # 优先用 primary_text（service + name 列）匹配
    matches = match_service(primary_text) if primary_text.strip() else []
    if not matches:
        matches = match_service(all_text)

    service_code = ""
    extra_fields = {}
    warning = ""

    if len(matches) == 0:
        service_code = svc_text.split()[0] if svc_text.strip() else "UNKNOWN"
        warning = f"[WARN] 无法识别服务: '{primary_text.strip()}'"
        print(warning, file=sys.stderr)
    elif len(matches) == 1:
        _, service_code, extra_fields, _ = matches[0]
    else:
        top = matches[0]
        second = matches[1]
        _, service_code, extra_fields, _ = top
        if top[3] <= second[3]:
            alternatives = ", ".join(f"{m[1]}(via '{m[0]}')" for m in matches[:3])
            warning = f"[WARN] 多个匹配: {alternatives}，已选择 {service_code}"
            print(warning, file=sys.stderr)

    # 提取规格
    spec_info = extract_spec(spec_text)
    for t in [svc_text, name_text, desc_text]:
        for k, v in extract_spec(t).items():
            if k not in spec_info:
                spec_info[k] = v

    # 检测引擎
    engine_info = detect_engine(all_text)

    # notes 收集
    notes_parts = []
    # notes_hint from extra_fields
    if extra_fields.get("notes_hint"):
        notes_parts.append(extra_fields.pop("notes_hint"))
    # 数量解析备注
    if row.get("quantity_notes"):
        notes_parts.append(row["quantity_notes"])
    # 描述信息
    if desc_text:
        notes_parts.append(desc_text)

    # 构建输出行
    result = {
        "sheet_name": row.get("sheet_name", ""),
        "section": row.get("section", ""),
        "service": service_code,
        "instance_type": "",
        "region": region,
        "quantity": row.get("quantity", "1") or "1",
        "usage_hours": "720",
        "os": "Linux" if service_code == "AmazonEC2" else "",
        "engine": engine_info.get("engine", ""),
        "storage_gb": "",
        "billing_mode": "on-demand",
        "notes": "",
        "original_request": original_request,
    }

    # 应用附加字段
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
        notes_parts.insert(0, f"recommend:{vcpu}c{mem}g")

    if warning:
        notes_parts.insert(0, warning)

    result["notes"] = " | ".join(filter(None, notes_parts))

    return result


def process_row(row: dict, region: str) -> dict:
    """处理 CSV 单行，返回标准化的 calculate_cost.py 输入格式"""
    norm = normalize_columns(row)

    # 保留客户原始需求描述
    orig_svc = norm.get("service", "")
    orig_spec = norm.get("spec", "")
    original_request = " ".join(filter(None, [orig_svc, orig_spec])).strip()

    # 如果已有标准 service 列且值是已知 ServiceCode，直接透传
    service_raw = orig_svc
    known_codes = {sc for _, sc, _ in SERVICE_RULES}
    if service_raw and service_raw in known_codes:
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

    matches = match_service(svc_text) if svc_text else []
    if not matches:
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
        top = matches[0]
        second = matches[1]
        _, service_code, extra_fields, _ = top
        if top[3] <= second[3]:
            alternatives = ", ".join(f"{m[1]}(via '{m[0]}')" for m in matches[:3])
            warning = f"[WARN] 多个匹配: {alternatives}，已选择 {service_code}"
            print(warning, file=sys.stderr)

    # 提取规格
    spec_text = norm.get("spec", "")
    spec_info = extract_spec(spec_text)
    for t in [norm.get("service", ""), norm.get("notes", "")]:
        for k, v in extract_spec(t).items():
            if k not in spec_info:
                spec_info[k] = v

    # 检测引擎
    engine_info = detect_engine(all_text)

    notes_hint = extra_fields.pop("notes_hint", "")

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

    for k, v in extra_fields.items():
        if not result.get(k):
            result[k] = v

    if "cacheEngine" in engine_info and service_code == "AmazonElastiCache":
        result["engine"] = engine_info["cacheEngine"]

    if spec_info.get("storage_gb") and not result["storage_gb"]:
        result["storage_gb"] = str(spec_info["storage_gb"])

    if spec_info.get("vcpu") and not result["instance_type"]:
        vcpu = spec_info["vcpu"]
        mem = spec_info.get("memory", 0)
        result["notes"] = f"recommend:{vcpu}c{mem}g" + (f" {result['notes']}" if result["notes"] else "")

    if notes_hint:
        result["notes"] = (notes_hint + " " + result["notes"]).strip() if result["notes"] else notes_hint
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
        "sheet_name", "section", "service", "instance_type", "region", "quantity",
        "usage_hours", "os", "engine", "storage_gb", "billing_mode", "notes",
        "original_request",
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
        "sheet_name", "section", "service", "instance_type", "region", "quantity",
        "usage_hours", "os", "engine", "storage_gb", "billing_mode", "notes",
        "original_request",
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
    parser.add_argument("--profile", default=None,
                       help="AWS CLI profile (默认: 环境变量 AWS_PROFILE 或 default)")
    parser.add_argument("--no-recommend", action="store_true", help="跳过实例推荐（加速处理）")
    args = parser.parse_args()

    # 加载输入
    rows, is_excel = load_input(args.input, args.region)
    if not rows:
        print("[ERROR] 输入文件为空", file=sys.stderr)
        sys.exit(1)

    print(f"[INFO] 读取 {len(rows)} 条记录", file=sys.stderr)

    # 逐行处理
    items = []
    for i, row in enumerate(rows, 1):
        if is_excel:
            result = process_excel_row(row, args.region)
        else:
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
                "sheet_name", "section", "service", "instance_type", "region",
                "quantity", "usage_hours", "os", "engine", "storage_gb",
                "billing_mode", "notes", "original_request",
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
