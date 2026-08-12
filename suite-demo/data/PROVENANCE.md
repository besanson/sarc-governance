# Data Provenance

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
SHA256: 4f637bc36ba5cffb56c31cd2b8273a135f89cc65448b28929ee71e73ded8f1d9

## Economics Constants (Simulation Knobs)
- Sell price = SKU median observed price
- True unit cost = 0.6 x sell price
- Newsvendor order = trailing-28-day demand quantile at critical ratio (price - cost) / price
- WARMUP = 35 days
- Per-class injection probability = 0.02
- SEED = 26313
