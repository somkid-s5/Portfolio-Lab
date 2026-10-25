"""Bounded opaque cursor positions. Cursors are not authorization tokens."""
import base64
import binascii
from datetime import datetime,timezone
import re

from order_domain import Rejected,canonical,identifier,read_json


def page_limit(value):
    if type(value) is not int or not 1 <= value <= 20:
        raise Rejected("invalid_page_limit")
    return value


def encode_cursor(created_at, record_id):
    record_id=identifier(record_id)
    if not isinstance(created_at,datetime) or created_at.tzinfo is None:
        raise ValueError("timezone_required")
    body=canonical({"v":1,"created_at":created_at.astimezone(timezone.utc).isoformat().replace("+00:00","Z"),
                    "id":record_id})
    return base64.urlsafe_b64encode(body).decode("ascii").rstrip("=")


def decode_cursor(value):
    if value is None:
        return None
    if not isinstance(value,str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,256}",value):
        raise Rejected("invalid_cursor")
    try:
        body=base64.b64decode(value+"="*((-len(value))%4),altchars=b"-_",validate=True)
        parsed=read_json(body,limit=256)
        if (set(parsed)!={"v","created_at","id"} or type(parsed["v"]) is not int or
                parsed["v"]!=1 or not isinstance(parsed["created_at"],str) or
                not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?Z",parsed["created_at"])):
            raise ValueError("invalid_cursor")
        created=datetime.fromisoformat(parsed["created_at"][:-1]+"+00:00")
        key=identifier(parsed["id"])
    except (ValueError,TypeError,binascii.Error):
        raise Rejected("invalid_cursor") from None
    return created,key


def page(rows,limit,key):
    limit=page_limit(limit)
    visible=rows[:limit]
    cursor=(encode_cursor(visible[-1]["created_at"],visible[-1][key])
            if len(rows)>limit else None)
    return {"items":visible,"next_cursor":cursor}
