from flask import Blueprint, abort, jsonify, request

from app.config import MAX_SOURCE_BYTES
from app.errors import InputError
from app.modules.m8_claim.export import claim_pack
from app.modules.m8_claim.service import claim_once
from app.web import find_run, store

routes = Blueprint("claim", __name__)

CLAIM_KEYS = ("认领清单", "凭证核销", "柜台认领", "待认领余款", "凭证隔离")


@routes.get("/api/claim/<claim_id>")
def inspect_claim(claim_id):
    claim = find_run(claim_id)
    if "认领清单" not in claim:
        abort(404)
    return jsonify({key: claim[key] for key in CLAIM_KEYS})


@routes.post("/api/claims")
def execute_claim():
    payload = request.get_json(silent=True) if request.is_json else request.form
    if not hasattr(payload, "get"):
        raise InputError("BAD_REQUEST", "请求字段无效")
    period = payload.get("period", "2026-11")
    if not isinstance(period, str) or len(period) != 7:
        raise InputError("BAD_PERIOD", "账期无效")
    uploaded = request.files.get("file")
    if not (uploaded and uploaded.filename):
        raise InputError("NO_FILE", "认领需要上传含转账凭证的账簿文件")
    raw = uploaded.read(MAX_SOURCE_BYTES + 1)
    claim, reused = claim_once(store(), raw, period)
    key = claim["认领清单"]["认领批次"]
    return jsonify(
        id=key,
        reused=reused,
        location=f"/work/claim?run={key}",
        publishable=claim["认领清单"]["可发布"],
        quarantined=claim["认领清单"]["隔离凭证数"],
    ), 200 if reused else 201


@routes.get("/api/claim/<claim_id>/export")
def export_claim(claim_id):
    claim = find_run(claim_id)
    if "认领清单" not in claim:
        abort(404)
    return claim_pack(claim)
