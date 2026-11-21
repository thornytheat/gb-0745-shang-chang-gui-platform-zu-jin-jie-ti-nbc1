import io
from datetime import date
from pathlib import Path

from app.errors import InputError
from app.modules.m1_intake.reader import open_payload
from app.modules.m8_claim.engine import AGING, DIRECT, FULL, allocate
from app.modules.m8_claim.service import build_claim, claim_once
from app.modules.m8_claim.vouchers import parse_vouchers
from app.store import RunStore

RECONCILE = [
    {"柜台": "001", "应缴分": 16000, "实缴分": 15500},
    {"柜台": "002", "应缴分": 13000, "实缴分": 0},
    {"柜台": "003", "应缴分": 27000, "实缴分": None},
    {"柜台": "004", "应缴分": 30000, "实缴分": 30000},
]
DATES = {
    "001": date(2026, 10, 31),
    "002": date(2026, 11, 5),
    "003": date(2026, 11, 10),
    "004": date(2026, 11, 15),
}
SHOPS = set(DATES)
SAMPLE = Path(__file__).resolve().parents[1] / "sample_data" / "vouchers.json"


def sample_bytes():
    return SAMPLE.read_bytes()


def test_unmarked_voucher_pays_oldest_first():
    vouchers, _ = parse_vouchers([{"id": "T1", "day": "2026-11-21", "amount": "300"}], SHOPS)
    lines, receivables, leftovers = allocate(vouchers, RECONCILE, DATES)
    assert [(r["柜台"], r["核销分"]) for r in lines] == [("001", 500), ("002", 13000), ("003", 16500)]
    assert all(r["归款依据"] == AGING for r in lines)
    assert receivables["003"]["待核销分"] == 10500
    assert leftovers == []


def test_named_voucher_only_hits_named_shop():
    vouchers, _ = parse_vouchers(
        [{"id": "T2", "day": "2026-11-22", "shop": "002", "amount": "20"}], SHOPS
    )
    lines, _, leftovers = allocate(vouchers, RECONCILE, DATES)
    assert [(r["柜台"], r["核销分"], r["归款依据"]) for r in lines] == [("002", 2000, DIRECT)]
    assert leftovers == []


def test_named_cleared_shop_keeps_money_and_does_not_spill():
    vouchers, _ = parse_vouchers(
        [{"id": "T3", "day": "2026-11-23", "shop": "004", "amount": "50"}], SHOPS
    )
    lines, _, leftovers = allocate(vouchers, RECONCILE, DATES)
    assert lines == []
    assert leftovers == [{"凭证号": "T3", "柜台": "004", "余款分": 5000, "依据": FULL}]


def test_named_overpay_leaves_remainder_on_same_shop():
    vouchers, _ = parse_vouchers(
        [{"id": "T4", "day": "2026-11-22", "shop": "002", "amount": "200"}], SHOPS
    )
    lines, _, leftovers = allocate(vouchers, RECONCILE, DATES)
    assert [(r["柜台"], r["核销分"]) for r in lines] == [("002", 13000)]
    assert leftovers[0]["余款分"] == 7000 and leftovers[0]["柜台"] == "002"


def test_shop_never_written_off_beyond_its_arrears():
    vouchers, _ = parse_vouchers(
        [
            {"id": "T1", "day": "2026-11-21", "amount": "10000"},
            {"id": "T2", "day": "2026-11-22", "amount": "10000"},
        ],
        SHOPS,
    )
    lines, receivables, _ = allocate(vouchers, RECONCILE, DATES)
    applied = {}
    for line in lines:
        applied[line["柜台"]] = applied.get(line["柜台"], 0) + line["核销分"]
    for shop, total in applied.items():
        due = next(r["应缴分"] - (r["实缴分"] or 0) for r in RECONCILE if r["柜台"] == shop)
        assert total <= due
    assert all(item["待核销分"] >= 0 for item in receivables.values())


def test_quarantine_missing_amount_and_unknown_shop():
    _, claim = build_claim(sample_bytes(), "2026-11")
    codes = {r["流水号"]: r["原因码"] for r in claim["凭证隔离"]}
    assert codes["T1004"] == "VOUCHER_AMOUNT"
    assert codes["T1005"] == "VOUCHER_SHOP"
    assert claim["认领清单"]["可发布"] is False


def test_duplicate_voucher_id_quarantined():
    accepted, isolated = parse_vouchers(
        [
            {"id": "T1", "day": "2026-11-21", "amount": "10"},
            {"id": "T1", "day": "2026-11-22", "amount": "20"},
        ],
        SHOPS,
    )
    assert len(accepted) == 1
    assert isolated[0]["原因码"] == "VOUCHER_DUPLICATE"


def test_bad_voucher_date_quarantined():
    _, isolated = parse_vouchers([{"id": "T1", "day": "not-a-date", "amount": "10"}], SHOPS)
    assert isolated[0]["原因码"] == "VOUCHER_DATE"


def test_idempotent_rerun_does_not_double_write(tmp_path):
    raw = sample_bytes()
    store = RunStore(tmp_path / "claim.sqlite")
    first, reused_first = claim_once(store, raw, "2026-11")
    second, reused_second = claim_once(store, raw, "2026-11")
    assert reused_first is False and reused_second is True
    assert first["认领清单"]["认领批次"] == second["认领清单"]["认领批次"]
    assert len(store.history()) == 1
    assert first["柜台认领"] == second["柜台认领"]


def test_failed_generation_keeps_previous_version(tmp_path):
    store = RunStore(tmp_path / "claim.sqlite")
    good, _ = claim_once(store, sample_bytes(), "2026-11")
    before = len(store.history())
    try:
        claim_once(store, b"{", "2026-11")
    except InputError:
        pass
    assert len(store.history()) == before
    assert store.get(good["认领清单"]["认领批次"]) is not None


def test_claim_api_and_workbench(client):
    raw = sample_bytes()
    first = client.post(
        "/api/claims", data={"period": "2026-11", "file": (io.BytesIO(raw), "vouchers.json")}
    )
    assert first.status_code == 201 and first.json["publishable"] is False
    second = client.post(
        "/api/claims", data={"period": "2026-11", "file": (io.BytesIO(raw), "vouchers.json")}
    )
    assert second.status_code == 200 and second.json["id"] == first.json["id"]
    claim_id = first.json["id"]
    detail = client.get(f"/api/claim/{claim_id}")
    assert detail.status_code == 200 and "凭证核销" in detail.json
    page = client.get(f"/work/claim?run={claim_id}")
    assert page.status_code == 200 and "分柜台核销结果".encode() in page.data
    export = client.get(f"/api/claim/{claim_id}/export")
    assert export.status_code == 200 and export.headers["Content-Disposition"].startswith("attachment;")


def test_default_claim_workbench_renders(client):
    response = client.get("/work/claim")
    assert response.status_code == 200
    assert "缴款认领".encode() in response.data


def test_original_vouchers_and_source_bills_retained():
    _, claim = build_claim(sample_bytes(), "2026-11")
    assert {v["凭证号"] for v in claim["原始凭证"]} >= {"T1001", "T1002", "T1003", "T1006"}
    assert set(claim["源账单"]) == {"001", "002", "003", "004"}


def test_clean_batch_is_publishable_and_matches_arrears():
    raw = (SAMPLE.parent / "claim_clean.json").read_bytes()
    _, claim = build_claim(raw, "2026-11")
    assert claim["认领清单"]["可发布"] is True
    assert claim["凭证隔离"] == []
    by_shop = {r["柜台"]: r for r in claim["柜台认领"]}
    assert by_shop["001"]["本次核销分"] == 500 and by_shop["001"]["核销后欠缴分"] == 0
    assert by_shop["002"]["本次核销分"] == 13000 and by_shop["002"]["核销后欠缴分"] == 0
    assert by_shop["003"]["本次核销分"] == 10000 and by_shop["003"]["核销后欠缴分"] == 17000
    split = [r for r in claim["凭证核销"] if r["凭证号"] == "T2001"]
    assert [(r["柜台"], r["核销分"]) for r in split] == [("001", 500), ("002", 13000)]


def test_optional_sections_default_to_empty():
    data = open_payload((SAMPLE.parent / "mall.json").read_bytes())
    assert data.get("vouchers", []) == []
    assert data.get("ledger", []) == []
