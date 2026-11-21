from collections import OrderedDict

DIRECT = "凭证注明柜台，直记该柜台"
AGING = "未注明柜台，按账单日先清欠得最久的柜台"
REMAIN = "无可冲柜台，余款挂待认领，不挪补别柜"
FULL = "该柜台已缴清，不挪去补别柜欠费"


def outstanding(row):
    """欠缴 = 应缴 − 月结单已实缴；缺单按全额欠缴，已缴清为零。"""
    paid = row["实缴分"] or 0
    return max(row["应缴分"] - paid, 0)


def build_receivables(reconcile_rows, bill_dates):
    """以月结单欠缴为基数，每个柜台的待核销余额不能超过自身欠缴。"""
    receivables = OrderedDict()
    for row in sorted(reconcile_rows, key=lambda item: (bill_dates[item["柜台"]], item["柜台"])):
        receivables[row["柜台"]] = {
            "应缴分": row["应缴分"],
            "已实缴分": row["实缴分"] or 0,
            "账单日": bill_dates[row["柜台"]],
            "待核销分": outstanding(row),
        }
    return receivables


def aging_order(receivables):
    """欠得最久优先：账单日升序，同日按柜台号（前导零按字符串）裁决。"""
    return [
        shop
        for shop, item in sorted(receivables.items(), key=lambda kv: (kv[1]["账单日"], kv[0]))
        if item["待核销分"] > 0
    ]


def allocate(vouchers, reconcile_rows, bill_dates):
    receivables = build_receivables(reconcile_rows, bill_dates)
    lines, leftovers = [], []
    for voucher in vouchers:
        shop = voucher["柜台"]
        amount = voucher["金额分"]
        if shop is not None:
            target = receivables[shop]
            applied = min(amount, target["待核销分"])
            if applied:
                lines.append(
                    {
                        "凭证号": voucher["凭证号"],
                        "柜台": shop,
                        "核销分": applied,
                        "归款依据": DIRECT,
                    }
                )
                target["待核销分"] -= applied
            if amount > applied:
                leftovers.append(
                    {
                        "凭证号": voucher["凭证号"],
                        "柜台": shop,
                        "余款分": amount - applied,
                        "依据": FULL if applied == 0 else REMAIN,
                    }
                )
        else:
            remaining = amount
            for candidate in aging_order(receivables):
                if remaining == 0:
                    break
                applied = min(remaining, receivables[candidate]["待核销分"])
                lines.append(
                    {
                        "凭证号": voucher["凭证号"],
                        "柜台": candidate,
                        "核销分": applied,
                        "归款依据": AGING,
                    }
                )
                receivables[candidate]["待核销分"] -= applied
                remaining -= applied
            if remaining:
                leftovers.append(
                    {
                        "凭证号": voucher["凭证号"],
                        "柜台": None,
                        "余款分": remaining,
                        "依据": REMAIN,
                    }
                )
    return lines, receivables, leftovers
