"""
Temporary exploration script -- hits the live iLEVEL API to see what current
data_items, scenarios, and periodicData actually look like (fields, shape,
current vs. Fabric warehouse), so we can build a Fabric -> iLEVEL migration
mapping spreadsheet grounded in real responses instead of the Postman docs.
"""
import csv
import json
import os

import requests
from dotenv import load_dotenv

load_dotenv()

BASE_URL = os.environ["ILEVEL_API_BASE_URL"]
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "exploration")


def get_token():
    resp = requests.post(
        f"{BASE_URL}/token",
        auth=(os.environ["ILEVEL_CLIENT_ID"], os.environ["ILEVEL_CLIENT_SECRET"]),
        data={"grant_type": "client_credentials"},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def get(session, path, params=None):
    resp = session.get(f"{BASE_URL}{path}", params=params, timeout=60)
    resp.raise_for_status()
    return resp.json()


def dump_json_rows(rows, out_name, columns):
    out_path = os.path.join(OUTPUT_DIR, out_name)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(columns)
        writer.writerows(rows)
    print(f"{out_name}: {len(rows)} rows -> {out_path}")


def dump_raw(obj, out_name):
    out_path = os.path.join(OUTPUT_DIR, out_name)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)
    print(f"raw sample -> {out_path}")


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    token = get_token()
    session = requests.Session()
    session.headers.update({"Authorization": f"Bearer {token}"})

    # 1. Raw shape of a single dataItems page -- print so we can see the full
    #    JSON:API envelope (attributes available, id format, etc.) before parsing.
    raw = get(session, "/dataItems", {"page[size]": 5})
    dump_raw(raw, "raw_data_items_sample.json")

    # 2. Full current data item list -- this is the authoritative "current only"
    #    universe iLEVEL exposes (no retired/OLD DO NOT USE items expected).
    all_items = []
    page = 1
    while True:
        body = get(session, "/dataItems", {"page[number]": page, "page[size]": 100})
        data = body.get("data", [])
        if not data:
            break
        for d in data:
            attrs = d.get("attributes", {})
            all_items.append([d.get("id"), attrs.get("name"), attrs.get("category"), attrs.get("formatType")])
        if len(data) < 100:
            break
        page += 1
    dump_json_rows(all_items, "ilevel_data_items.csv", ["id", "name", "category", "formatType"])

    # 3. Scenarios -- confirm exact label/id for "Actual".
    raw_scenarios = get(session, "/scenarios")
    dump_raw(raw_scenarios, "raw_scenarios.json")

    # 4. periodicData sample -- see the actual value/dataItem/investment/currency shape.
    raw_periodic = get(session, "/periodicData", {"page[size]": 5})
    dump_raw(raw_periodic, "raw_periodic_data_sample.json")

    # 5. assets sample -- see investment id/name shape.
    raw_assets = get(session, "/entities/assets", {"page[size]": 5})
    dump_raw(raw_assets, "raw_assets_sample.json")


if __name__ == "__main__":
    main()
