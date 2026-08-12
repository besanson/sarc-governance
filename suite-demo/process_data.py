#!/usr/bin/env python3
# Copyright 2026 SARC Suite Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Process UCI Online Retail data for SARC Suite demo."""
import csv
import hashlib
from pathlib import Path
from datetime import datetime
from collections import defaultdict

input_file = Path("data/online-retail-full.csv")
output_file = Path("data/open_retail_daily.csv")

# Read and filter data
data_by_key = defaultdict()  # (sku, date) -> (qty_sum, prices=[])

with open(input_file) as f:
    reader = csv.DictReader(f)
    for row in reader:
        # Keep only UK rows
        if row.get("Country", "").strip() != "United Kingdom":
            continue

        try:
            qty = float(row.get("Quantity", 0))
            price = float(row.get("UnitPrice", 0))
        except (ValueError, TypeError):
            continue

        # Keep only positive quantity and price
        if qty <= 0 or price <= 0:
            continue

        sku = row.get("StockCode", "").strip()
        invoice_date = row.get("InvoiceDate", "").strip()

        if not sku or not invoice_date:
            continue

        # Parse date (format: MM/DD/YYYY HH:MM)
        try:
            date_obj = datetime.strptime(invoice_date.split()[0], "%m/%d/%Y")
            date_str = date_obj.strftime("%Y-%m-%d")
        except ValueError:
            continue

        key = (sku, date_str)
        if key not in data_by_key:
            data_by_key[key] = (0, [])

        qty_sum, prices = data_by_key[key]
        data_by_key[key] = (qty_sum + qty, prices + [price])

# Compute median prices and filter top 40 SKUs by active days
sku_active_days = defaultdict(set)
records = []

for (sku, date), (qty_sum, prices) in data_by_key.items():
    sku_active_days[sku].add(date)
    # Compute median price
    sorted_prices = sorted(prices)
    median_price = sorted_prices[len(sorted_prices) // 2]
    records.append((sku, date, qty_sum, median_price))

# Get top 40 SKUs by number of active days
top_skus = sorted(sku_active_days.items(), key=lambda x: len(x[1]), reverse=True)[:40]
top_sku_set = {sku for sku, _ in top_skus}

# Filter records and write
output_records = [r for r in records if r[0] in top_sku_set]
output_records.sort()  # Sort by sku, then date

with open(output_file, "w", newline="") as f:
    writer = csv.writer(f)
    writer.writerow(["sku", "date", "qty", "unit_price"])
    for sku, date, qty, price in output_records:
        writer.writerow([sku, date, qty, price])

# Compute SHA256
with open(output_file, "rb") as f:
    sha256 = hashlib.sha256(f.read()).hexdigest()

print(f"✓ Derived {len(output_records)} records from {len(data_by_key)} daily aggregates")
print(f"✓ Kept top 40 SKUs ({len(top_sku_set)} actually present)")
print(f"✓ SHA256: {sha256}")

# Write PROVENANCE.md
provenance_text = f"""# Data Provenance

## Source
UCI Online Retail (CC BY 4.0)

Citation: Chen, D. (2015). Online Retail [Dataset]. UCI Machine Learning Repository. doi 10.24432/C5BW33.

Mirror URL: https://raw.githubusercontent.com/databricks/Spark-The-Definitive-Guide/master/data/retail-data/all/online-retail-dataset.csv

## Derivation
- Filtered to United Kingdom rows only
- Kept Quantity > 0 and UnitPrice > 0
- Aggregated per (StockCode, date): quantity summed, unit_price = daily median
- Kept top 40 SKUs by number of active days
- Output columns: sku, date, qty, unit_price

## Derived File Hash
SHA256: {sha256}

## Economics Constants (Simulation Knobs)
- Sell price = SKU median observed price
- True unit cost = 0.6 x sell price
- Newsvendor order = trailing-28-day demand quantile at critical ratio (price - cost) / price
- WARMUP = 35 days
- Per-class injection probability = 0.02
- SEED = 26313
"""

with open(Path("data/PROVENANCE.md"), "w") as f:
    f.write(provenance_text)

print(f"✓ Wrote data/PROVENANCE.md")
