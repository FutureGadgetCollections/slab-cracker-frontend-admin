#!/usr/bin/env python3
"""
Local MCP server for slab-cracker.
Provides read-only tools for BigQuery and GCS in the fg-tcglabs project.

Requires Application Default Credentials:
  gcloud auth application-default login
"""

import json
import os
import functools
import threading
import traceback

# Eager top-level imports so we pay the ~2s google.cloud import cost at server
# startup instead of on the first tool call the user makes.
from google.cloud import bigquery, storage

from mcp.server.fastmcp import FastMCP

PROJECT_ID = "fg-tcglabs"
REGION = "us-central1"
SCANS_BUCKET = "slab-cracker-scans"

# Hard upper bounds so a hung upstream call can't lock up the MCP session.
HTTP_TIMEOUT_SECONDS = 30
BQ_TIMEOUT_SECONDS = 45

mcp = FastMCP("gcp-slab-cracker")


def safe_tool(fn):
    """Wrap a tool so any exception returns a JSON error instead of hanging
    the MCP client or surfacing a raw stack trace."""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            return json.dumps({
                "error": f"{type(e).__name__}: {e}",
                "tool": fn.__name__,
                "traceback": traceback.format_exc(limit=3),
            })

    return wrapper


# ── Client singletons ─────────────────────────────────────────────────────────

_bq_client = None
_gcs_client = None
_anthropic_client = None
_anthropic_api_key_cached = None


def _anthropic_api_key():
    global _anthropic_api_key_cached
    if _anthropic_api_key_cached:
        return _anthropic_api_key_cached
    key = os.environ.get("ANTHROPIC_API_KEY")
    if key:
        _anthropic_api_key_cached = key
        return key
    # Fall back to Secret Manager so the server works even when launched
    # from an MCP host (e.g., Claude Code) that doesn't inherit the shell env.
    from google.cloud import secretmanager
    sm = secretmanager.SecretManagerServiceClient()
    name = f"projects/{PROJECT_ID}/secrets/anthropic-api-key/versions/latest"
    resp = sm.access_secret_version(request={"name": name})
    _anthropic_api_key_cached = resp.payload.data.decode("utf-8")
    return _anthropic_api_key_cached


def _anthropic():
    global _anthropic_client
    if _anthropic_client is None:
        import anthropic
        _anthropic_client = anthropic.Anthropic(
            api_key=_anthropic_api_key(),
            timeout=HTTP_TIMEOUT_SECONDS,
            max_retries=1,
        )
    return _anthropic_client


def _bq():
    global _bq_client
    if _bq_client is None:
        _bq_client = bigquery.Client(project=PROJECT_ID)
    return _bq_client


def _gcs():
    global _gcs_client
    if _gcs_client is None:
        _gcs_client = storage.Client(project=PROJECT_ID)
    return _gcs_client


def _warm_clients():
    # Fire-and-forget: pre-instantiates BQ + GCS clients so the first tool
    # call doesn't pay the ~1-2s ADC token exchange / HTTP pool setup cost.
    try:
        _bq()
        _gcs()
    except Exception:
        pass  # clients will retry lazily on first real use


# ── BigQuery ──────────────────────────────────────────────────────────────────

@mcp.tool()
@safe_tool
def bq_list_datasets() -> str:
    """List all BigQuery datasets in the fg-tcglabs project."""
    client = _bq()
    datasets = list(client.list_datasets())
    return json.dumps([
        {"dataset_id": d.dataset_id, "location": d.location}
        for d in datasets
    ])


@mcp.tool()
@safe_tool
def bq_list_tables(dataset_id: str) -> str:
    """List all tables in a BigQuery dataset."""
    client = _bq()
    tables = list(client.list_tables(dataset_id))
    return json.dumps([
        {
            "table_id": t.table_id,
            "table_type": t.table_type,
            "full_id": f"{PROJECT_ID}.{dataset_id}.{t.table_id}",
        }
        for t in tables
    ])


@mcp.tool()
@safe_tool
def bq_describe_table(dataset_id: str, table_id: str) -> str:
    """Get schema, row count, and metadata for a BigQuery table."""
    client = _bq()
    table = client.get_table(f"{PROJECT_ID}.{dataset_id}.{table_id}")
    schema = [
        {
            "name": f.name,
            "type": f.field_type,
            "mode": f.mode,
            "description": f.description,
        }
        for f in table.schema
    ]
    return json.dumps(
        {
            "full_id": f"{PROJECT_ID}.{dataset_id}.{table_id}",
            "num_rows": table.num_rows,
            "num_bytes": table.num_bytes,
            "created": str(table.created),
            "modified": str(table.modified),
            "description": table.description,
            "schema": schema,
        },
        default=str,
    )


@mcp.tool()
@safe_tool
def bq_query(sql: str, max_rows: int = 200, timeout_seconds: int = BQ_TIMEOUT_SECONDS) -> str:
    """
    Execute a read-only SQL query against BigQuery (SELECT only).
    Project is fg-tcglabs. Use fully-qualified names like `grading.cert_scans`
    or cross-project: `future-gadget-labs-483502.catalog.single_cards`.
    Capped at 100 MB scanned. Default timeout 45s; pass larger `timeout_seconds`
    for heavy queries. On timeout the BQ job is cancelled and `job_id` is
    returned so you can inspect it in the BQ console.
    """
    blocked = {"INSERT", "UPDATE", "DELETE", "DROP", "CREATE", "ALTER", "TRUNCATE", "MERGE"}
    upper = sql.upper()
    for kw in blocked:
        if kw in upper:
            return json.dumps({"error": f"Keyword '{kw}' is not allowed — SELECT only."})

    from google.cloud import bigquery
    client = _bq()
    job_config = bigquery.QueryJobConfig(
        maximum_bytes_billed=100 * 1024 * 1024,
        use_query_cache=True,  # cheap and fast on repeated exploratory queries
    )

    # Submit. This is a quick metadata call; the job runs server-side.
    try:
        job = client.query(sql, job_config=job_config, timeout=HTTP_TIMEOUT_SECONDS)
    except Exception as e:
        return json.dumps({
            "error": f"Query submission failed: {type(e).__name__}: {e}",
            "hint": "Check auth (gcloud auth application-default login) or SQL syntax.",
        })

    job_id = job.job_id
    job_location = job.location

    # Wait for completion with a hard deadline. On timeout, cancel the job so
    # it doesn't keep burning bytes after the MCP client has given up.
    try:
        results = job.result(timeout=timeout_seconds)
    except Exception as e:
        try:
            client.cancel_job(job_id, location=job_location)
        except Exception:
            pass  # best-effort — job may have finished or never started
        return json.dumps({
            "error": f"Query timed out after {timeout_seconds}s ({type(e).__name__}: {e})",
            "job_id": job_id,
            "location": job_location,
            "hint": "Narrow the query (tighter WHERE, add LIMIT), or retry with a larger timeout_seconds.",
        })

    rows = []
    try:
        for i, row in enumerate(results):
            if i >= max_rows:
                break
            rows.append(dict(row))
    except Exception as e:
        return json.dumps({
            "error": f"Result iteration failed: {type(e).__name__}: {e}",
            "job_id": job_id,
            "partial_rows": len(rows),
        })

    total = results.total_rows if results.total_rows is not None else len(rows)
    bytes_processed = getattr(job, "total_bytes_processed", None)
    return json.dumps(
        {
            "rows": rows,
            "returned": len(rows),
            "total_rows": total,
            "truncated": len(rows) < total,
            "job_id": job_id,
            "bytes_processed": bytes_processed,
            "cache_hit": getattr(job, "cache_hit", None),
        },
        default=str,
    )


@mcp.tool()
@safe_tool
def bq_sample(dataset_id: str, table_id: str, limit: int = 20) -> str:
    """Return a sample of rows from a BigQuery table."""
    sql = f"SELECT * FROM `{PROJECT_ID}.{dataset_id}.{table_id}` LIMIT {limit}"
    return bq_query(sql, max_rows=limit)


@mcp.tool()
@safe_tool
def cert_scans_summary() -> str:
    """
    Get a summary of all cataloged cert scans grouped by game, set_code, and role.
    Shows counts and scan status breakdown.
    """
    sql = f"""
        SELECT game, set_code, card_number, card_name, grade, role,
               COUNT(*) as count,
               COUNTIF(scan_status = 'complete') as scans_complete,
               COUNTIF(scan_status = 'pending') as scans_pending
        FROM `{PROJECT_ID}.grading.cert_scans`
        GROUP BY game, set_code, card_number, card_name, grade, role
        ORDER BY game, set_code, card_number, grade
    """
    return bq_query(sql, max_rows=500)


@mcp.tool()
@safe_tool
def cert_scans_for_card(game: str, set_code: str, card_number: str) -> str:
    """
    Get all cert scans for a specific card identity.
    Shows all grades, roles, and scan status.
    """
    sql = f"""
        SELECT cert_number, grade, grading_company, role, scan_status,
               card_name, treatment, rarity, gcs_front_path, gcs_back_path,
               submitted_at
        FROM `{PROJECT_ID}.grading.cert_scans`
        WHERE game = '{game}' AND set_code = '{set_code}' AND card_number = '{card_number}'
        ORDER BY grade DESC, role, submitted_at
    """
    return bq_query(sql, max_rows=200)


@mcp.tool()
@safe_tool
def cross_project_card_price(game: str, set_code: str, card_number: str) -> str:
    """
    Look up a card's market price from the collection-market-tracker project.
    Joins slab-cracker cert_scans with market tracker's single_cards and prices.
    Requires cross-project BQ access to future-gadget-labs-483502.
    """
    sql = f"""
        SELECT cs.cert_number, cs.grade, cs.role, cs.card_name,
               sc.rarity, sc.treatment, sc.tcgplayer_id,
               tp.market_price, tp.avg_daily_sold, tp.listed_median, tp.date as price_date
        FROM `{PROJECT_ID}.grading.cert_scans` cs
        LEFT JOIN `future-gadget-labs-483502.catalog.single_cards` sc
          ON cs.game = sc.game AND cs.set_code = sc.set_code AND cs.card_number = sc.card_number
        LEFT JOIN `future-gadget-labs-483502.market_data.latest_tcgplayer_prices` tp
          ON sc.tcgplayer_id = tp.tcgplayer_id
        WHERE cs.game = '{game}' AND cs.set_code = '{set_code}' AND cs.card_number = '{card_number}'
        ORDER BY cs.grade DESC, cs.role
    """
    return bq_query(sql, max_rows=100)


# ── GCS ───────────────────────────────────────────────────────────────────────

@mcp.tool()
@safe_tool
def gcs_list_scans(prefix: str = "", limit: int = 50) -> str:
    """
    List scan files in the slab-cracker-scans bucket.
    prefix: optional path prefix to filter, e.g. 'pokemon/sv01/006/'
    """
    client = _gcs()
    bucket = client.bucket(SCANS_BUCKET)
    blobs = bucket.list_blobs(prefix=prefix, max_results=limit)
    return json.dumps([
        {
            "name": b.name,
            "size_bytes": b.size,
            "content_type": b.content_type,
            "updated": str(b.updated),
        }
        for b in blobs
    ], default=str)


@mcp.tool()
@safe_tool
def gcs_scan_folders(game: str = "") -> str:
    """
    List the top-level folder structure in slab-cracker-scans.
    Optionally filter by game prefix to see sets within a game.
    """
    client = _gcs()
    bucket = client.bucket(SCANS_BUCKET)
    prefix = f"{game}/" if game else ""
    iterator = bucket.list_blobs(prefix=prefix, delimiter="/")

    # Consume the iterator to populate prefixes
    _ = list(iterator)
    prefixes = list(iterator.prefixes)

    return json.dumps({"prefix": prefix, "folders": sorted(prefixes)})


# ── Cloud Run ─────────────────────────────────────────────────────────────────

@mcp.tool()
@safe_tool
def cloudrun_list_services() -> str:
    """List all Cloud Run services in the fg-tcglabs project."""
    from google.cloud import run_v2
    client = run_v2.ServicesClient(transport="rest")
    parent = f"projects/{PROJECT_ID}/locations/{REGION}"
    services = list(client.list_services(parent=parent, timeout=HTTP_TIMEOUT_SECONDS))
    return json.dumps([
        {
            "name": s.name.split("/")[-1],
            "uri": s.uri,
            "update_time": str(s.update_time),
        }
        for s in services
    ], default=str)


@mcp.tool()
@safe_tool
def cloudrun_service_logs(service_name: str, limit: int = 50) -> str:
    """
    Fetch recent logs for a Cloud Run service.
    service_name example: 'slab-cracker-api'
    """
    from google.cloud import logging as cloud_logging
    client = cloud_logging.Client(project=PROJECT_ID)
    filter_str = (
        f'resource.type="cloud_run_revision" '
        f'resource.labels.service_name="{service_name}"'
    )
    entries = client.list_entries(
        filter_=filter_str,
        max_results=limit,
        order_by=cloud_logging.DESCENDING,
        page_size=limit,
    )
    result = []
    # Guard against the iterator streaming indefinitely — stop at `limit`.
    for entry in entries:
        if len(result) >= limit:
            break
        result.append({
            "timestamp": str(entry.timestamp),
            "severity": entry.severity,
            "payload": entry.payload if isinstance(entry.payload, (str, dict)) else str(entry.payload),
        })
    return json.dumps(result, default=str)


# ── Anthropic Batch API ───────────────────────────────────────────────────────

@mcp.tool()
@safe_tool
def anthropic_list_batches(limit: int = 20) -> str:
    """
    List recent Claude Message Batch API jobs.
    Shows batch ID, processing status, request counts, and timestamps.
    Requires ANTHROPIC_API_KEY in environment.
    """
    client = _anthropic()
    batches = list(client.messages.batches.list(limit=limit))
    return json.dumps([
        {
            "id": b.id,
            "processing_status": b.processing_status,
            "request_counts": {
                "processing": b.request_counts.processing,
                "succeeded": b.request_counts.succeeded,
                "errored": b.request_counts.errored,
                "canceled": b.request_counts.canceled,
                "expired": b.request_counts.expired,
            },
            "created_at": str(b.created_at),
            "ended_at": str(b.ended_at) if b.ended_at else None,
            "expires_at": str(b.expires_at),
        }
        for b in batches
    ], default=str)


@mcp.tool()
@safe_tool
def anthropic_batch_status(batch_id: str) -> str:
    """
    Get detailed status for a specific Claude batch by ID.
    Shows processing state, request counts, and result availability.
    """
    client = _anthropic()
    b = client.messages.batches.retrieve(batch_id)
    return json.dumps({
        "id": b.id,
        "processing_status": b.processing_status,
        "request_counts": {
            "processing": b.request_counts.processing,
            "succeeded": b.request_counts.succeeded,
            "errored": b.request_counts.errored,
            "canceled": b.request_counts.canceled,
            "expired": b.request_counts.expired,
        },
        "created_at": str(b.created_at),
        "ended_at": str(b.ended_at) if b.ended_at else None,
        "expires_at": str(b.expires_at),
        "results_url": b.results_url,
    }, default=str)


@mcp.tool()
@safe_tool
def anthropic_batch_results(batch_id: str, limit: int = 10, custom_id_contains: str = "") -> str:
    """
    Fetch results from a completed Claude batch.
    Only works if batch processing_status is 'ended'.
    Returns up to `limit` results. Optionally filter by substring of custom_id.
    Response text is truncated to 2000 chars per entry to keep output manageable.
    """
    client = _anthropic()
    try:
        results_iter = client.messages.batches.results(batch_id)
    except Exception as e:
        return json.dumps({"error": f"Batch may not be ended yet: {e}"})

    results = []
    for r in results_iter:
        if custom_id_contains and custom_id_contains not in r.custom_id:
            continue
        entry = {"custom_id": r.custom_id, "result_type": r.result.type}
        if r.result.type == "succeeded":
            msg = r.result.message
            text_blocks = [b.text for b in msg.content if hasattr(b, "text")]
            combined = "\n".join(text_blocks)
            entry["response_text"] = combined[:2000]
            entry["truncated"] = len(combined) > 2000
            entry["stop_reason"] = msg.stop_reason
            entry["usage"] = {
                "input_tokens": msg.usage.input_tokens,
                "output_tokens": msg.usage.output_tokens,
            }
        elif r.result.type == "errored":
            entry["error"] = str(r.result.error)
        results.append(entry)
        if len(results) >= limit:
            break
    return json.dumps(results, default=str)


@mcp.tool()
@safe_tool
def anthropic_batch_result_for_cert(batch_id: str, cert_number: str) -> str:
    """
    Fetch the single result for a specific cert_number from a batch.
    Matches against the custom_id field containing the cert. Returns full response text.
    """
    client = _anthropic()
    try:
        results_iter = client.messages.batches.results(batch_id)
    except Exception as e:
        return json.dumps({"error": f"Batch not ready: {e}"})

    for r in results_iter:
        if cert_number in r.custom_id:
            entry = {"custom_id": r.custom_id, "result_type": r.result.type}
            if r.result.type == "succeeded":
                msg = r.result.message
                text = "\n".join(b.text for b in msg.content if hasattr(b, "text"))
                entry["response_text"] = text
                entry["stop_reason"] = msg.stop_reason
                entry["usage"] = {
                    "input_tokens": msg.usage.input_tokens,
                    "output_tokens": msg.usage.output_tokens,
                }
            elif r.result.type == "errored":
                entry["error"] = str(r.result.error)
            return json.dumps(entry, default=str)
    return json.dumps({"error": f"No result found for cert {cert_number}"})


if __name__ == "__main__":
    threading.Thread(target=_warm_clients, daemon=True).start()
    mcp.run()
