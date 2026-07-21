"""
Temporary exploration script — lists all tables/views in the Fabric warehouse
whose names suggest a data-item dimension/category/template table, so we can
check for an authoritative financial-statement-item categorization instead of
relying on keyword matching against base_ilevel__periodic_data.
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


TARGET_TABLES = [
    "base_ilevel__data_items",
    "base_ilevel__data_item_relationships",
    "dim__data_items",
    "dim__calculated_data_items",
]


def dump_columns(cursor, table_name):
    cursor.execute(
        """
        SELECT COLUMN_NAME, DATA_TYPE
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = 'production' AND TABLE_NAME = ?
        ORDER BY ORDINAL_POSITION
        """,
        table_name,
    )
    rows = cursor.fetchall()
    print(f"\n--- production.{table_name} columns ---")
    for col, dtype in rows:
        print(f"  {col} ({dtype})")
    return [r[0] for r in rows]


def dump_sample(cursor, table_name, columns):
    cursor.execute(f"SELECT TOP 5 * FROM production.{table_name}")
    rows = cursor.fetchall()
    out_path = os.path.join(OUTPUT_DIR, f"sample_{table_name}.csv")
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(columns)
        writer.writerows(rows)
    print(f"  sample -> {out_path} ({len(rows)} rows)")


CONFIRMED_IDS = [
    10717, 10001, 11679, 11680, 11682, 10059, 11705, 10004, 10012, 12190, 10014,
    11683, 12212, 10722, 10016, 10017, 10269, 10018, 10020, 11684, 10270, 10271,
    10023, 10025, 11686, 11687, 10028, 10030, 10031, 10730, 12179, 10032, 12192,
    10728, 10727, 12191, 12194, 11689, 10040, 10041, 12193, 11690, 10047, 10048,
    10049, 10292,
]


def dump_categories(cursor):
    cursor.execute(
        """
        SELECT DISTINCT data_item_category
        FROM production.base_ilevel__data_items
        ORDER BY data_item_category
        """
    )
    rows = cursor.fetchall()
    print("\n--- distinct data_item_category values ---")
    for (cat,) in rows:
        print(f"  {cat}")


def dump_confirmed_item_attributes(cursor):
    placeholders = ",".join(str(i) for i in CONFIRMED_IDS)
    cursor.execute(
        f"""
        SELECT data_item_id, data_item_name, data_item_category,
               is_carry_over, is_carry_backward, data_item_last_modified_date
        FROM production.base_ilevel__data_items
        WHERE data_item_id IN ({placeholders})
        ORDER BY data_item_name
        """
    )
    rows = cursor.fetchall()
    columns = ["data_item_id", "data_item_name", "data_item_category",
               "is_carry_over", "is_carry_backward", "data_item_last_modified_date"]
    out_path = os.path.join(OUTPUT_DIR, "confirmed_items_attributes.csv")
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(columns)
        writer.writerows(rows)
    print(f"\nconfirmed_items_attributes.csv: {len(rows)} rows -> {out_path}")


def dump_financial_statement_items(cursor):
    cursor.execute(
        """
        SELECT data_item_id, data_item_name, data_item_category,
               is_carry_over, is_carry_backward, data_item_last_modified_date
        FROM production.base_ilevel__data_items
        WHERE data_item_category IN ('Income Statement', 'Balance Sheet', 'Cash Flow')
        ORDER BY data_item_category, data_item_name
        """
    )
    rows = cursor.fetchall()
    columns = ["data_item_id", "data_item_name", "data_item_category",
               "is_carry_over", "is_carry_backward", "data_item_last_modified_date"]
    out_path = os.path.join(OUTPUT_DIR, "financial_statement_items_all.csv")
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(columns)
        writer.writerows(rows)
    print(f"\nfinancial_statement_items_all.csv: {len(rows)} rows -> {out_path}")


def main():
    conn = get_connection()
    cursor = conn.cursor()
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    for table_name in TARGET_TABLES:
        try:
            columns = dump_columns(cursor, table_name)
            if columns:
                dump_sample(cursor, table_name, columns)
        except Exception as e:
            print(f"  ERROR on {table_name}: {e}")

    dump_categories(cursor)
    dump_confirmed_item_attributes(cursor)
    dump_financial_statement_items(cursor)

    conn.close()


if __name__ == "__main__":
    main()
