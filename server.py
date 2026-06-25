"""
CDGC MCP Server
Exposes Informatica Cloud Data Governance & Catalog (CDGC), Data Marketplace (CDMP),
and IDMC user/connection management APIs as MCP tools for use with Claude Code.

Usage:
    python server.py

Registration (add to ~/.claude/settings.json under mcpServers):
    "cdgc": {
        "command": "python",
        "args": ["c:/Toolbox/Python/Projects/CDGC MCP Server/server.py"]
    }
"""

from typing import Optional
import os
import requests
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecurityMiddleware
from auth import get_session

VERSION = "20260529.1"

# Disable all MCP transport security checks — we handle auth via X-IDMC-Token.
async def _no_op_validate(self, request, is_post=False):
    return None
TransportSecurityMiddleware.validate_request = _no_op_validate

mcp = FastMCP("CDGC")


# ---------------------------------------------------------------------------
# Version
# ---------------------------------------------------------------------------

@mcp.tool()
def get_server_version() -> dict:
    """Return the version of this CDGC MCP server.

    Returns:
        Dict with "version" key containing the datestamp version string.
    """
    return {"version": VERSION}


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _r(resp: requests.Response) -> dict:
    """Normalise an HTTP response into a dict for return to the LLM."""
    if resp.status_code == 204:
        return {"status": "ok"}
    if resp.status_code in (200, 201, 202):
        try:
            return resp.json()
        except Exception:
            return {"status": "ok", "status_code": resp.status_code}
    try:
        return {"error": resp.status_code, "detail": resp.json()}
    except Exception:
        return {"error": resp.status_code, "detail": resp.text}


# ===========================================================================
# CDGC PUBLIC API — SEARCH
# ===========================================================================

@mcp.tool()
def search_assets(
    query: str = "*",
    from_index: int = 0,
    size: int = 20,
    segments: str = "all",
) -> dict:
    """Search for assets in the CDGC catalog using the knowledge query language.

    PREFER internal_search OVER THIS TOOL when possible — it is faster, supports
    bulk fetch by ID, and handles complex filters in one call. Use this tool only
    when you need the natural-language knowledge query syntax (e.g. "tables related
    to CDEs", "assets related to Policy X") that internal_search cannot express.

    Before constructing a query, read the resource examples://cdgc-search-queries
    for proven query patterns organized by category (policies, DQ, lineage, CDEs, etc.).

    Args:
        query: Natural-language or keyword search string. "*" returns everything.
        from_index: Pagination start offset (default 0).
        size: Number of results to return (default 20, max 100).
        segments: Detail level — "all", "summary", etc. (default "all").

    Returns:
        Dict with "hits" list of matching assets and total count.
    """
    s = get_session()
    resp = requests.post(
        f"{s.cdgc_api_url}/data360/search/v1/assets",
        params={"knowledgeQuery": query, "segments": segments},
        json={"from": from_index, "size": size},
        headers=s.cdgc_headers(),
        timeout=30,
    )
    return _r(resp)


@mcp.tool()
def get_asset(
    asset_id: str,
    scheme: str = "internal",
    segments: str = "all",
) -> dict:
    """Get full details of a single CDGC asset by ID.

    NOTE: If you need details for MORE THAN ONE asset, use internal_search with a
    terms query on core.identity instead — it fetches all of them in a single call
    and is significantly faster than calling this tool in a loop.

    Args:
        asset_id: Asset UUID (scheme="internal") or reference like "BT-123" (scheme="external").
        scheme: "internal" (UUID) or "external" (reference ID). Default "internal".
        segments: Detail level — "all", "summary", etc.

    Returns:
        Full asset record including attributes, relationships, and stakeholders.
    """
    s = get_session()
    resp = requests.get(
        f"{s.cdgc_api_url}/data360/search/v1/assets/{asset_id}",
        params={"scheme": scheme, "segments": segments},
        headers=s.cdgc_headers(),
        timeout=30,
    )
    return _r(resp)


@mcp.tool()
def get_multiple_assets(
    asset_ids: list[str],
    scheme: str = "internal",
    segments: str = "all",
) -> dict:
    """Get details for multiple CDGC assets in one call. Limited to 5 IDs per call.

    PREFER internal_search FOR BULK FETCHING — it has no 5-ID limit and returns
    results faster. Use a terms query on core.identity:
      {"query": {"bool": {"must": [{"terms": {"elementType": ["OBJECT"]}},
        {"terms": {"core.identity": ["id1", "id2", ...]}}]}}}

    Args:
        asset_ids: List of asset IDs (max 5).
        scheme: "internal" (UUIDs) or "external" (reference IDs). Default "internal".
        segments: Detail level.

    Returns:
        Dict containing details for all requested assets.
    """
    s = get_session()
    resp = requests.post(
        f"{s.cdgc_api_url}/data360/search/v1/assets/details",
        params={"scheme": scheme, "segments": segments},
        json=asset_ids,
        headers=s.cdgc_headers(),
        timeout=30,
    )
    return _r(resp)


# ===========================================================================
# CDGC PUBLIC API — ASSET MANAGEMENT
# ===========================================================================

@mcp.tool()
def create_asset(
    class_type: str,
    name: str,
    description: str = "",
    parent_id: Optional[str] = None,
    reference_id: Optional[str] = None,
) -> dict:
    """Create a new governance asset in CDGC.

    Args:
        class_type: Asset class type. Common values:
            "com.infa.ccgf.models.governance.BusinessTerm"
            "com.infa.ccgf.models.governance.Domain"
            "com.infa.ccgf.models.governance.SubDomain"
            "com.infa.ccgf.models.governance.Metric"
            "com.infa.ccgf.models.governance.Policy"
            "com.infa.ccgf.models.governance.Regulation"
            "com.infa.ccgf.models.governance.Process"
            "com.infa.ccgf.models.governance.Geography"
            "com.infa.ccgf.models.governance.LegalEntity"
        name: Asset name.
        description: Asset description.
        parent_id: External ID of parent asset (e.g. "DOM-001").
        reference_id: Optional custom external reference ID (e.g. "BT-CUST-001").

    Returns:
        Created asset with its assigned ID.
    """
    s = get_session()
    body: dict = {
        "core.classType": class_type,
        "summary": {"core.name": name, "core.description": description},
    }
    if parent_id:
        body["parent"] = {"core.externalId": parent_id}
    if reference_id:
        body["core.externalId"] = reference_id

    resp = requests.post(
        f"{s.cdgc_api_url}/data360/content/v1/assets",
        json=body,
        headers=s.cdgc_headers(),
        timeout=30,
    )
    return _r(resp)


@mcp.tool()
def update_asset(
    asset_id: str,
    operations: list[dict],
    scheme: str = "external",
) -> dict:
    """Update an existing CDGC asset with PATCH operations.

    Args:
        asset_id: Asset reference ID (e.g. "BT-123") or UUID.
        operations: List of patch operations. Each entry has:
            - "operation": "add" | "replace" | "remove"
            - "segment": "summary" | "stakeholdership" | "selfAttributes" | ...
            - "attributes": dict of attribute key-value pairs
            Example — update description:
            [{"operation": "replace", "segment": "summary",
              "attributes": {"core.description": "New description"}}]
        scheme: "external" (default) or "internal".

    Returns:
        Update response.
    """
    s = get_session()
    resp = requests.patch(
        f"{s.cdgc_api_url}/data360/content/v1/assets/{asset_id}",
        params={"scheme": scheme},
        json=operations,
        headers=s.cdgc_headers(),
        timeout=30,
    )
    return _r(resp)


@mcp.tool()
def delete_asset(
    asset_id: str,
    scheme: str = "external",
    purge: bool = False,
) -> dict:
    """Delete a CDGC asset.

    Args:
        asset_id: Asset reference ID or UUID.
        scheme: "external" (default) or "internal".
        purge: True = hard/permanent delete. False (default) = soft delete.

    Returns:
        Deletion response.
    """
    s = get_session()
    resp = requests.delete(
        f"{s.cdgc_api_url}/data360/content/v1/assets/{asset_id}",
        params={"scheme": scheme, "purge": str(purge).lower()},
        headers=s.cdgc_headers(),
        timeout=30,
    )
    return _r(resp)


# ===========================================================================
# CDGC PUBLIC API — RELATIONSHIPS
# ===========================================================================

@mcp.tool()
def create_relationship(
    from_id: str,
    to_id: str,
    relationship_type: str,
    scheme: str = "external",
) -> dict:
    """Create a relationship between two CDGC assets.

    Args:
        from_id: Source asset ID.
        to_id: Target asset ID.
        relationship_type: Relationship type identifier, e.g.:
            "com.infa.ccgf.models.governance.asscDataSetDataElement"
            "com.infa.ccgf.models.governance.asscDataSetManualDataElement"
        scheme: "external" (default) or "internal".

    Returns:
        Relationship creation response.
    """
    s = get_session()
    resp = requests.post(
        f"{s.cdgc_api_url}/data360/content/v1/assets/{from_id}/{relationship_type}/{to_id}",
        params={"scheme": scheme},
        headers=s.cdgc_headers(),
        timeout=30,
    )
    return _r(resp)


@mcp.tool()
def delete_relationship(
    from_id: str,
    to_id: str,
    relationship_type: str,
    scheme: str = "external",
) -> dict:
    """Delete a relationship between two CDGC assets.

    Args:
        from_id: Source asset ID.
        to_id: Target asset ID.
        relationship_type: Relationship type identifier.
        scheme: "external" (default) or "internal".

    Returns:
        Deletion response.
    """
    s = get_session()
    resp = requests.delete(
        f"{s.cdgc_api_url}/data360/content/v1/assets/{from_id}/{relationship_type}/{to_id}",
        params={"scheme": scheme},
        headers=s.cdgc_headers(),
        timeout=30,
    )
    return _r(resp)


# ===========================================================================
# CDGC PUBLIC API — DATA QUALITY SCORES
# ===========================================================================

@mcp.tool()
def upload_dq_scores(scores: list[dict]) -> dict:
    """Upload data quality scores to existing rule occurrences in CDGC.

    Args:
        scores: List of score objects. Each entry:
            {
              "assetId": "<rule-occurrence-id>",
              "dqscore": {
                "facts": {
                  "com.infa.ccgf.models.governance.value": 95,
                  "com.infa.ccgf.models.governance.totalCount": 10000,
                  "com.infa.ccgf.models.governance.exception": 500,
                  "com.infa.ccgf.models.governance.scannedTime": "2025-10-15T10:00:00.000Z"
                }
              }
            }

    Returns:
        Response with jobId for tracking via get_job_status.
    """
    s = get_session()
    resp = requests.post(
        f"{s.cdgc_api_url}/data360/content/v1/assets/dqscores",
        json=scores,
        headers=s.cdgc_headers(),
        timeout=30,
    )
    return _r(resp)


# ===========================================================================
# CDGC PUBLIC API — CATALOG SOURCES
# ===========================================================================

@mcp.tool()
def list_catalog_sources(
    offset: int = 0,
    limit: int = 25,
    sort: str = "name:ASC",
    filter_str: Optional[str] = None,
    custom: bool = False,
) -> dict:
    """List catalog sources in CDGC.

    Args:
        offset: Pagination start offset (default 0).
        limit: Number to return (default 25).
        sort: "name:ASC" or "name:DESC".
        filter_str: Optional filter, e.g. "type:EQ:Oracle" or "name:LIKE:Retail".
            Operators: EQ, NE, LT, LE, GT, GE, LIKE, NOT_LIKE, IN.
        custom: Include custom catalog sources (default False).

    Returns:
        Paginated list of catalog sources.
    """
    s = get_session()
    params: dict = {
        "offset": offset,
        "limit": limit,
        "sort": sort,
        "custom": str(custom).lower(),
    }
    if filter_str:
        params["filter"] = filter_str

    resp = requests.get(
        f"{s.cdgc_api_url}/data360/catalog-source-management/v1/catalogsources",
        params=params,
        headers=s.cdgc_headers(),
        timeout=30,
    )
    return _r(resp)


@mcp.tool()
def get_catalog_source(catalog_source_id: str) -> dict:
    """Get full configuration of a specific catalog source.

    Args:
        catalog_source_id: Catalog source UUID or name.

    Returns:
        Full catalog source config including capabilities, connection options, etc.
    """
    s = get_session()
    resp = requests.get(
        f"{s.cdgc_api_url}/data360/catalog-source-management/v1/catalogsources/{catalog_source_id}",
        headers=s.cdgc_headers(),
        timeout=30,
    )
    return _r(resp)


@mcp.tool()
def create_catalog_source(catalog_source_payload: dict) -> dict:
    """Create a new catalog source in CDGC.

    The payload follows the CDGC catalog source schema. At minimum provide:
        name, description, type (e.g. "Oracle", "Snowflake"), custom (bool),
        typeOptions.configurationProperties (connection options),
        capabilities (list of capability config objects).

    Example minimal payload:
        {
            "name": "My_Snowflake_Source",
            "description": "Snowflake catalog source",
            "type": "Snowflake",
            "custom": false,
            "typeOptions": {
                "configurationProperties": [
                    {
                        "optionGroupName": "Snowflake OptionGroup",
                        "configOptions": [
                            {"key": "ConnectionId", "values": ["<idmc-connection-id>"]}
                        ]
                    }
                ]
            },
            "capabilities": [
                {"capabilityName": "Metadata Extraction", "configurationProperties": []},
                {"capabilityName": "Data Profiling", "configurationProperties": []},
                {"capabilityName": "Data Classification", "configurationProperties": []},
                {"capabilityName": "Data Quality", "configurationProperties": []}
            ]
        }

    Use list_connections() to find the ConnectionId and
    list_runtime_environments() to find the runtimeEnvironmentId.

    Returns:
        Created catalog source object with its assigned ID.
    """
    s = get_session()
    resp = requests.post(
        f"{s.cdgc_api_url}/data360/catalog-source-management/v1/catalogsources",
        json=catalog_source_payload,
        headers=s.cdgc_headers(),
        timeout=30,
    )
    return _r(resp)


@mcp.tool()
def update_catalog_source(catalog_source_id: str, catalog_source_payload: dict) -> dict:
    """Update an existing catalog source in CDGC.

    IMPORTANT: This is a full PUT — you must pass the complete catalog source
    payload, not just the fields you want to change. Use get_catalog_source()
    first to retrieve the current config, modify the fields you need, then
    pass the full object here.

    Args:
        catalog_source_id: Catalog source UUID or name.
        catalog_source_payload: Complete catalog source object (same schema as
            create_catalog_source). Must include all existing fields.

    Returns:
        Updated catalog source object.
    """
    s = get_session()
    resp = requests.put(
        f"{s.cdgc_api_url}/data360/catalog-source-management/v1/catalogsources/{catalog_source_id}",
        json=catalog_source_payload,
        headers=s.cdgc_headers(),
        timeout=30,
    )
    return _r(resp)


@mcp.tool()
def delete_catalog_source(
    catalog_source_id: str,
    delete_type: str = "delete",
) -> dict:
    """Delete or purge a catalog source.

    Args:
        catalog_source_id: Catalog source UUID or name.
        delete_type:
            "delete"          — remove config + all extracted metadata (default)
            "purge"           — remove extracted metadata only, keep config
            "purge_obsolete"  — remove only obsolete lifecycle objects

    Returns:
        Delete operation response.
    """
    s = get_session()
    resp = requests.delete(
        f"{s.cdgc_api_url}/data360/catalog-source-management/v1/catalogsources/{catalog_source_id}",
        params={"type": delete_type},
        headers=s.cdgc_headers(),
        timeout=30,
    )
    return _r(resp)


@mcp.tool()
def run_catalog_source(
    catalog_source_id: str,
    capabilities: Optional[str] = None,
) -> dict:
    """Trigger a scan job for a catalog source with specific capabilities.

    Args:
        catalog_source_id: Catalog source UUID or name.
        capabilities: Comma-separated list of capabilities to run.
            Available values:
                "Metadata Extraction"
                "Data Profiling"
                "Data Classification"
                "Data Quality"
                "Relationship Discovery"
                "Glossary Association"
            Defaults to all six if not specified.
            Example: "Metadata Extraction,Data Profiling,Data Quality"

    Returns:
        Job response containing jobId — use get_job_status to poll progress.
    """
    s = get_session()
    all_capabilities = [
        "Metadata Extraction",
        "Data Profiling",
        "Data Classification",
        "Data Quality",
        "Relationship Discovery",
        "Glossary Association",
    ]
    if capabilities:
        selected = [c.strip() for c in capabilities.split(",")]
    else:
        selected = all_capabilities

    payload = {"capabilityNames": selected}
    resp = requests.post(
        f"{s.cdgc_api_url}/data360/executable/v1/catalogsource/{catalog_source_id}",
        json=payload,
        headers=s.cdgc_headers(),
        timeout=30,
    )
    return _r(resp)


# ===========================================================================
# CDGC PUBLIC API — JOBS
# ===========================================================================

@mcp.tool()
def get_job_status(job_id: str) -> dict:
    """Get the status and output of a CDGC job.

    Args:
        job_id: Job ID returned by run_catalog_source, upload_dq_scores, etc.

    Returns:
        Job status (state, progress, child tasks, output properties).
    """
    s = get_session()
    # Use URL params directly — requests serialises list values as repeated params
    resp = requests.get(
        f"{s.cdgc_api_url}/data360/observable/v1/jobs/{job_id}"
        "?expandChildren=TASK-HIERARCHY&expandChildren=OUTPUT-PROPERTIES",
        headers=s.cdgc_headers(),
        timeout=30,
    )
    return _r(resp)


# ===========================================================================
# CDGC INTERNAL API — ASSET MODELS
# ===========================================================================

@mcp.tool()
def get_asset_models() -> dict:
    """Get all available asset model/type definitions in CDGC.

    Returns:
        List of asset models with classType identifiers and display names.
        Use classType values as the class_type argument in create_asset.
    """
    s = get_session()
    resp = requests.get(
        f"{s.cdgc_api_url}/ccgf-metadata-discovery/api/v1/models",
        headers=s.cdgc_internal_headers(),
        timeout=30,
    )
    return _r(resp)


# ===========================================================================
# CDGC INTERNAL API — CLASSIFICATIONS
# ===========================================================================

@mcp.tool()
def list_classifications(
    page_size: int = 100,
    page_number: int = 0,
) -> dict:
    """List all data classifications defined in CDGC.

    Args:
        page_size: Results per page (default 100).
        page_number: Page index to retrieve (default 0).

    Returns:
        List of classifications with IDs, names, and metadata.
    """
    s = get_session()
    resp = requests.get(
        f"{s.cdgc_api_url}/ccgf-metadata-discovery/api/v1/classifications",
        params={
            "pageSize": page_size,
            "pageNumber": page_number,
            "sortBy": "name",
            "sortOrder": "asc",
        },
        headers=s.classification_headers(),
        timeout=30,
    )
    return _r(resp)


@mcp.tool()
def get_classification(classification_id: str) -> dict:
    """Get details of a specific CDGC classification.

    Args:
        classification_id: Classification identifier.

    Returns:
        Classification details including rules and associated assets.
    """
    s = get_session()
    resp = requests.get(
        f"{s.cdgc_api_url}/ccgf-metadata-discovery/api/v1/classifications/{classification_id}",
        headers=s.classification_headers(),
        timeout=30,
    )
    return _r(resp)


# ===========================================================================
# CDGC INTERNAL API — WORKFLOWS
# ===========================================================================

@mcp.tool()
def list_workflows(
    limit: int = 50,
    offset: int = 0,
    search: str = "",
    is_template: bool = True,
) -> dict:
    """List workflow definitions in CDGC.

    Args:
        limit: Number to return (default 50).
        offset: Pagination offset (default 0).
        search: Filter workflows by name fragment.
        is_template: Return template workflows only (default True).

    Returns:
        List of workflow definitions with IDs and names.
    """
    s = get_session()
    resp = requests.get(
        f"{s.cdgc_api_url}/htm-carbon/api/v1/workflow-definitions",
        params={
            "application": "CDGC",
            "search": search,
            "isTemplate": str(is_template).lower(),
            "sortByField": "NAME",
            "sort": "ASC",
            "offset": offset,
            "limit": limit,
        },
        headers=s.workflow_headers(),
        timeout=30,
    )
    return _r(resp)


@mcp.tool()
def get_workflow(workflow_id: str) -> dict:
    """Get details of a specific CDGC workflow definition.

    Args:
        workflow_id: Workflow identifier.

    Returns:
        Workflow definition including steps, assignees, and configuration.
    """
    s = get_session()
    resp = requests.get(
        f"{s.cdgc_api_url}/htm-carbon/api/v1/workflow-definitions/{workflow_id}",
        params={"idType": "DEFINITION"},
        headers=s.workflow_headers(),
        timeout=30,
    )
    return _r(resp)


# ===========================================================================
# DATA MARKETPLACE (CDMP) — CATEGORIES
# ===========================================================================

@mcp.tool()
def list_mp_categories(
    search: str = "*",
    offset: int = 0,
    limit: int = 20,
) -> dict:
    """List categories in the Data Marketplace (CDMP).

    Args:
        search: Name filter. "*" returns all (default).
        offset: Pagination offset.
        limit: Number to return (default 20).

    Returns:
        List of marketplace categories.
    """
    s = get_session()
    resp = requests.get(
        f"{s.base_api_url}/data360/marketplace/api/v2/categories",
        params={"search": search, "offset": offset, "limit": limit, "segments": "all"},
        headers=s.cdmp_headers(),
        timeout=30,
    )
    return _r(resp)


@mcp.tool()
def get_mp_category(category_id: str) -> dict:
    """Get details of a specific Data Marketplace category.

    Args:
        category_id: Category identifier.

    Returns:
        Category details including sub-categories and stakeholders.
    """
    s = get_session()
    resp = requests.get(
        f"{s.base_api_url}/data360/marketplace/api/v2/categories/{category_id}",
        params={"segments": "all"},
        headers=s.cdmp_headers(),
        timeout=30,
    )
    return _r(resp)


@mcp.tool()
def create_mp_category(
    name: str,
    description: str = "",
    status: str = "ACTIVE",
    parent_category_id: Optional[str] = None,
) -> dict:
    """Create a new category in the Data Marketplace.

    Args:
        name: Category name.
        description: Category description.
        status: "ACTIVE" (default) or "INACTIVE".
        parent_category_id: Parent category ID for nested categories.

    Returns:
        Created category with its assigned ID.
    """
    s = get_session()
    payload: dict = {"name": name, "status": status}
    if description:
        payload["description"] = description
    if parent_category_id:
        payload["parentCategoryId"] = parent_category_id

    resp = requests.post(
        f"{s.base_api_url}/data360/marketplace/api/v2/categories",
        json=payload,
        headers=s.cdmp_headers(),
        timeout=30,
    )
    return _r(resp)


@mcp.tool()
def delete_mp_category(category_id: str) -> dict:
    """Delete a Data Marketplace category.

    Args:
        category_id: Category identifier.

    Returns:
        Deletion response.
    """
    s = get_session()
    resp = requests.delete(
        f"{s.base_api_url}/data360/marketplace/api/v2/categories/{category_id}",
        headers=s.cdmp_headers(),
        timeout=30,
    )
    return _r(resp)


# ===========================================================================
# DATA MARKETPLACE (CDMP) — DATA COLLECTIONS
# ===========================================================================

@mcp.tool()
def list_data_collections(
    search: str = "",
    offset: int = 0,
    limit: int = 20,
) -> dict:
    """List data collections in the Data Marketplace.

    Args:
        search: Optional name filter.
        offset: Pagination offset.
        limit: Number to return (default 20).

    Returns:
        List of data collections with status and category info.
    """
    s = get_session()
    params: dict = {"offset": offset, "limit": limit, "segments": "all"}
    if search:
        params["search"] = search

    resp = requests.get(
        f"{s.base_api_url}/data360/marketplace/api/v2/data-collections",
        params=params,
        headers=s.cdmp_headers(),
        timeout=30,
    )
    return _r(resp)


@mcp.tool()
def get_data_collection(data_collection_id: str) -> dict:
    """Get details of a specific Data Marketplace data collection.

    Args:
        data_collection_id: Data collection identifier.

    Returns:
        Data collection details including assets, delivery options, and stakeholders.
    """
    s = get_session()
    resp = requests.get(
        f"{s.base_api_url}/data360/marketplace/api/v2/data-collections/{data_collection_id}",
        params={"segments": "all"},
        headers=s.cdmp_headers(),
        timeout=30,
    )
    return _r(resp)


@mcp.tool()
def create_data_collection(
    name: str,
    description: str,
    category_id: str,
    status: str = "PUBLISHED",
) -> dict:
    """Create a new data collection in the Data Marketplace.

    Args:
        name: Collection name.
        description: Collection description.
        category_id: Parent category ID (use list_mp_categories to find IDs).
        status: "PUBLISHED" (default), "DRAFT", or "INACTIVE".

    Returns:
        Created data collection with its assigned ID.
    """
    s = get_session()
    resp = requests.post(
        f"{s.base_api_url}/data360/marketplace/api/v2/data-collections",
        json={
            "name": name,
            "description": description,
            "categoryId": category_id,
            "status": status,
        },
        headers=s.cdmp_headers(),
        timeout=30,
    )
    return _r(resp)


# ===========================================================================
# DATA MARKETPLACE (CDMP) — ORDERS, DELIVERY, ACCESS
# ===========================================================================

@mcp.tool()
def list_orders(offset: int = 0, limit: int = 20) -> dict:
    """List orders in the Data Marketplace.

    Args:
        offset: Pagination offset.
        limit: Number to return (default 20).

    Returns:
        List of marketplace orders with status, requestor, and collection info.
    """
    s = get_session()
    resp = requests.get(
        f"{s.base_api_url}/data360/marketplace/api/v2/orders",
        params={"offset": offset, "limit": limit},
        headers=s.cdmp_headers(),
        timeout=30,
    )
    return _r(resp)


@mcp.tool()
def list_delivery_targets(offset: int = 0, limit: int = 20) -> dict:
    """List delivery targets in the Data Marketplace.

    Args:
        offset: Pagination offset.
        limit: Number to return (default 20).

    Returns:
        List of delivery targets with type and connection details.
    """
    s = get_session()
    resp = requests.get(
        f"{s.base_api_url}/data360/marketplace/api/v2/delivery-targets",
        params={"offset": offset, "limit": limit},
        headers=s.cdmp_headers(),
        timeout=30,
    )
    return _r(resp)


@mcp.tool()
def list_consumer_accesses(offset: int = 0, limit: int = 20) -> dict:
    """List consumer accesses in the Data Marketplace.

    Args:
        offset: Pagination offset.
        limit: Number to return (default 20).

    Returns:
        List of consumer access records with status and expiry.
    """
    s = get_session()
    resp = requests.get(
        f"{s.base_api_url}/data360/marketplace/api/v2/consumer-accesses",
        params={"offset": offset, "limit": limit},
        headers=s.cdmp_headers(),
        timeout=30,
    )
    return _r(resp)


@mcp.tool()
def get_delivery_templates() -> dict:
    """Get available delivery templates from the Data Marketplace.

    Returns:
        List of delivery templates with IDs and configuration options.
    """
    s = get_session()
    resp = requests.get(
        f"{s.cdgc_api_url}/cdmp-marketplace/api/v1/provisioning/deliveryTemplates",
        headers=s.cdmp_headers(),
        timeout=30,
    )
    return _r(resp)


@mcp.tool()
def get_usage_contexts() -> dict:
    """Get available usage contexts for the Data Marketplace.

    Returns:
        List of usage contexts (e.g. Analytics, Reporting) with IDs.
    """
    s = get_session()
    resp = requests.get(
        f"{s.cdgc_api_url}/cdmp-marketplace/api/v1/usageContext",
        headers=s.cdmp_headers(),
        timeout=30,
    )
    return _r(resp)


# ===========================================================================
# IDMC — USER MANAGEMENT
# ===========================================================================

@mcp.tool()
def list_users(limit: int = 100, skip: int = 0) -> dict:
    """List users in the IDMC organization.

    Args:
        limit: Max users to return (default 100, max 200).
        skip: Number to skip for pagination.

    Returns:
        List of users with roles, groups, and profile details.
    """
    s = get_session()
    resp = requests.get(
        f"{s.base_api_url}/public/core/v3/users",
        params={"limit": limit, "skip": skip},
        headers=s.idmc_headers(),
        timeout=30,
    )
    return _r(resp)


@mcp.tool()
def get_user(
    user_id: Optional[str] = None,
    user_name: Optional[str] = None,
) -> dict:
    """Get details of a specific IDMC user.

    Args:
        user_id: User ID (provide this OR user_name).
        user_name: Username (provide this OR user_id).

    Returns:
        User details including assigned roles and groups.
    """
    s = get_session()
    if user_id:
        q = f"userId=={user_id}"
    elif user_name:
        q = f"userName=={user_name}"
    else:
        return {"error": "Provide either user_id or user_name"}

    resp = requests.get(
        f"{s.base_api_url}/public/core/v3/users",
        params={"q": q, "limit": 1},
        headers=s.idmc_headers(),
        timeout=30,
    )
    return _r(resp)


@mcp.tool()
def list_groups(limit: int = 100, skip: int = 0) -> dict:
    """List user groups in the IDMC organization.

    Args:
        limit: Max groups to return (default 100).
        skip: Number to skip for pagination.

    Returns:
        List of user groups with members and assigned roles.
    """
    s = get_session()
    resp = requests.get(
        f"{s.base_api_url}/public/core/v3/userGroups",
        params={"limit": limit, "skip": skip},
        headers=s.idmc_headers(),
        timeout=30,
    )
    return _r(resp)


@mcp.tool()
def list_roles(limit: int = 100, skip: int = 0) -> dict:
    """List roles defined in the IDMC organization.

    Args:
        limit: Max roles to return (default 100).
        skip: Number to skip for pagination.

    Returns:
        List of roles with names and IDs.
    """
    s = get_session()
    resp = requests.get(
        f"{s.base_api_url}/public/core/v3/roles",
        params={"limit": limit, "skip": skip},
        headers=s.idmc_headers(),
        timeout=30,
    )
    return _r(resp)


@mcp.tool()
def get_privileges() -> dict:
    """Get the privileges of the currently authenticated IDMC user.

    Returns:
        List of privileges assigned to the current user session.
    """
    s = get_session()
    resp = requests.get(
        f"{s.base_api_url}/public/core/v3/privileges",
        headers={
            "cookie": f"USER_SESSION={s.session_id}",
            "IDS-SESSION-ID": s.session_id,
            "INFA-SESSION-ID": s.session_id,
        },
        timeout=30,
    )
    return _r(resp)


# ===========================================================================
# IDMC — CONNECTION MANAGEMENT
# ===========================================================================

@mcp.tool()
def list_connections() -> dict:
    """List all connections in the IDMC organization.

    Returns:
        List of connections with type, name, and runtime environment details.
    """
    s = get_session()
    resp = requests.get(
        f"{s.base_api_url}/api/v2/connection",
        headers=s.idmc_headers(),
        timeout=30,
    )
    return _r(resp)


@mcp.tool()
def get_connection(connection_id: str) -> dict:
    """Get the full configuration of a specific IDMC connection.

    Args:
        connection_id: Connection ID.

    Returns:
        Connection configuration including type, options, and runtime environment.
    """
    s = get_session()
    resp = requests.get(
        f"{s.base_api_url}/api/v2/connection/{connection_id}",
        headers=s.idmc_headers(),
        timeout=30,
    )
    return _r(resp)


@mcp.tool()
def test_connection(connection_id: str) -> dict:
    """Test an IDMC connection to verify it can reach its target system.

    Args:
        connection_id: Connection ID to test.

    Returns:
        Test result indicating success or failure with details.
    """
    s = get_session()
    resp = requests.get(
        f"{s.base_api_url}/api/v2/connection/test/{connection_id}",
        headers=s.idmc_headers(),
        timeout=60,
    )
    return _r(resp)


@mcp.tool()
def list_runtime_environments() -> dict:
    """List all runtime environments (Secure Agent groups) in IDMC.

    Returns:
        List of runtime environments with names, IDs, and agent status.
    """
    s = get_session()
    resp = requests.get(
        f"{s.base_api_url}/api/v2/runtimeEnvironment",
        headers=s.idmc_headers(),
        timeout=30,
    )
    return _r(resp)


# ===========================================================================
# CDGC PUBLIC API — BULK EXPORT / IMPORT
# ===========================================================================

@mcp.tool()
def export_assets(
    query: str = "*",
    from_index: int = 0,
    size: int = 10000,
    segments: str = "all",
) -> dict:
    """Start an asynchronous bulk export of assets matching a search query.

    This is the async export endpoint — it returns a jobId immediately.
    Use get_job_status(jobId) to poll until complete, then
    download_export_file(jobId, key) to retrieve the file.

    Args:
        query: CDGC knowledge query string. "*" exports everything.
            See examples://cdgc-search-queries for query patterns.
        from_index: Pagination offset (default 0).
        size: Max assets to export (default 10000).
        segments: Detail level — "all", "summary" (default "all").

    Returns:
        Dict with jobId — poll with get_job_status.
    """
    s = get_session()
    resp = requests.post(
        f"{s.cdgc_api_url}/data360/search/export/v1/assets",
        params={"knowledgeQuery": query, "segments": segments},
        json={"from": from_index, "size": size},
        headers=s.cdgc_headers(),
        timeout=30,
    )
    return _r(resp)


@mcp.tool()
def export_asset_details(asset_ids: list) -> dict:
    """Start an asynchronous bulk export for a specific list of asset IDs.

    Returns full detail for each asset. Use get_job_status then
    download_export_file to retrieve the result.

    Args:
        asset_ids: List of internal asset UUID strings to export.

    Returns:
        Dict with jobId — poll with get_job_status.
    """
    s = get_session()
    resp = requests.post(
        f"{s.cdgc_api_url}/data360/search/export/v1/assets/details",
        json=asset_ids,
        headers=s.cdgc_headers(),
        timeout=30,
    )
    return _r(resp)


@mcp.tool()
def download_export_file(job_id: str, output_property_key: str) -> dict:
    """Download a file produced by a completed export job.

    Use get_job_status(job_id) first to find the outputPropertyKey values
    in the job's outputProperties once it reaches a completed state.

    Args:
        job_id: Job ID returned by export_assets or export_asset_details.
        output_property_key: Key from the job's outputProperties (e.g. "file").

    Returns:
        File content or download URL from the job output.
    """
    s = get_session()
    resp = requests.get(
        f"{s.cdgc_api_url}/data360/observable/v1/jobs/{job_id}"
        f"/outputProperties/files/{output_property_key}",
        headers=s.cdgc_headers(),
        timeout=60,
    )
    return _r(resp)


@mcp.tool()
def import_assets(
    file_path: str,
    validation_policy: str = "CONTINUE_ON_ERROR_WARNING",
) -> dict:
    """Bulk import or curate assets from a file (multipart upload).

    The file should be a CDGC-format export file (JSON or CSV depending
    on what CDGC expects for import). Use export_assets to get the format.

    Args:
        file_path: Absolute local path to the file to upload.
        validation_policy: How to handle errors during import.
            "CONTINUE_ON_ERROR_WARNING" — import valid rows, skip errors (default)
            "STOP_ON_ERROR"             — abort on first error
            "STOP_ON_WARNING"           — abort on first warning or error

    Returns:
        Dict with jobId — poll with get_job_status.
    """
    import os
    s = get_session()
    mime = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" \
        if file_path.lower().endswith(".xlsx") else "application/octet-stream"
    filename = os.path.basename(file_path)
    params = {"validationPolicy": validation_policy}
    with open(file_path, "rb") as f:
        resp = requests.post(
            f"{s.cdgc_api_url}/data360/content/import/v1/assets",
            files={"file": (filename, f, mime)},
            params=params,
            headers={k: v for k, v in s.cdgc_headers().items() if k != "Content-Type"},
            timeout=120,
        )
    return _r(resp)


# ===========================================================================
# CDGC PUBLIC API — DQ PUBLISH
# ===========================================================================

@mcp.tool()
def publish_dq_assets(items: list) -> dict:
    """Create or update DQ templates and DQ occurrences (rule instances) via publish API.

    This endpoint handles both DQ Template creation and DQ Occurrence (rule instance)
    creation. Each item in the list is one asset to create/update.

    Common attributes for DQ Templates:
        core.name, core.description,
        com.infa.ccgf.models.governance.Criticality  (Low/Medium/High/Critical)
        com.infa.ccgf.models.governance.Frequency    (Daily/Weekly/Monthly/etc.)
        com.infa.ccgf.models.governance.MeasuringMethod  (BusinessExtract/InformaticaCloudDataQuality)
        com.infa.ccgf.models.governance.RuleType     (Validity/Completeness/Uniqueness/etc.)
        com.infa.ccgf.models.governance.Target       (numeric threshold, e.g. 90)

    Example item for a DQ Template:
        {
            "attributes": {
                "core.name": "Email Validity Check",
                "core.description": "Checks email format",
                "com.infa.ccgf.models.governance.Criticality": "High",
                "com.infa.ccgf.models.governance.Frequency": "Weekly",
                "com.infa.ccgf.models.governance.MeasuringMethod": "BusinessExtract",
                "com.infa.ccgf.models.governance.RuleType": "Validity",
                "com.infa.ccgf.models.governance.Target": 95
            }
        }

    Args:
        items: List of asset attribute dicts to publish.

    Returns:
        Publish response with created/updated asset IDs.
    """
    s = get_session()
    resp = requests.post(
        f"{s.cdgc_api_url}/data360/content/api/v1/publish",
        json={"items": items},
        headers=s.cdgc_headers(),
        timeout=30,
    )
    return _r(resp)


# ===========================================================================
# CDGC PUBLIC API — AUDIT HISTORY
# ===========================================================================

@mcp.tool()
def get_asset_audit_history(
    asset_id: str,
    scheme: str = "internal",
    hierarchy_options: str = "INCLUDE_ALL_CHILDREN",
    offset: int = 0,
    limit: int = 100,
    sort: str = "timestamp:DESC",
    filters: Optional[str] = None,
) -> dict:
    """Get the audit/event history for a specific asset.

    Useful for seeing scan history, curation events, certification changes, etc.

    Args:
        asset_id: Asset UUID (internal) or external ID.
        scheme: "internal" (default) or "external" — matches the ID type used.
        hierarchy_options: How far to traverse the asset hierarchy:
            "EXCLUDE_HIERARCHY"          — only the asset itself (default for scans)
            "INCLUDE_IMMEDIATE_CHILDREN" — asset + direct children
            "INCLUDE_ALL_CHILDREN"       — asset + all descendants (default)
        offset: Pagination offset (default 0).
        limit: Results per page, max 100 (default 100).
        sort: Sort order, e.g. "timestamp:DESC" or "eventId:DESC,timestamp:DESC".
        filters: Semicolon-separated filter expressions. Each filter uses the
            format "attribute:OPERATOR:(value)". Multiple filters are ANDed.
            Supported attributes: timestamp, modifiedBy, eventType, action,
                                  traceId, changedAttributes, assetTypes,
                                  assetExternalId.
            Operators: GE, LE, IN.
            Examples:
                "timestamp:GE:(2025-01-01T00:00:00.000Z)"
                "action:IN:(UPDATE);eventType:IN:(Certification)"
                "changedAttributes:IN:(core.curationStatus)"
                "changedAttributes:IN:(core.lastScannedOn)"

    Returns:
        Paginated list of audit events for the asset.
    """
    s = get_session()
    params: dict = {
        "scheme": scheme.upper(),
        "hierarchyOptions": hierarchy_options,
        "offset": offset,
        "limit": limit,
        "sort": sort,
    }
    if filters:
        params["filter"] = filters.split(";")
    resp = requests.get(
        f"{s.cdgc_api_url}/data360/audit/v1/assets/{asset_id}/events",
        params=params,
        headers=s.cdgc_headers(),
        timeout=30,
    )
    return _r(resp)


@mcp.tool()
def list_audit_events(
    scheme: str = "internal",
    hierarchy_options: str = "EXCLUDE_HIERARCHY",
    offset: int = 0,
    limit: int = 100,
    sort: str = "timestamp:DESC",
    filters: Optional[str] = None,
) -> dict:
    """Get audit events across multiple assets, filterable by asset type, action, etc.

    Use this to find things like: all glossary terms created this week,
    all columns curated today, all certification changes across the catalog.

    Args:
        scheme: "internal" (default) or "external".
        hierarchy_options:
            "EXCLUDE_HIERARCHY"          — assets only, no children (default)
            "INCLUDE_IMMEDIATE_CHILDREN" — assets + direct children
            "INCLUDE_ALL_CHILDREN"       — assets + all descendants
        offset: Pagination offset (default 0).
        limit: Results per page, max 100 (default 100).
        sort: Sort order, e.g. "timestamp:DESC" or "eventId:DESC,timestamp:DESC".
        filters: Semicolon-separated filter expressions (same format as
            get_asset_audit_history). Additional attributes available here:
                assetTypes    — filter by asset class type
                              e.g. "assetTypes:IN:(com.infa.ccgf.models.governance.BusinessTerm)"
                assetExternalId — filter by external IDs
                              e.g. "assetExternalId:IN:(TERM-1,TERM-2)"
            Examples:
                "assetTypes:IN:(com.infa.ccgf.models.governance.BusinessTerm);action:IN:(INSERT)"
                "assetTypes:IN:(com.infa.odin.models.relational.Column);changedAttributes:IN:(core.curationStatus)"
                "assetTypes:IN:(com.infa.odin.models.relational.Table);eventType:IN:(Certification)"
                "timestamp:GE:(2025-01-01T00:00:00.000Z)"

    Returns:
        Paginated list of audit events matching the filters.
    """
    s = get_session()
    params: dict = {
        "scheme": scheme.upper(),
        "hierarchyOptions": hierarchy_options,
        "offset": offset,
        "limit": limit,
        "sort": sort,
    }
    if filters:
        params["filter"] = filters.split(";")
    resp = requests.get(
        f"{s.cdgc_api_url}/data360/audit/v1/assets/events",
        params=params,
        headers=s.cdgc_headers(),
        timeout=30,
    )
    return _r(resp)


# ===========================================================================
# IDMC API — CONNECTION / RUNTIME ENVIRONMENT BY NAME
# ===========================================================================

@mcp.tool()
def get_connection_by_name(connection_name: str) -> dict:
    """Get an IDMC connection by name.

    Useful when you know the connection name but not its ID.
    Use the returned connection ID when creating catalog sources.

    Args:
        connection_name: Exact name of the connection.

    Returns:
        Connection details including its ID, type, and agent assignment.
    """
    s = get_session()
    resp = requests.get(
        f"{s.base_api_url}/api/v2/connection/name/{connection_name}",
        headers=s.idmc_headers(),
        timeout=30,
    )
    return _r(resp)


@mcp.tool()
def get_runtime_environment_by_name(runtime_environment_name: str) -> dict:
    """Get an IDMC runtime environment (Secure Agent group) by name.

    Useful when you know the environment name but not its ID.
    Use the returned ID when creating catalog sources that require an agent.

    Args:
        runtime_environment_name: Exact name of the runtime environment.

    Returns:
        Runtime environment details including its ID and agent status.
    """
    s = get_session()
    resp = requests.get(
        f"{s.base_api_url}/api/v2/runtimeEnvironmentname/{runtime_environment_name}",
        headers=s.idmc_headers(),
        timeout=30,
    )
    return _r(resp)


# ===========================================================================
# CDGC INTERNAL ELASTICSEARCH SEARCH
# Direct Elasticsearch queries via /ccgf-searchv2/api/v1/search.
# More powerful than search_assets: supports bulk fetch by ID, relationship
# traversal, classType filters, and complex bool queries in one call.
# Before constructing a query, read examples://cdgc-es-queries for patterns.
# ===========================================================================

@mcp.tool()
def internal_search(
    body: dict,
) -> dict:
    """Execute an Elasticsearch query against the CDGC internal search index.

    More powerful than search_assets — use this for:
    - Bulk fetching many assets by ID in one call (avoids looping with get_asset)
    - Filtering by classType, lifecycle, origin, curation status, or any field
    - Traversing relationships (elementType=RELATIONSHIP queries)
    - Finding CDEs, DQ rule occurrences, glossary links, policy/classification links
    - Complex boolean queries with must/filter/should clauses

    IMPORTANT: Before constructing a query, read the resource examples://cdgc-es-queries
    for proven query patterns and a complete classType reference table.

    Args:
        body: Elasticsearch query body. Must be a valid ES bool query dict. Example:
            {
              "from": 0,
              "size": 100,
              "query": {
                "bool": {
                  "must": [{"terms": {"elementType": ["OBJECT"]}}],
                  "filter": [{"terms": {"core.classType": ["com.infa.ccgf.models.governance.BusinessTerm"]}}]
                }
              },
              "sort": [{"core.name": {"order": "asc"}}]
            }

    Returns:
        Elasticsearch response with hits.hits[] containing matched assets.
        Each hit has _source.core.identity, _source.core.name, _source.core.classType.
    """
    s = get_session()
    resp = requests.post(
        f"{s.cdgc_api_url}/ccgf-searchv2/api/v1/search",
        json=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {s.get_jwt()}",
            "X-INFA-SEARCH-LANGUAGE": "elasticsearch",
            "Cookie": f"USER_SESSION={s.session_id}",
        },
        timeout=60,
    )
    return _r(resp)


# ===========================================================================
# DATA PROFILING APIs
# Base URL derived from login: https://{pod}-dqprofile.dm-{region}.informaticacloud.com
# ===========================================================================

@mcp.tool()
def list_profiles(
    project_name: Optional[str] = None,
    folder_name: Optional[str] = None,
    name: Optional[str] = None,
) -> dict:
    """List data profiles in the org.

    Args:
        project_name: Filter by FRS project name.
        folder_name: Filter by FRS folder name.
        name: Filter by profile name (exact match).

    Returns:
        List of profiles with IDs, names, connection info, and sampling options.
    """
    s = get_session()
    params = {}
    if project_name:
        params["frsProjectName"] = project_name
    if folder_name:
        params["frsFolderName"] = folder_name
    if name:
        params["name"] = name
        params["exactMatch"] = "true"

    resp = requests.get(
        f"{s.profiling_url}/profiling-service/api/v1/profile",
        params=params,
        headers=s.profiling_headers(),
        timeout=30,
    )
    return _r(resp)


@mcp.tool()
def get_profile(profile_id: str) -> dict:
    """Get the full definition of a data profile by ID.

    Args:
        profile_id: Profile UUID (from list_profiles).

    Returns:
        Full profile definition including source, fields, sampling options, and runtime config.
    """
    s = get_session()
    resp = requests.get(
        f"{s.profiling_url}/profiling-service/api/v1/profile/{profile_id}",
        headers=s.profiling_headers(),
        timeout=30,
    )
    return _r(resp)


@mcp.tool()
def run_profile(profile_id: str) -> dict:
    """Execute a data profile run.

    Args:
        profile_id: Profile UUID (from list_profiles).

    Returns:
        Dict with profileRunId and profileJobId — use get_profile_job_status to track progress.
    """
    s = get_session()
    resp = requests.post(
        f"{s.profiling_url}/profiling-service/api/v1/profile/{profile_id}/execute",
        headers=s.profiling_headers(),
        timeout=30,
    )
    return _r(resp)


@mcp.tool()
def get_profile_job_status(job_id: str) -> dict:
    """Get the status and details of a profiling job.

    Args:
        job_id: Job ID returned by run_profile (profileJobId).

    Returns:
        Job status (COMPLETED, RUNNING, FAILED), start/end times, and step details.
    """
    s = get_session()
    resp = requests.get(
        f"{s.profiling_url}/profiling-service/api/v1/job/{job_id}",
        headers=s.profiling_headers(),
        timeout=30,
    )
    return _r(resp)


@mcp.tool()
def list_profile_runs(
    limit: int = 10,
) -> dict:
    """List recent profile run details across all profiles.

    Args:
        limit: Number of runs to return (default 10).

    Returns:
        List of recent profile runs with IDs, status, and timing.
    """
    s = get_session()
    resp = requests.get(
        f"{s.profiling_url}/profiling-service/api/v1/runDetail/topNrun",
        params={"limit": limit},
        headers=s.profiling_headers(),
        timeout=30,
    )
    return _r(resp)


@mcp.tool()
def get_profile_columns(profile_id: str) -> dict:
    """List all profiled columns in a profile with their summary statistics.

    Args:
        profile_id: Profile UUID (from list_profiles).

    Returns:
        List of columns with null %, distinct count, min/max values, and data type info.
    """
    s = get_session()
    resp = requests.get(
        f"{s.profiling_url}/metric-store/api/v1/odata/Profiles('{profile_id}')/Columns",
        headers=s.profiling_headers(),
        timeout=30,
    )
    return _r(resp)


@mcp.tool()
def get_column_profile(
    profile_id: str,
    column_id: str,
    include_patterns: bool = False,
    include_value_frequencies: bool = False,
    include_data_types: bool = False,
) -> dict:
    """Get detailed profiling results for a specific column.

    Args:
        profile_id: Profile UUID (from list_profiles).
        column_id: Column key/ID (from get_profile_columns).
        include_patterns: Also fetch inferred patterns (regex-like).
        include_value_frequencies: Also fetch value frequency distribution.
        include_data_types: Also fetch inferred data types.

    Returns:
        Column statistics and optionally patterns, value frequencies, or data types.
    """
    s = get_session()
    base = f"{s.profiling_url}/metric-store/api/v1/odata/Profiles('{profile_id}')/Columns('{column_id}')"

    result: dict = {}

    resp = requests.get(base, headers=s.profiling_headers(), timeout=30)
    result["column"] = _r(resp)

    if include_patterns:
        resp = requests.get(f"{base}/Patterns", headers=s.profiling_headers(), timeout=30)
        result["patterns"] = _r(resp)

    if include_value_frequencies:
        resp = requests.get(f"{base}/ValueFrequencies", headers=s.profiling_headers(), timeout=30)
        result["value_frequencies"] = _r(resp)

    if include_data_types:
        resp = requests.get(f"{base}/DataTypes", headers=s.profiling_headers(), timeout=30)
        result["data_types"] = _r(resp)

    return result


@mcp.tool()
def get_profile_insights(profile_id: str) -> dict:
    """Get CLAIRE AI insights for a completed profile.

    CLAIRE insights include completeness checks, data anomalies, uniqueness,
    and other AI-generated observations about the profiled data.

    Args:
        profile_id: Profile UUID (from list_profiles).

    Returns:
        List of insights with type, score, statement, and confirmation status.
    """
    s = get_session()
    resp = requests.get(
        f"{s.profiling_url}/metric-store/api/v1/Profiles('{profile_id}')/Insights",
        headers=s.profiling_headers(),
        timeout=30,
    )
    return _r(resp)


# ===========================================================================
# CDGC — SMART SEARCH TOOLS
# These build the correct CDGC query syntax internally so the LLM doesn't
# need to know the query language. Use these before falling back to
# the raw search_assets tool.
# ===========================================================================

@mcp.tool()
def find_technical_datasets(
    resource_name: Optional[str] = None,
    name_contains: Optional[str] = None,
    classification: Optional[str] = None,
    policy: Optional[str] = None,
    size: int = 20,
) -> dict:
    """Find Technical Datasets (tables, views, files, schemas) in the catalog.

    A Technical Dataset is the CDGC generic term for any structured data container:
    Snowflake tables, Oracle views, S3 files, BigQuery datasets, etc.

    Args:
        resource_name: Filter by catalog source name (e.g. "NSEN Snowflake*", "Salesforce").
                       Supports wildcards (*).
        name_contains: Filter by dataset name containing this string.
        classification: Filter by data classification name (e.g. "Email", "SSN").
        policy: Filter by related policy name (e.g. "Personal Data", "HIPAA").
        size: Number of results to return (default 20).

    Returns:
        List of matching Technical Datasets with IDs and names.
    """
    s = get_session()

    parts = ["Technical Data Sets"]
    if classification:
        parts.append(f'related to Data Element related to Classification with Name \'{classification}\'')
    if policy:
        parts.append(f'related to Data Element related to assets related to Policy "{policy}"')
    if resource_name:
        parts.append(f'in resource "{resource_name}"')
    if name_contains:
        parts.append(f'with name *{name_contains}*')

    query = " ".join(parts) if len(parts) > 1 else "Technical Data Sets"

    resp = requests.post(
        f"{s.cdgc_api_url}/data360/search/v1/assets",
        params={"knowledgeQuery": query, "segments": "summary"},
        json={"from": 0, "size": size},
        headers=s.cdgc_headers(),
        timeout=30,
    )
    return _r(resp)


@mcp.tool()
def find_data_elements(
    resource_name: Optional[str] = None,
    dataset_name: Optional[str] = None,
    classification: Optional[str] = None,
    business_term: Optional[str] = None,
    policy: Optional[str] = None,
    curation_status: Optional[str] = None,
    critical_only: bool = False,
    size: int = 20,
) -> dict:
    """Find Data Elements (columns, fields) in the catalog.

    Args:
        resource_name: Filter by catalog source/resource name (e.g. "NSEN*", "Salesforce").
        dataset_name: Filter by parent table/dataset name.
        classification: Filter by classification name (e.g. "Email", "Birth date").
        business_term: Filter by related business term name.
        policy: Filter by related policy name.
        curation_status: Filter by curation status — one of:
                         AUTO_ACCEPTED, ACCEPTED, REJECTED, NONE.
        critical_only: If True, only return elements linked to Critical Data Elements.
        size: Number of results to return (default 20).

    Returns:
        List of matching Data Elements with IDs, names, and parent info.
    """
    s = get_session()

    if critical_only:
        base = "Data Elements related to (business terms which are critical data element)"
    else:
        base = "Data Elements"

    parts = [base]

    if classification:
        parts.append(f'related to Classification with Name \'{classification}\'')
    if business_term:
        parts.append(f'related to Business Term "{business_term}"')
    if policy:
        parts.append(f'related to assets related to Policy "{policy}"')
    if curation_status:
        parts.append(f'related with curation status {curation_status} to data classification')
    if resource_name:
        parts.append(f'in resource "{resource_name}"')
    if dataset_name:
        parts.append(f'related to technical dataset "{dataset_name}"')

    query = " ".join(parts)

    resp = requests.post(
        f"{s.cdgc_api_url}/data360/search/v1/assets",
        params={"knowledgeQuery": query, "segments": "summary"},
        json={"from": 0, "size": size},
        headers=s.cdgc_headers(),
        timeout=30,
    )
    return _r(resp)


@mcp.tool()
def find_glossary_terms(
    name_contains: Optional[str] = None,
    domain: Optional[str] = None,
    policy: Optional[str] = None,
    critical_only: bool = False,
    certified_only: bool = False,
    size: int = 20,
) -> dict:
    """Find Business Glossary Terms (Business Terms, Domains, Metrics, Policies, etc.).

    Args:
        name_contains: Filter by term name containing this string.
        domain: Filter by parent domain name.
        policy: Filter by related policy name.
        critical_only: If True, only return terms flagged as Critical Data Elements.
        certified_only: If True, only return certified terms.
        size: Number of results to return (default 20).

    Returns:
        List of matching glossary assets with IDs, names, and descriptions.
    """
    s = get_session()

    if critical_only:
        base = "business terms which are critical data element"
    else:
        base = "Glossary"

    parts = [base]

    if certified_only:
        parts = ["all which are certified"]
        if critical_only:
            parts = ["business terms which are critical data element and certified"]

    if policy:
        parts.append(f'related to policies "{policy}"')
    if domain:
        parts.append(f'in domain "{domain}"')
    if name_contains:
        parts.append(f'with name *{name_contains}*')

    query = " ".join(parts)

    resp = requests.post(
        f"{s.cdgc_api_url}/data360/search/v1/assets",
        params={"knowledgeQuery": query, "segments": "summary"},
        json={"from": 0, "size": size},
        headers=s.cdgc_headers(),
        timeout=30,
    )
    return _r(resp)


@mcp.tool()
def find_dq_rules(
    resource_name: Optional[str] = None,
    dataset_name: Optional[str] = None,
    business_term: Optional[str] = None,
    policy: Optional[str] = None,
    unacceptable_only: bool = False,
    size: int = 20,
) -> dict:
    """Find Data Quality Rules and Rule Occurrences in the catalog.

    Args:
        resource_name: Filter rules for data elements in this resource.
        dataset_name: Filter rules for data elements in this table/dataset.
        business_term: Filter rules related to this business term.
        policy: Filter rules related to this policy.
        unacceptable_only: If True, only return rules with unacceptable DQ scores.
        size: Number of results to return (default 20).

    Returns:
        List of matching DQ rules with IDs, names, and scores.
    """
    s = get_session()

    if unacceptable_only:
        base = "(data element related to business terms which are critical data element) related to data quality rule occurrence with threshold result \"not acceptable\""
    else:
        base = "dq rule"

    parts = [base]

    if business_term:
        parts.append(f'related to Data elements related to Business Term "{business_term}"')
    elif resource_name:
        parts.append(f'related to Data elements related to tables in resource "{resource_name}"')
    elif dataset_name:
        parts.append(f'related to Data elements related to (table {dataset_name})')
    if policy:
        parts.append(f'related to Data Element related to assets related to Policy "{policy}"')

    query = " ".join(parts)

    resp = requests.post(
        f"{s.cdgc_api_url}/data360/search/v1/assets",
        params={"knowledgeQuery": query, "segments": "summary"},
        json={"from": 0, "size": size},
        headers=s.cdgc_headers(),
        timeout=30,
    )
    return _r(resp)


@mcp.tool()
def find_catalog_sources_by_type(
    source_type: Optional[str] = None,
    name_contains: Optional[str] = None,
    size: int = 25,
) -> dict:
    """Find catalog sources, optionally filtered by technology type or name.

    Args:
        source_type: Technology type filter (e.g. "Snowflake", "Oracle", "Databricks",
                     "Amazon S3", "Azure Data Factory", "BigQuery", "PowerBI").
        name_contains: Filter by source name containing this string.
        size: Number of results to return (default 25).

    Returns:
        List of matching catalog sources with IDs, names, and types.
    """
    s = get_session()

    params: dict = {
        "offset": 0,
        "limit": size,
        "sort": "name:ASC",
        "custom": "false",
    }
    if source_type:
        params["filter"] = f"type:EQ:{source_type}"
    if name_contains:
        params["filter"] = f"name:LIKE:{name_contains}"

    resp = requests.get(
        f"{s.cdgc_api_url}/data360/catalog-source-management/v1/catalogsources",
        params=params,
        headers=s.cdgc_headers(),
        timeout=30,
    )
    return _r(resp)


# ===========================================================================
# Resources
# ===========================================================================

@mcp.resource("examples://cdgc-es-queries")
def cdgc_es_query_examples() -> str:
    """Elasticsearch query examples for the internal_search tool.

    Covers: bulk fetch by ID, CDEs, DQ rule occurrences, Business Terms,
    Policies, Classifications, relationship traversal, lineage, Databricks,
    Power BI, Tableau, Marketplace, and a complete classType reference.
    """
    path = os.path.join(os.path.dirname(__file__), "es_query_examples.md")
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


@mcp.resource("examples://cdgc-search-queries")
def cdgc_search_query_examples() -> str:
    """Example CDGC search queries organized by category.

    Covers: catalog source discovery, data elements, CDEs, tables, policies,
    DQ rules, DQ occurrences, classification, sensitivity, stakeholders,
    profiling, certification, lineage, ROPA, and dashboard queries.
    """
    examples_path = os.path.join(os.path.dirname(__file__), "query_examples.md")
    with open(examples_path, "r", encoding="utf-8") as f:
        return f.read()


# ===========================================================================
# Entry point
# ===========================================================================

if __name__ == "__main__":
    mcp.run()
