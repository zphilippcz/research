#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Convert GeoNames US dataset (US.txt) into a compact USA gazetteer CSV
with columns: name,kind,state,lat,lon,population,variants

Input: GeoNames 'US.txt' (tab-separated). You can download it from geonames.org
as part of the "allCountries" or "US" subset. Expected columns per GeoNames docs:
geonameid, name, asciiname, alternatenames, latitude, longitude,
feature class, feature code, country code, cc2, admin1 code, admin2 code,
admin3, admin4, population, elevation, dem, timezone, modification date

We keep rows where:
- country code == 'US'
- feature class == 'P' and feature code starts with 'PPL' (populated places),
  OR feature class == 'A' and feature code == 'ADM1' (states, optional)

For performance/size you can filter to population > 1000 (option).

Usage:
  python geonames_us_to_gazetteer.py --us US.txt --out usa_gazetteer.csv --min-pop 1000

Note: This script does not require the giant alternateNames file; it uses the
'alternatenames' column embedded in US.txt.
"""
import csv
import sys

def convert(us_path: str, out_csv: str, min_pop: int = 0, keep_states: bool = False):
    kept = 0
    with open(us_path, 'r', encoding='utf-8') as fin, open(out_csv, 'w', newline='', encoding='utf-8') as fout:
        writer = csv.writer(fout)
        writer.writerow(["name","kind","state","lat","lon","population","variants"])
        for line in fin:
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 19:
                continue
            name = parts[1]
            asciiname = parts[2]
            alternatenames = parts[3]
            lat = parts[4]
            lon = parts[5]
            fclass = parts[6]
            fcode = parts[7]
            country = parts[8]
            admin1 = parts[10]  # For US this should be the 2-letter state code
            pop = parts[14]

            if country != "US":
                continue

            kind = None
            if fclass == "P" and fcode.startswith("PPL"):
                kind = "city"
            elif keep_states and fclass == "A" and fcode == "ADM1":
                kind = "state"
            else:
                continue

            try:
                ipop = int(float(pop or 0))
            except:
                ipop = 0
            if ipop < min_pop:
                continue

            variants = set()
            if asciiname and asciiname.lower() != name.lower():
                variants.add(asciiname)
            if alternatenames:
                for v in alternatenames.split(","):
                    v = v.strip()
                    if v and v.lower() != name.lower():
                        variants.add(v)
            variants_str = "|".join(sorted(variants))

            writer.writerow([name, kind, admin1, lat, lon, ipop, variants_str])
            kept += 1
    print(f"Wrote {kept} rows to {out_csv}")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Convert GeoNames US.txt to USA gazetteer CSV")
    parser.add_argument("--us", required=True, help="Path to GeoNames US.txt")
    parser.add_argument("--out", required=True, help="Output CSV path (gazetteer)")
    parser.add_argument("--min-pop", type=int, default=0, help="Minimum population filter (default 0)")
    parser.add_argument("--keep-states", action="store_true", help="Include ADM1 state records (optional)")
    args = parser.parse_args()
    convert(args.us, args.out, min_pop=args.min_pop, keep_states=args.keep_states)
