from datetime import date

from app.modules.m1_intake.amounts import cents
from app.modules.m1_intake.service import transaction_key
from app.reasons import issue

MISSING_SHOP_SENTINEL = {"", "-", "N/A", "NULL", "未知", None}


def parse_vouchers(records, known_shops):
    """逐张校验转账凭证；结构或金额有问题的凭证进隔离，不参与核销。

    注明的柜台必须存在于本月账单；未注明柜台（含空哨兵）允许留空，
    交由按账龄分配的规则处理。
    """
    accepted, isolated = [], []
    seen = set()
    for line, row in enumerate(records, 1):
        key = ""
        try:
            key = transaction_key(row, "id")
            try:
                posted = date.fromisoformat(row["day"])
            except (ValueError, TypeError):
                isolated.append(issue(line, "VOUCHER_DATE", key))
                continue
            note = row.get("shop")
            if note is None or (isinstance(note, str) and note.strip() in MISSING_SHOP_SENTINEL):
                shop = None
            else:
                shop = transaction_key(row, "shop")
                if shop not in known_shops:
                    isolated.append(issue(line, "VOUCHER_SHOP", key))
                    continue
        except (ValueError, KeyError, TypeError):
            isolated.append(issue(line, "VOUCHER_FIELD", key))
            continue
        try:
            amount = cents(row["amount"], row.get("unit", "元"))
        except ValueError:
            isolated.append(issue(line, "VOUCHER_AMOUNT", key))
            continue
        if key in seen:
            isolated.append(issue(line, "VOUCHER_DUPLICATE", key))
            continue
        seen.add(key)
        accepted.append(
            {"行号": line, "凭证号": key, "柜台": shop, "转账日": posted, "金额分": amount}
        )
    accepted.sort(key=lambda item: (item["转账日"], item["行号"]))
    return accepted, isolated
