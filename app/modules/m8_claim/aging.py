from datetime import date

from app.errors import InputError
from app.modules.m1_intake.service import transaction_key


def invoice_dates(records, shops, fallback):
    """读取各柜台月结单的账单日（账龄依据）。

    缺账龄账时以账期首日兜底；柜台重复或日期损坏直接拒绝整批，
    与合同、缴款账损坏的处理保持一致——旧版结果保留。
    """
    dates = {}
    for row in records:
        try:
            shop = transaction_key(row, "shop")
            if shop not in shops or shop in dates:
                raise ValueError("账龄账柜台无效或重复")
            dates[shop] = date.fromisoformat(row["bill_date"])
        except (ValueError, KeyError, TypeError) as exc:
            raise InputError("BAD_LEDGER", "账龄账字段有误或柜台重复") from exc
    return {shop: dates.get(shop, fallback) for shop in shops}
