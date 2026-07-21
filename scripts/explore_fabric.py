"""
Temporary exploration script — dumps the distinct data_item and investment
(company) rosters from Fabric's periodic_data table to local CSVs so the
Fabric -> bronze column/company mapping can be reviewed and confirmed.

Not part of the production load pipeline. Delete or fold into the real
loader once the mapping is settled.
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


def dump_query(cursor, sql, out_filename):
    cursor.execute(sql)
    columns = [col[0] for col in cursor.description]
    rows = cursor.fetchall()

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    out_path = os.path.join(OUTPUT_DIR, out_filename)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(columns)
        writer.writerows(rows)

    print(f"{out_filename}: {len(rows)} rows -> {out_path}")


def main():
    conn = get_connection()
    cursor = conn.cursor()

    dump_query(
        cursor,
        """
        SELECT DISTINCT
            periodic_data_data_item,
            periodic_data_data_item_id,
            periodic_data_data_item_type
        FROM production.base_ilevel__periodic_data
        WHERE periodic_data_scenario = 'Actual'
        ORDER BY periodic_data_data_item
        """,
        "data_items.csv",
    )

    dump_query(
        cursor,
        """
        SELECT DISTINCT
            periodic_data_investment,
            periodic_data_investment_id
        FROM production.base_ilevel__periodic_data
        WHERE periodic_data_scenario = 'Actual'
        ORDER BY periodic_data_investment
        """,
        "investments.csv",
    )

    conn.close()


if __name__ == "__main__":
    main()
