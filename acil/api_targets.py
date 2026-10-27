"""Safe normalization of observable HTTP targets for trace and risk evidence."""

import hashlib
import re
from urllib.parse import urlsplit

_UUID_SEGMENT = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
_NUMBER_SEGMENT = re.compile(r"^\d+$")


def normalize_api_target(raw_url: object) -> dict | None:
    """Return an endpoint-safe target; queries, fragments, and credentials are omitted."""
    if not isinstance(raw_url, str) or len(raw_url) > 4_096:
        return None
    parsed = urlsplit(raw_url.strip())
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        return None
    host = parsed.hostname.lower()
    segments = []
    for segment in parsed.path.split("/"):
        if not segment:
            continue
        if _UUID_SEGMENT.match(segment):
            segments.append("{uuid}")
        elif _NUMBER_SEGMENT.match(segment):
            segments.append("{id}")
        else:
            segments.append(segment[:80])
    path_template = "/" + "/".join(segments)
    identity = f"{parsed.scheme.lower()}://{host}{path_template}"
    return {
        "scheme": parsed.scheme.lower(),
        "host": host,
        "path_template": path_template,
        "fingerprint": hashlib.sha256(identity.encode()).hexdigest(),
    }


def extract_api_target(attributes: dict) -> tuple[dict, dict | None]:
    """Remove raw URL fields and return safe attributes plus a normalized target."""
    cleaned = dict(attributes)
    raw_url = None
    for key in ("api_url", "request_url", "url", "endpoint"):
        value = cleaned.pop(key, None)
        if raw_url is None:
            raw_url = value
    target = normalize_api_target(raw_url)
    if target is not None:
        cleaned["api_target"] = target
    return cleaned, target
