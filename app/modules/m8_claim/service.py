import hashlib
import json
from datetime import date, datetime, timezone
from time import perf_counter

from app.config import RULE_VERSION
from app.manifest import input_identity
from app.modules.m1_intake.reader import open_payload
from app.modules.m7_publish.service import calculate
from app.modules.m8_claim.aging import invoice_dates
from app.modules.m8_claim.engine import allocate
from app.modules.m8_claim.vouchers import parse_vouchers


def claim_identity(raw, period, run_id):
    digest = hashlib.sha256(raw).hexdigest()
    parameters = {"规则": RULE_VERSION, "账期": period, "源批次": run_id, "凭证摘要": digest}
    encoded = json.dumps(parameters, ensure_ascii=False, sort_keys=True).encode()
    return hashlib.sha256(encoded).hexdigest()[:24], parameters


def build_claim(raw, period):
    """在内存里完成整批认领；任何一步抛错都不落库，旧版完整保留。"""
    started = perf_counter()
    data = open_payload(raw)
    source = calculate(raw, period)
    run_id = source["运行清单"]["批次"]
    shops = {row["柜台"] for row in source["柜台对账"]}
    period_label = source["运行清单"]["账期"]
    fallback = date.fromisoformat(f"{period_label}-01")
    bill_dates = invoice_dates(data.get("ledger", []), shops, fallback)
    vouchers, isolated = parse_vouchers(data.get("vouchers", []), shops)
    lines, receivables, leftovers = allocate(vouchers, source["柜台对账"], bill_dates)

    applied_by_shop = {}
    for line in lines:
        applied_by_shop[line["柜台"]] = applied_by_shop.get(line["柜台"], 0) + line["核销分"]
    shop_rows = []
    for shop, item in receivables.items():
        applied = applied_by_shop.get(shop, 0)
        shop_rows.append(
            {
                "柜台": shop,
                "账单日": item["账单日"].isoformat(),
                "应缴分": item["应缴分"],
                "月结实缴分": item["已实缴分"],
                "本次核销分": applied,
                "核销后欠缴分": item["待核销分"],
            }
        )
    claim_id, parameters = claim_identity(raw, period, run_id)
    quarantined = len(isolated) > 0
    result = {
        "认领清单": {
            "认领批次": claim_id,
            "批次": claim_id,
            **parameters,
            "生成时间": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "处理毫秒": round((perf_counter() - started) * 1000),
            "源批次": run_id,
            "可发布": not quarantined,
            "隔离凭证数": len(isolated),
        },
        "凭证核销": lines,
        "柜台认领": shop_rows,
        "待认领余款": leftovers,
        "凭证隔离": isolated,
        "原始凭证": [
            {
                "行号": v["行号"],
                "凭证号": v["凭证号"],
                "柜台": v["柜台"],
                "转账日": v["转账日"].isoformat(),
                "金额分": v["金额分"],
            }
            for v in vouchers
        ],
        "源账单": {row["柜台"]: row for row in source["柜台对账"]},
    }
    return claim_id, result


def claim_once(store, raw, period):
    """同一批凭证重跑复用既有认领，不产生重复核销。"""
    run_id, _ = input_identity(raw, period)
    claim_id, _ = claim_identity(raw, period, run_id)
    existing = store.get(claim_id)
    if existing is not None:
        return existing, True
    claim_id, result = build_claim(raw, period)
    saved, _ = store.save(claim_id, result)
    if saved.get("认领清单", {}).get("认领批次") != claim_id:  # 极端并发撞号：保留先到版本
        return store.get(claim_id), True
    return saved, False
