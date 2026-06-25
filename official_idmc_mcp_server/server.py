"""
Official IDMC MCP Server — proxy wrapper.

Thin auth proxy to the official Informatica-hosted MCP servers.
Authenticates with Informatica, resolves pod_location and url_prefix,
then forwards calls via MCP SDK (SSE transport) with IDS-SESSION-ID.

URL templates are loaded from .env (see .env.example).
"""

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from mcp import ClientSession
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamablehttp_client
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecurityMiddleware

from auth import AuthError, get_session, request_credentials

load_dotenv(Path(__file__).parent / ".env")

async def _no_op_validate(self, request, is_post=False):
    return None
TransportSecurityMiddleware.validate_request = _no_op_validate

mcp = FastMCP("IDMC")


# Patch list_tools to filter by enabled services for the current token.
# We wrap the original handler after all tools are registered (see bottom of file).
_original_list_tools = None


def _patch_list_tools():
    global _original_list_tools
    _original_list_tools = mcp._tool_manager.list_tools

    def _filtered_list_tools():
        all_tools = _original_list_tools()
        creds = request_credentials.get()
        if creds is None:
            return all_tools  # local dev — show all
        services = set(creds.get("services", []))
        if not services:
            return all_tools  # all services enabled
        return [
            t for t in all_tools
            if _TOOL_SERVICE_MAP.get(t.name, "__always__") in services
            or t.name not in _TOOL_SERVICE_MAP
        ]

    mcp._tool_manager.list_tools = _filtered_list_tools


# ---------------------------------------------------------------------------
# Service access guard
# ---------------------------------------------------------------------------

def _service_enabled(service_key: str) -> bool:
    """Return True if the current token permits this service.

    An empty services list means all services are enabled (backwards compatible
    with tokens generated before the services feature was added).
    """
    creds = request_credentials.get()
    if creds is None:
        return True  # local dev — no token restrictions
    services = creds.get("services", [])
    return not services or service_key in services


# ---------------------------------------------------------------------------
# URL resolution
# ---------------------------------------------------------------------------

def _resolve_url(env_key: str) -> str:
    template = os.environ.get(env_key, "")
    if not template:
        raise RuntimeError(f"Missing environment variable: {env_key}")
    session = get_session()
    return template.format(
        pod=session.pod,
        pod_location=session.pod_location,
        url_prefix=session.url_prefix,
    )


# ---------------------------------------------------------------------------
# Upstream MCP client
# ---------------------------------------------------------------------------

@asynccontextmanager
async def _upstream_session(service_url: str, session_id: str):
    """Open an MCP client session — SSE first, streamable HTTP fallback."""
    headers = {"IDS-SESSION-ID": session_id}

    connected = False
    try:
        async with sse_client(service_url, headers=headers) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                connected = True
                yield session
        return
    except Exception:
        if connected:
            raise

    async with streamablehttp_client(service_url, headers=headers) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session


def _unwrap_error(e: BaseException) -> str:
    if hasattr(e, "exceptions") and e.exceptions:
        return _unwrap_error(e.exceptions[0])
    return str(e)


async def _call_upstream(env_key: str, tool_name: str, arguments: dict) -> Any:
    try:
        session = get_session()
        url = _resolve_url(env_key)
    except (AuthError, RuntimeError) as e:
        return {"error": str(e)}

    try:
        async with _upstream_session(url, session.session_id) as upstream:
            result = await upstream.call_tool(tool_name, arguments)
        parts = [c.text for c in result.content if hasattr(c, "text")]
        return "\n".join(parts) if parts else str(result.content)
    except BaseException as e:
        return {"error": _unwrap_error(e), "error_type": type(e).__name__, "url": url}


async def _list_upstream(env_key: str) -> dict:
    try:
        session = get_session()
        url = _resolve_url(env_key)
    except (AuthError, RuntimeError) as e:
        return {"error": str(e)}

    try:
        async with _upstream_session(url, session.session_id) as upstream:
            result = await upstream.list_tools()
        return {
            "url": url,
            "tools": [
                {
                    "name": t.name,
                    "description": t.description or "",
                    "inputSchema": dict(t.inputSchema) if t.inputSchema else {},
                }
                for t in result.tools
            ],
        }
    except BaseException as e:
        return {"error": _unwrap_error(e), "url": url}


# ---------------------------------------------------------------------------
# Address Verification
# ---------------------------------------------------------------------------

@mcp.tool()
async def address_verify(inputs: list, job_token: str = "") -> Any:
    """Verify and standardize postal addresses using Informatica DQ Address Verification.

    Args:
        inputs: List of address objects. Each object may contain:
                - AddressElements: {Country, Locality, PostalCode, AdministrativeDivision}
                - PreformattedData: {PostalDeliveryAddressLines}
        job_token: Optional GUID to avoid consuming extra verification hits on retry.
    """
    if not _service_enabled("address_verification"):
        return {"error": "Address Verification is not enabled for this token."}
    args = {"Request": {"IO": {"Inputs": inputs}}}
    if job_token:
        args["JobToken"] = job_token
    return await _call_upstream("ADDRESS_VERIFICATION_URL", "verify_address", args)


# ---------------------------------------------------------------------------
# CDGC Metadata Search
# ---------------------------------------------------------------------------

@mcp.tool()
async def cdgc_search_metadata(knowledgeQuery: str) -> Any:
    """Search the CDGC metadata catalog for assets, datasets, glossary terms, and more.

    Args:
        knowledgeQuery: Natural language query (e.g. 'tables with PII data',
                        'certified financial terms', 'customer datasets')
    """
    if not _service_enabled("cdgc_metadata_search"):
        return {"error": "CDGC Metadata Search is not enabled for this token."}
    return await _call_upstream("CDGC_METADATA_SEARCH_URL", "search_metadata", {
        "knowledgeQuery": knowledgeQuery,
    })


@mcp.tool()
async def cdgc_get_asset_details(id: str, scheme: str) -> Any:
    """Retrieve complete metadata details for a single catalog asset.

    Args:
        id: Asset identifier
        scheme: Identity scheme — "internal" or "external"
    """
    if not _service_enabled("cdgc_metadata_search"):
        return {"error": "CDGC Metadata Search is not enabled for this token."}
    return await _call_upstream("CDGC_METADATA_SEARCH_URL", "get_asset_details", {
        "id": id,
        "scheme": scheme,
    })


# ---------------------------------------------------------------------------
# MDM Customer Identification
# ---------------------------------------------------------------------------

@mcp.tool()
async def customer_search(entityType: str, recordsToReturn: int = 10,
                           search: str = "", fields: dict = None,
                           filters: list = None) -> Any:
    """Search for customer records in MDM Customer 360.

    Args:
        entityType: "c360.person" or "c360.organization"
        recordsToReturn: Number of records to return (default 10)
        search: Free-text search string (cannot be combined with fields)
        fields: Structured field search — e.g. {"firstName": "John", "lastName": "Smith",
                "phoneNumber": "...", "addressLine1": "...", "city": "...",
                "state": "...", "postalCode": "...", "country": "..."}
        filters: Array of filter conditions — e.g. [{"fieldName": "...",
                 "comparator": "...", "fieldValue": "..."}]
    """
    if not _service_enabled("customer_identification"):
        return {"error": "Customer Identification is not enabled for this token."}
    args = {"entityType": entityType, "recordsToReturn": recordsToReturn}
    if search:
        args["search"] = search
    if fields:
        args["fields"] = fields
    if filters:
        args["filters"] = filters
    return await _call_upstream("CUSTOMER_IDENTIFICATION_URL", "search_master_record", args)


@mcp.tool()
async def customer_get_details(entityType: str, id: str) -> Any:
    """Retrieve full details for a specific MDM customer master record.

    Args:
        entityType: "c360.person" or "c360.organization"
        id: Business ID of the master record
    """
    if not _service_enabled("customer_identification"):
        return {"error": "Customer Identification is not enabled for this token."}
    return await _call_upstream("CUSTOMER_IDENTIFICATION_URL", "get_master_record_details", {
        "entityType": entityType,
        "id": id,
    })


# ---------------------------------------------------------------------------
# Data Marketplace — Data Provisioning
# ---------------------------------------------------------------------------

@mcp.tool()
async def data_provisioning_list_collections(search: str = "", limit: int = 20) -> Any:
    """List available data collections in the Informatica Data Marketplace.

    Args:
        search: Optional search string to filter collections
        limit: Maximum number of results to return (default 20)
    """
    if not _service_enabled("data_provisioning"):
        return {"error": "Data Provisioning is not enabled for this token."}
    args = {}
    if search:
        args["search"] = search
    if limit:
        args["limit"] = limit
    return await _call_upstream("DATA_PROVISIONING_URL", "list_data_collections", args)


@mcp.tool()
async def data_provisioning_list_targets(id: str) -> Any:
    """List available delivery targets for a data collection.

    Args:
        id: UUID of the data collection
    """
    if not _service_enabled("data_provisioning"):
        return {"error": "Data Provisioning is not enabled for this token."}
    return await _call_upstream("DATA_PROVISIONING_URL", "list_delivery_targets", {"id": id})


@mcp.tool()
async def data_provisioning_checkout(dataCollectionId: str, justification: str,
                                      requestedProvisionedTargetRef: str,
                                      customAttributes: list = None) -> Any:
    """Submit a data order (checkout) for a data collection in the Data Marketplace.

    Args:
        dataCollectionId: UUID of the data collection to order
        justification: Business reason for requesting the data
        requestedProvisionedTargetRef: Reference to the requested delivery target
        customAttributes: Optional list of custom attribute key/value pairs
    """
    if not _service_enabled("data_provisioning"):
        return {"error": "Data Provisioning is not enabled for this token."}
    args = {
        "dataCollectionId": dataCollectionId,
        "justification": justification,
        "requestedProvisionedTargetRef": requestedProvisionedTargetRef,
    }
    if customAttributes:
        args["customAttributes"] = customAttributes
    return await _call_upstream("DATA_PROVISIONING_URL", "checkout_data_order", args)


# ---------------------------------------------------------------------------
# Job Management
# ---------------------------------------------------------------------------

@mcp.tool()
async def job_run_mapping(taskType: str, taskId: str = "",
                           taskName: str = "", taskFederatedId: str = "") -> Any:
    """Run an Informatica mapping or workflow task.

    Args:
        taskType: Task type — e.g. MTT, WORKFLOW
        taskId: Task ID (use one of taskId, taskName, or taskFederatedId)
        taskName: Task name
        taskFederatedId: Federated task ID
    """
    if not _service_enabled("job_management"):
        return {"error": "Job Management is not enabled for this token."}
    args = {"taskType": taskType}
    if taskId:
        args["taskId"] = taskId
    if taskName:
        args["taskName"] = taskName
    if taskFederatedId:
        args["taskFederatedId"] = taskFederatedId
    return await _call_upstream("JOB_MANAGEMENT_URL", "run_mapping_task", args)


@mcp.tool()
async def job_get_status(taskId: str, runId: int) -> Any:
    """Get the status of a running or completed Informatica job.

    Args:
        taskId: Task ID of the job
        runId: Run ID (int64) of the specific job execution
    """
    if not _service_enabled("job_management"):
        return {"error": "Job Management is not enabled for this token."}
    return await _call_upstream("JOB_MANAGEMENT_URL", "get_job_status", {
        "taskId": taskId,
        "runId": runId,
    })


@mcp.tool()
async def job_stop(taskType: str, taskId: str = "",
                   taskName: str = "", taskFederatedId: str = "") -> Any:
    """Stop a running Informatica job.

    Args:
        taskType: Task type — e.g. MTT, WORKFLOW
        taskId: Task ID (use one of taskId, taskName, or taskFederatedId)
        taskName: Task name
        taskFederatedId: Federated task ID
    """
    if not _service_enabled("job_management"):
        return {"error": "Job Management is not enabled for this token."}
    args = {"taskType": taskType}
    if taskId:
        args["taskId"] = taskId
    if taskName:
        args["taskName"] = taskName
    if taskFederatedId:
        args["taskFederatedId"] = taskFederatedId
    return await _call_upstream("JOB_MANAGEMENT_URL", "stop_running_job", args)


# ---------------------------------------------------------------------------
# Diagnostic tools
# ---------------------------------------------------------------------------

_ALL_SERVICES = {
    "address_verification":    "ADDRESS_VERIFICATION_URL",
    "cdgc_metadata_search":    "CDGC_METADATA_SEARCH_URL",
    "customer_identification": "CUSTOMER_IDENTIFICATION_URL",
    "data_provisioning":       "DATA_PROVISIONING_URL",
    "job_management":          "JOB_MANAGEMENT_URL",
}

# Maps each proxy tool name to its service key.
# Tools NOT in this map (diagnostics, version) are always visible.
_TOOL_SERVICE_MAP = {
    "address_verify":                       "address_verification",
    "cdgc_search_metadata":                 "cdgc_metadata_search",
    "cdgc_get_asset_details":               "cdgc_metadata_search",
    "customer_search":                      "customer_identification",
    "customer_get_details":                 "customer_identification",
    "data_provisioning_list_collections":   "data_provisioning",
    "data_provisioning_list_targets":       "data_provisioning",
    "data_provisioning_checkout":           "data_provisioning",
    "job_run_mapping":                      "job_management",
    "job_get_status":                       "job_management",
    "job_stop":                             "job_management",
}


def _enabled_services() -> dict:
    """Return the subset of _ALL_SERVICES permitted by the current token."""
    creds = request_credentials.get()
    services = creds.get("services", []) if creds else []
    if not services:
        return _ALL_SERVICES  # empty list = all enabled
    return {k: v for k, v in _ALL_SERVICES.items() if k in services}


@mcp.tool()
async def discover_all_schemas() -> dict:
    """Fetch the full input schemas for all upstream Informatica MCP services enabled for this token."""
    results = {}
    for service, key in _enabled_services().items():
        results[service] = await _list_upstream(key)
    return results


@mcp.tool()
async def list_upstream_tools(service: str) -> dict:
    """List the tools available on a specific upstream Informatica MCP server.

    Args:
        service: One of the services enabled for this token.
    """
    enabled = _enabled_services()
    key = enabled.get(service)
    if not key:
        return {"error": f"Service '{service}' is not available. Enabled services: {list(enabled.keys())}"}
    return await _list_upstream(key)


@mcp.tool()
async def debug_resolve_urls() -> dict:
    """Show the resolved upstream MCP URLs for the current session credentials."""
    try:
        session = get_session()
        env_keys = {
            "address_verification":    "ADDRESS_VERIFICATION_URL",
            "cdgc_metadata_search":    "CDGC_METADATA_SEARCH_URL",
            "customer_identification": "CUSTOMER_IDENTIFICATION_URL",
            "data_provisioning":       "DATA_PROVISIONING_URL",
            "job_management":          "JOB_MANAGEMENT_URL",
        }
        creds = request_credentials.get()
        return {
            "pod": session.pod,
            "pod_location": session.pod_location,
            "url_prefix": session.url_prefix,
            "server_url": session.server_url,
            "enabled_services": creds.get("services", []) if creds else [],
            "resolved_urls": {
                name: os.environ.get(key, "").format(
                    pod=session.pod,
                    pod_location=session.pod_location,
                    url_prefix=session.url_prefix,
                )
                for name, key in env_keys.items()
            },
        }
    except AuthError as e:
        return {"error": str(e)}


@mcp.tool()
def get_server_version() -> dict:
    """Return the version of this official IDMC MCP server."""
    return {"version": "20260624.4", "server": "official-idmc-mcp"}


# Apply the list_tools filter after all tools are registered.
_patch_list_tools()
