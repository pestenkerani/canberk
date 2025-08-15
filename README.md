## Hotel Logo Generator

Generates logos for hotels/hostels/apartments from a CSV list. Priority is Instagram profile photos; falls back to website logos; if neither is found, generates a text-based logo (white text on black background).

### CSV format
Columns (header required):
- property_name
- city
- district
- website (can be empty)

See `data/hotels_sample.csv` for an example.

### Setup
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### Run
```bash
python scripts/generate_logos.py --csv data/hotels_sample.csv --out output_logos --results output_logos/results.csv --delay 1.0 --limit 5
```

- `--csv`: input CSV path
- `--out`: directory to save logos
- `--results`: where to write the summary CSV
- `--delay`: delay between network operations (seconds)
- `--limit`: only process first N rows (optional)

Output logos and a `results.csv` will be written to the `--out` directory.

### Notes
- No API keys are used.
- Instagram scraping attempts multiple methods (public endpoints and page metadata). If blocked, the script will try website logos.
- Text logos are 512x512 PNGs with white text on a black background.