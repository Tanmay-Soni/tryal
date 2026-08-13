import json
import os
from typing import Any
from uuid import uuid4

from backend.models import ConvokeEnrichmentRequest, ConvokeProgram, ConvokeToolInfo


class ConvokeIntegrationError(RuntimeError):
    pass


def fetch_programs(filters: ConvokeEnrichmentRequest) -> list[ConvokeProgram]:
    if _truthy(os.getenv("CONVOKE_MOCK")):
        return _mock_programs(filters)
    return _fetch_programs_via_mcp(filters)


def discover_tools() -> list[ConvokeToolInfo]:
    tools = _with_mcp_client(lambda client: list(client.list_tools_sync()))
    return [_normalize_tool(tool) for tool in tools]


def _fetch_programs_via_mcp(
    filters: ConvokeEnrichmentRequest,
) -> list[ConvokeProgram]:
    def call_program_tool(client: Any) -> Any:
        tools = list(client.list_tools_sync())
        tool = _select_program_tracker_tool(tools)
        if tool is None:
            available = ", ".join(_tool_name(candidate) for candidate in tools)
            raise ConvokeIntegrationError(
                f"could not find a Program Tracker MCP tool; available tools: {available}"
            )

        tool_name = _tool_name(tool)
        arguments = filters.model_dump(exclude_none=True)
        return client.call_tool_sync(
            tool_use_id=f"convoke_{uuid4().hex}",
            name=tool_name,
            arguments=arguments,
        )

    result = _with_mcp_client(call_program_tool)
    payload = _extract_payload(result)
    program_records = _extract_program_records(payload)
    return [_normalize_program(record) for record in program_records]


def _with_mcp_client(operation: Any) -> Any:
    mcp_url = os.getenv("CONVOKE_MCP_URL")
    if not mcp_url:
        raise ConvokeIntegrationError(
            "CONVOKE_MCP_URL is required unless CONVOKE_MOCK=true"
        )

    try:
        from strands.tools.mcp import MCPClient  # type: ignore
    except ImportError as exc:
        raise ConvokeIntegrationError(
            "strands-agents is not installed; use CONVOKE_MOCK=true for local demo "
            "or install the Strands MCP dependencies"
        ) from exc

    server_config: dict[str, Any] = {
        "url": mcp_url,
        "transport": os.getenv("CONVOKE_MCP_TRANSPORT", "streamable-http"),
        "continue_on_error": False,
    }
    headers = _auth_headers_from_env()
    if headers:
        server_config["headers"] = headers

    try:
        clients = MCPClient.load_servers({"mcpServers": {"convoke": server_config}})
        if not clients:
            raise ConvokeIntegrationError("no Convoke MCP clients were created")

        with clients[0] as client:
            return operation(client)
    except ConvokeIntegrationError:
        raise
    except Exception as exc:
        message = _format_exception(exc)
        challenge = _probe_mcp_auth_challenge(mcp_url, headers)
        if challenge:
            message = f"{message} | {challenge}"
        raise ConvokeIntegrationError(message) from exc


def _auth_headers_from_env() -> dict[str, str]:
    headers: dict[str, str] = {}

    token = os.getenv("CONVOKE_MCP_AUTH_TOKEN")
    if token:
        header_name = os.getenv("CONVOKE_MCP_AUTH_HEADER", "Authorization")
        if header_name.lower() == "authorization" and not token.lower().startswith(
            "bearer "
        ):
            headers[header_name] = f"Bearer {token}"
        else:
            headers[header_name] = token

    api_key = os.getenv("CONVOKE_MCP_API_KEY") or os.getenv("CONVOKE_API_KEY")
    if api_key:
        header_name = os.getenv("CONVOKE_MCP_API_KEY_HEADER", "X-API-Key")
        headers[header_name] = api_key

    raw_headers = os.getenv("CONVOKE_MCP_HEADERS_JSON")
    if raw_headers:
        try:
            parsed = json.loads(raw_headers)
        except json.JSONDecodeError as exc:
            raise ConvokeIntegrationError(
                "CONVOKE_MCP_HEADERS_JSON must be valid JSON"
            ) from exc
        if not isinstance(parsed, dict):
            raise ConvokeIntegrationError(
                "CONVOKE_MCP_HEADERS_JSON must be a JSON object"
            )
        headers.update({str(key): str(value) for key, value in parsed.items()})

    return headers


def _format_exception(exc: BaseException) -> str:
    messages: list[str] = []
    _collect_exception_messages(exc, messages)
    return " | ".join(messages) or str(exc)


def _collect_exception_messages(
    exc: BaseException, messages: list[str], depth: int = 0
) -> None:
    if depth > 5:
        return

    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    url = getattr(getattr(exc, "request", None), "url", None)
    www_authenticate = None
    if response is not None:
        www_authenticate = response.headers.get("www-authenticate")

    message = f"{exc.__class__.__name__}: {exc}"
    if status:
        message += f" status_code={status}"
    if url:
        message += f" url={url}"
    if www_authenticate:
        message += f" www-authenticate={www_authenticate}"
    if message not in messages:
        messages.append(message)

    for nested in getattr(exc, "exceptions", []) or []:
        if isinstance(nested, BaseException):
            _collect_exception_messages(nested, messages, depth + 1)


def _probe_mcp_auth_challenge(mcp_url: str, headers: dict[str, str]) -> str | None:
    try:
        import httpx

        payload = {
            "jsonrpc": "2.0",
            "id": "auth-probe",
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {
                    "name": "trial-compliance",
                    "version": "0.1.0",
                },
            },
        }
        response = httpx.post(
            mcp_url,
            headers={"Content-Type": "application/json", **headers},
            json=payload,
            timeout=20,
        )
    except Exception as exc:
        return f"auth_probe_error={exc.__class__.__name__}: {exc}"

    www_authenticate = response.headers.get("www-authenticate")
    body = response.text.strip()
    message = f"auth_probe_status={response.status_code}"
    if www_authenticate:
        message += f" www-authenticate={www_authenticate}"
    if body:
        message += f" body={body}"
    return message


def _select_program_tracker_tool(tools: list[Any]) -> Any | None:
    ranked: list[tuple[int, Any]] = []
    for tool in tools:
        name = _tool_name(tool).lower()
        description = _tool_description(tool).lower()
        haystack = f"{name} {description}"
        if "program" not in haystack:
            continue

        score = 1
        if "tracker" in haystack:
            score += 5
        if "search" in haystack or "query" in haystack or "find" in haystack:
            score += 3
        if "clinical" in haystack or "biopharma" in haystack:
            score += 1
        ranked.append((score, tool))

    if not ranked:
        return None
    ranked.sort(key=lambda item: item[0], reverse=True)
    return ranked[0][1]


def _tool_name(tool: Any) -> str:
    if isinstance(tool, dict):
        return str(tool.get("name") or tool.get("tool_name") or "")
    return str(getattr(tool, "name", None) or getattr(tool, "tool_name", ""))


def _tool_description(tool: Any) -> str:
    if isinstance(tool, dict):
        return str(tool.get("description") or "")
    return str(getattr(tool, "description", "") or "")


def _normalize_tool(tool: Any) -> ConvokeToolInfo:
    tool_spec = _tool_spec(tool)
    name = _tool_name(tool)
    description = _tool_description(tool) or None
    input_schema = _input_schema(tool, tool_spec)

    if not name and tool_spec:
        name = str(tool_spec.get("name") or "")
    if description is None and tool_spec:
        description = tool_spec.get("description")

    return ConvokeToolInfo(
        name=name,
        description=description,
        input_schema=input_schema,
    )


def _tool_spec(tool: Any) -> dict[str, Any]:
    if isinstance(tool, dict):
        spec = tool.get("tool_spec") or tool.get("toolSpec") or tool
    else:
        spec = getattr(tool, "tool_spec", None) or getattr(tool, "toolSpec", None)
    if hasattr(spec, "model_dump"):
        spec = spec.model_dump()
    return spec if isinstance(spec, dict) else {}


def _input_schema(tool: Any, tool_spec: dict[str, Any]) -> dict[str, Any] | None:
    candidates = []
    if isinstance(tool, dict):
        candidates.extend(
            [
                tool.get("input_schema"),
                tool.get("inputSchema"),
                tool.get("schema"),
            ]
        )
    else:
        candidates.extend(
            [
                getattr(tool, "input_schema", None),
                getattr(tool, "inputSchema", None),
                getattr(tool, "schema", None),
            ]
        )
    candidates.extend(
        [
            tool_spec.get("input_schema"),
            tool_spec.get("inputSchema"),
            tool_spec.get("schema"),
        ]
    )

    for candidate in candidates:
        if hasattr(candidate, "model_dump"):
            candidate = candidate.model_dump()
        if isinstance(candidate, dict):
            return candidate
    return None


def _extract_payload(result: Any) -> Any:
    if hasattr(result, "structuredContent"):
        return getattr(result, "structuredContent")
    if hasattr(result, "structured_content"):
        return getattr(result, "structured_content")
    if hasattr(result, "model_dump"):
        return result.model_dump()
    if isinstance(result, dict):
        for key in ("structuredContent", "structured_content", "data", "result"):
            if key in result:
                return result[key]
        if "content" in result:
            return _extract_payload(result["content"])
        return result
    if isinstance(result, list):
        parsed_items = [_extract_payload(item) for item in result]
        return parsed_items[-1] if parsed_items else []
    if hasattr(result, "text"):
        return _parse_possible_json(getattr(result, "text"))
    return _parse_possible_json(str(result))


def _parse_possible_json(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text:
        return None
    if text[0] not in "[{":
        return text
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def _extract_program_records(payload: Any) -> list[dict[str, Any]]:
    payload = _parse_possible_json(payload)
    if isinstance(payload, list):
        records: list[dict[str, Any]] = []
        for item in payload:
            if isinstance(item, dict):
                records.append(item)
        return records
    if isinstance(payload, dict):
        for key in ("programs", "results", "items", "data", "records"):
            value = payload.get(key)
            records = _extract_program_records(value)
            if records:
                return records
        return [payload]
    return []


def _normalize_program(record: dict[str, Any]) -> ConvokeProgram:
    return ConvokeProgram(
        drug_name=_first_text(
            record,
            "drug_name",
            "drug",
            "asset",
            "product",
            "investigational_product",
        ),
        organization=_first_text(
            record, "organization", "org", "company", "sponsor", "developer"
        ),
        target=_first_text(record, "target", "targets", "mechanism_target"),
        indication=_first_text(record, "indication", "disease", "condition"),
        phase=_first_text(record, "phase", "development_phase", "clinical_phase"),
        status=_first_text(record, "status", "program_status", "development_status"),
        raw_data=record,
    )


def _first_text(record: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = record.get(key)
        if value is None:
            continue
        if isinstance(value, list):
            if not value:
                continue
            value = value[0]
        if isinstance(value, dict):
            value = value.get("name") or value.get("label") or value.get("value")
        text = str(value).strip()
        if text:
            return text
    return None


def _mock_programs(filters: ConvokeEnrichmentRequest) -> list[ConvokeProgram]:
    seed_indication = filters.indication or "non-small cell lung cancer"
    seed_target = filters.target or "PD-1"
    seed_drug = filters.drug_name or "CTX-101"
    seed_org = filters.organization or "Convoke Demo Bio"

    records = [
        {
            "drug_name": seed_drug,
            "organization": seed_org,
            "target": seed_target,
            "indication": seed_indication,
            "phase": "Phase 2",
            "status": "Active, not recruiting",
            "source": "convoke_mock",
        },
        {
            "drug_name": f"{seed_target}-ADC",
            "organization": "Northstar Therapeutics",
            "target": seed_target,
            "indication": seed_indication,
            "phase": "Phase 1/2",
            "status": "Recruiting",
            "source": "convoke_mock",
        },
    ]

    return [_normalize_program(record) for record in records if _matches(record, filters)]


def _matches(record: dict[str, Any], filters: ConvokeEnrichmentRequest) -> bool:
    requested = filters.model_dump(exclude_none=True)
    if not requested:
        return True

    aliases = {
        "drug_name": "drug_name",
        "organization": "organization",
        "target": "target",
        "indication": "indication",
    }
    for request_key, record_key in aliases.items():
        expected = requested.get(request_key)
        if not expected:
            continue
        actual = str(record.get(record_key, "")).lower()
        if str(expected).lower() not in actual:
            return False
    return True


def _truthy(value: str | None) -> bool:
    return value is not None and value.lower() in {"1", "true", "yes", "on"}
