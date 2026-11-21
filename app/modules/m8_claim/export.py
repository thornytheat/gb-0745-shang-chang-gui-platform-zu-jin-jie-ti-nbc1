import json

from flask import Response


def claim_pack(claim):
    claim_id = claim["认领清单"]["认领批次"]
    filename = f"claim-{claim_id}.json"
    return Response(
        json.dumps(claim, ensure_ascii=False, indent=2) + "\n",
        mimetype="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
