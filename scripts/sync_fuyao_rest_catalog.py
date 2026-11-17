"""Regenerate the reviewed Fuyao REST catalog from the official OpenAPI JSON.

Download the spec from https://fuyao.aicubes.cn/openapi/financial-api.openapi.json
and pass its file path to this script. Review operation additions and removals
before updating EXPECTED_OPERATIONS. The application never fetches a live spec.
"""

import hashlib
import json
import re
import sys
from pathlib import Path

ORIGIN = "https://fuyao.aicubes.cn"
SPEC_URL = f"{ORIGIN}/openapi/financial-api.openapi.json"
EXPECTED_OPERATIONS = 111
TARGET = Path(__file__).resolve().parents[1] / "src/platform/marketdata/fuyao_rest_catalog.json"
GROUPS = {"a-share", "a-share-index", "fund", "futures", "options", "hk-share", "meta", "news"}
TYPES = {"string", "integer", "number", "boolean"}
SCHEMA_KEYS = {"type", "default", "enum", "minimum", "maximum"}


def extract(raw: bytes) -> dict:
    spec = json.loads(raw)
    auth = spec["components"]["securitySchemes"]["ApiKeyAuth"]
    if (spec["servers"] != [{"url": ORIGIN}] or spec["security"] != [{"ApiKeyAuth": []}]
            or (auth["type"], auth["in"], auth["name"].lower()) != ("apiKey", "header", "x-api-key")):
        raise ValueError("Unexpected host or authentication")
    operations = {}
    for path, methods in spec["paths"].items():
        if set(methods) != {"get"} or not re.fullmatch(r"/api/[a-z-]+(?:/[a-z0-9-]+)+", path):
            raise ValueError(f"Unexpected method or path: {path}")
        operation = methods["get"]
        operation_id = operation["operationId"]
        group = path.split("/")[2]
        docs = operation["externalDocs"]["url"]
        if (group not in GROUPS or not docs.startswith("/docs/api-reference/")
                or operation_id in operations or not re.fullmatch(r"get_[a-z0-9_]+", operation_id)
                or set(operation) - {"tags", "summary", "description", "operationId", "parameters", "responses", "externalDocs"}):
            raise ValueError(f"Unexpected operation: {operation_id}")
        params = []
        for item in operation["parameters"]:
            name, schema = item["name"], item["schema"]
            if (not re.fullmatch(r"[a-z][a-z0-9_]*", name) or item["in"] != "query"
                    or schema["type"] not in TYPES or set(schema) - SCHEMA_KEYS
                    or any(param["name"] == name for param in params)):
                raise ValueError(f"Unsupported parameter: {operation_id}.{name}")
            param = {"name": name, "required": item["required"], "description": item["description"], **schema}
            if "example" in item:
                param["example"] = item["example"]
            if item.get("x-ui-control") == "date-ms":
                param["encoding"] = "date-ms"
                if "x-default-days-ago" in item:
                    param["example_days_ago"] = item["x-default-days-ago"]
            params.append(param)
        operations[operation_id] = {
            "id": operation_id, "method": "GET", "path": path, "group": group, "summary": operation["summary"],
            "description": operation["description"], "docs_url": ORIGIN + docs, "parameters": params,
        }
    if len(operations) != EXPECTED_OPERATIONS:
        raise ValueError(f"Expected {EXPECTED_OPERATIONS} operations, got {len(operations)}")
    return {"source": SPEC_URL, "version": spec["info"]["version"], "sha256": hashlib.sha256(raw).hexdigest(),
            "operations": list(operations.values())}


if __name__ == "__main__":
    catalog = extract(Path(sys.argv[1]).read_bytes())
    TARGET.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
