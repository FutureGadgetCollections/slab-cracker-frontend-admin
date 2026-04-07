#!/usr/bin/env python3
"""
Local MCP server for slab-cracker.
Provides read-only tools for BigQuery and GCS in the fg-tcglabs project.

Requires Application Default Credentials:
  gcloud auth application-default login
"""

import json
from mcp.server.fastmcp import FastMCP

PROJECT_ID = "fg-tcglabs"
REGION = "us-central1"
SCANS_BUCKET = "slab-cracker-scans"

mcp = FastMCP("gcp-slab-cracker")

# ── Client singletons ─────────────────────────────────────────────────────────

_bq_client = None
_gcs_client = None


def _bq():
    global _bq_client
    if _bq_client is None:
        from google.cloud import bigquery
        _bq_client = bigquery.Client(project=PROJECT_ID)
    return _bq_client


def _gcs():
    global _gcs_client
    if _gcs_client is None:
        from google.cloud import storage
        _gcs_client = storage.Client(project=PROJECT_ID)
    return _gcs_client


# ── BigQuery ──────────────────────────────────────────────────────────────────

@mcp.tool()
def bq_list_datasets() -> str:
    """List all BigQuery datasets in the fg-tcglabs project."""
    client = _bq()
    datasets = list(client.list_datasets())
    return json.dumps([
        {"dataset_id": d.dataset_id, "location": d.location}
        for d in datasets
    ])


@mcp.tool()
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
def bq_query(sql: str, max_rows: int = 200) -> str:
    """
    Execute a read-only SQL query against BigQuery (SELECT only).
    Project is fg-tcglabs. Use fully-qualified names like `grading.cert_scans`
    or cross-project: `future-gadget-labs-483502.catalog.single_cards`.
    Capped at 100 MB scanned.
    """
    blocked = {"INSERT", "UPDATE", "DELETE", "DROP", "CREATE", "ALTER", "TRUNCATE", "MERGE"}
    upper = sql.upper()
    for kw in blocked:
        if kw in upper:
            return json.dumps({"error": f"Keyword '{kw}' is not allowed — SELECT only."})

    from google.cloud import bigquery
    client = _bq()
    job_config = bigquery.QueryJobConfig(maximum_bytes_billed=100 * 1024 * 1024)
    try:
        job = client.query(sql, job_config=job_config)
        results = job.result()
        rows = []
        for i, row in enumerate(results):
            if i >= max_rows:
                break
            rows.append(dict(row))
        total = results.total_rows if results.total_rows is not None else len(rows)
        return json.dumps(
            {
                "rows": rows,
                "returned": len(rows),
                "total_rows": total,
                "truncated": len(rows) < total,
            },
            default=str,
        )
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def bq_sample(dataset_id: str, table_id: str, limit: int = 20) -> str:
    """Return a sample of rows from a BigQuery table."""
    sql = f"SELECT * FROM `{PROJECT_ID}.{dataset_id}.{table_id}` LIMIT {limit}"
    return bq_query(sql, max_rows=limit)


@mcp.tool()
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
def cloudrun_list_services() -> str:
    """List all Cloud Run services in the fg-tcglabs project."""
    from google.cloud import run_v2
    client = run_v2.ServicesClient(transport="rest")
    parent = f"projects/{PROJECT_ID}/locations/{REGION}"
    services = list(client.list_services(parent=parent))
    return json.dumps([
        {
            "name": s.name.split("/")[-1],
            "uri": s.uri,
            "update_time": str(s.update_time),
        }
        for s in services
    ], default=str)


@mcp.tool()
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
    )
    result = []
    for entry in entries:
        result.append({
            "timestamp": str(entry.timestamp),
            "severity": entry.severity,
            "payload": entry.payload if isinstance(entry.payload, (str, dict)) else str(entry.payload),
        })
    return json.dumps(result, default=str)


if __name__ == "__main__":
    mcp.run()
