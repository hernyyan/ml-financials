"""
Temporary script -- for each of the 6 "OLD DO NOT USE" financial-statement
data items, pulls row count and period_end range from Fabric, and does the
same for their confirmed replacement item (where one exists), so we can see
the handoff gap/overlap between retired and current ids.
"""
import csv
import os
import struct

import pyodbc
from azure.identity import ClientSecretCredential
from dotenv import load_dotenv

load_dotenv()

FABRIC_SCOPE = "https://database.windows.net/.default"
SQL_COPT_SS_ACCESS_TOKEN = 1256
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "exploration")

OLD_ITEMS = [
    (10729, "Long Term Mortgages - OLD DO NOT USE", None, None),
    (10036, "Other Non-Current Liabilities - OLD DO NOT USE", 12191, "Other Non-Current Liabilities"),
    (10724, "Short Term Capitalized Leases - OLD DO NOT USE", None, None),
    (10725, "Short Term Mortgages - OLD DO NOT USE", None, None),
    (10033, "Total Current Liabilities - OLD DO NOT USE", 12192, "Total Current Liabilities"),
    (10063, "Total Non-Current Liabilities - OLD DO NOT USE", 12194, "Total Non-Current Liabilities"),
]


def get_connection():
    credential = ClientSecretCredential(
        tenant_id=os.environ["FABRIC_TENANT_ID"],
        client_id=os.environ["FABRIC_CLIENT_ID"],
        client_secret=os.environ["FABRIC_CLIENT_SECRET"],
    )
    token = credential.get_token(FABRIC_SCOPE).token
    token_bytes = token.encode("utf-16-le")
    token_struct = struct.pack(f"<I{len(token_bytes)}s", len(token_bytes), token_bytes)
    conn_str = (
        "Driver={ODBC Driver 18 for SQL Server};"
        f"Server={os.environ['FABRIC_SQL_ENDPOINT']},1433;"
        f"Database={os.environ['FABRIC_DATABASE']};"
        "Encrypt=yes;"
        "TrustServerCertificate=no;"
        "Connection Timeout=30;"
    )
    return pyodbc.connect(conn_str, attrs_before={SQL_COPT_SS_ACCESS_TOKEN: token_struct})


def stats_for_item(cursor, item_id):
    cursor.execute(
        """
        SELECT COUNT(*), MIN(periodic_data_period_end), MAX(periodic_data_period_end),
               COUNT(DISTINCT periodic_data_investment_id)
        FROM production.base_ilevel__periodic_data
        WHERE periodic_data_data_item_id = ? AND periodic_data_scenario = 'Actual'
        """,
        item_id,
    )
    count, min_period, max_period, distinct_companies = cursor.fetchone()
    return count, min_period, max_period, distinct_companies


def main():
    conn = get_connection()
    cursor = conn.cursor()

    rows = []
    for old_id, old_name, repl_id, repl_name in OLD_ITEMS:
        old_count, old_min, old_max, old_companies = stats_for_item(cursor, old_id)

        if repl_id:
            repl_count, repl_min, repl_max, repl_companies = stats_for_item(cursor, repl_id)
        else:
            repl_count, repl_min, repl_max, repl_companies = None, None, None, None

        rows.append([
            old_id, old_name, old_count, old_companies, old_min, old_max,
            repl_id if repl_id else "(none found)",
            repl_name if repl_name else "",
            repl_count, repl_companies, repl_min,
        ])
        print(f"{old_name} ({old_id}): {old_count} rows, {old_companies} companies, {old_min} -> {old_max}")
        if repl_id:
            print(f"  replacement {repl_name} ({repl_id}): {repl_count} rows, {repl_companies} companies, earliest {repl_min}")

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    out_path = os.path.join(OUTPUT_DIR, "old_items_investigation.csv")
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "old_item_id", "old_item_name", "old_row_count", "old_distinct_companies",
            "old_earliest_period_end", "old_latest_period_end",
            "replacement_item_id", "replacement_item_name",
            "replacement_row_count", "replacement_distinct_companies", "replacement_earliest_period_end",
        ])
        writer.writerows(rows)
    print(f"\nSaved: {out_path}")

    conn.close()


if __name__ == "__main__":
    main()
