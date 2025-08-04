#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
USA Location Detector — FULL Gazetteer Support (Deterministic, no LLM)

- Loads a full US gazetteer (cities/places) from CSV, including GPS coordinates and population.
- Efficient token-trie matcher over normalized (ASCII-folded) text.
- Also recognizes US states (full names + USPS codes as UPPERCASE tokens) and common big-city aliases.
- Deterministic, fast, no external services.

Gazetteer CSV format (UTF-8, header required):
  name,kind,state,lat,lon,population,variants
Where:
  - name: canonical place name (e.g., "San Francisco")
  - kind: "city" | "town" | "village" | "place" (free text ok, used for ranking), or "airport"/"poi" if you want
  - state: USPS code (CA, NY, ...), blank for cross-state entities
  - lat,lon: decimal degrees
  - population: integer (optional; 0 if unknown)
  - variants: optional aliases separated by "|" (e.g., "san francisco|sf|s.f.|the bay")

Usage:
  python us_location_detector_full.py --gazetteer usa_gazetteer.csv --input queries.csv --output detected.csv --text-column query
"""
import re
import csv
import sys
import math
import unicodedata
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

def fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.lower()
    s = re.sub(r"\s+", " ", s).strip()
    return s

def tokenize(s: str) -> List[str]:
    return re.findall(r"[a-z0-9]+", s.lower())

@dataclass
class GazetteerEntry:
    canonical: str
    kind: str
    state: Optional[str]
    lat: Optional[float]
    lon: Optional[float]
    population: int
    variants: List[str] = field(default_factory=list)

US_STATES = [
    ("Alabama","AL"),("Alaska","AK"),("Arizona","AZ"),("Arkansas","AR"),
    ("California","CA"),("Colorado","CO"),("Connecticut","CT"),("Delaware","DE"),
    ("Florida","FL"),("Georgia","GA"),("Hawaii","HI"),("Idaho","ID"),
    ("Illinois","IL"),("Indiana","IN"),("Iowa","IA"),("Kansas","KS"),
    ("Kentucky","KY"),("Louisiana","LA"),("Maine","ME"),("Maryland","MD"),
    ("Massachusetts","MA"),("Michigan","MI"),("Minnesota","MN"),("Mississippi","MS"),
    ("Missouri","MO"),("Montana","MT"),("Nebraska","NE"),("Nevada","NV"),
    ("New Hampshire","NH"),("New Jersey","NJ"),("New Mexico","NM"),("New York","NY"),
    ("North Carolina","NC"),("North Dakota","ND"),("Ohio","OH"),("Oklahoma","OK"),
    ("Oregon","OR"),("Pennsylvania","PA"),("Rhode Island","RI"),("South Carolina","SC"),
    ("South Dakota","SD"),("Tennessee","TN"),("Texas","TX"),("Utah","UT"),
    ("Vermont","VT"),("Virginia","VA"),("Washington","WA"),("West Virginia","WV"),
    ("Wisconsin","WI"),("Wyoming","WY"),
]
STATE_SET = {abbr for _, abbr in US_STATES} | {"DC"}

# A few high-value nationwide aliases not in city gazetteers
BIG_CITY_ALIASES = {
    "New York": ["new york city","nyc","ny, ny","ny ny","manhattan","brooklyn","queens","bronx","staten island"],
    "Los Angeles": ["los angeles","l.a.","l. a."],  # Note: we do NOT add bare 'la' to avoid noise
    "San Francisco": ["san francisco","sf","s.f.","bay area","the bay"],
    "Washington, DC": ["washington dc","washington, dc","dc","d.c.","district of columbia","the district"],
    "Las Vegas": ["las vegas","vegas","lv"],
    "Miami": ["miami beach","south beach","so-be"],
    "Kansas City": ["kc","k.c.","kcmo","k.c. mo"],
    "Saint Louis": ["st. louis","st louis","stl"],
}

# ----------------------- Trie-based Keyword Matcher --------------------------

class TrieNode:
    __slots__ = ("children","outputs")
    def __init__(self):
        self.children: Dict[str, "TrieNode"] = {}
        self.outputs: List[Tuple[str, float]] = []  # (canonical_key, confidence)

class KeywordTrie:
    def __init__(self):
        self.root = TrieNode()

    def add(self, phrase: str, canonical_key: str, confidence: float = 0.95):
        toks = tokenize(fold(phrase))
        if not toks:
            return
        node = self.root
        for t in toks:
            node = node.children.setdefault(t, TrieNode())
        # store max confidence per canonical
        for i,(k,c) in enumerate(node.outputs):
            if k == canonical_key:
                if confidence > c:
                    node.outputs[i] = (k, confidence)
                break
        else:
            node.outputs.append((canonical_key, confidence))

    def find_all(self, text: str) -> List[Tuple[int,int,str,float]]:
        toks = tokenize(fold(text))
        n = len(toks)
        matches: List[Tuple[int,int,str,float]] = []
        for i in range(n):
            node = self.root
            j = i
            best: Optional[Tuple[int,int,str,float]] = None
            while j < n and toks[j] in node.children:
                node = node.children[toks[j]]
                j += 1
                for (ckey, conf) in node.outputs:
                    cur = (i, j, ckey, conf)
                    if (best is None) or (j - i > best[1] - best[0]) or (j - i == best[1] - best[0] and conf > best[3]):
                        best = cur
            if best:
                matches.append(best)
        return matches

# ----------------------- Detector -------------------------------------------

@dataclass
class CanonicalRecord:
    entry: GazetteerEntry
    canonical_key: str  # unique key, e.g., f"{name}|{state}"
    base_conf: float

class USLocationDetector:
    def __init__(self, gazetteer_rows: List[GazetteerEntry]):
        # Build canonical index and keyword trie
        self.canon_by_key: Dict[str, CanonicalRecord] = {}
        self.trie = KeywordTrie()
        # ingest gazetteer rows
        for e in gazetteer_rows:
            key = f"{e.canonical}|{e.state or ''}"
            self.canon_by_key[key] = CanonicalRecord(entry=e, canonical_key=key, base_conf=0.95)
            # add canonical name and variants
            all_variants = [e.canonical] + list(e.variants)
            for v in all_variants:
                # downweight risky very short tokens (<=2 chars); skip them
                if len(v) <= 2:
                    continue
                self.trie.add(v, key, 0.95 if v.lower()==e.canonical.lower() else 0.9)

        # Add big city aliases to strengthen recall (if present in dataset, map to that canonical)
        name_to_key = {rec.entry.canonical.lower(): key for key,rec in self.canon_by_key.items()}
        for name, aliases in BIG_CITY_ALIASES.items():
            key = name_to_key.get(name.lower())
            if key:
                for a in aliases:
                    self.trie.add(a, key, 0.92)

        # States index (full names -> canonical) and abbreviation handling
        self.state_name_to_abbr = {name.lower(): abbr for name, abbr in US_STATES}
        self.state_entries: Dict[str, CanonicalRecord] = {}
        for name, abbr in US_STATES:
            e = GazetteerEntry(canonical=name, kind="state", state=abbr, lat=None, lon=None, population=0, variants=[name])
            key = f"{e.canonical}|{e.state}"
            self.state_entries[key] = CanonicalRecord(entry=e, canonical_key=key, base_conf=0.93)
            self.trie.add(name, key, 0.93)
        # DC as region
        e = GazetteerEntry(canonical="District of Columbia", kind="region", state="DC", lat=None, lon=None, population=0, variants=["district of columbia","washington dc","washington, dc"])
        key = f"{e.canonical}|{e.state}"
        self.state_entries[key] = CanonicalRecord(entry=e, canonical_key=key, base_conf=0.93)
        self.trie.add("district of columbia", key, 0.93)
        self.trie.add("washington dc", key, 0.93)
        self.trie.add("washington, dc", key, 0.93)

    def _match_state_abbreviations(self, raw_text: str) -> List[Dict]:
        hits = []
        for tok in re.findall(r"\b[A-Z]{2,3}\b", raw_text):
            if tok in STATE_SET:
                if tok == "DC":
                    canonical = "District of Columbia"; kind = "region"
                else:
                    canonical = next(name for name, abbr in US_STATES if abbr == tok); kind = "state"
                key = f"{canonical}|{tok}"
                hits.append({
                    "canonical_key": key,
                    "confidence": 0.91,
                    "variant": tok
                })
        return hits

    def find(self, text: str) -> List[Dict]:
        raw = text or ""
        trie_hits = self.trie.find_all(raw)
        # Convert to canonical structures
        found: Dict[str, Dict] = {}
        for _i,_j,key,conf in trie_hits:
            rec = self.canon_by_key.get(key) or self.state_entries.get(key)
            if not rec:
                continue
            cand = {
                "canonical_key": key,
                "canonical": rec.entry.canonical,
                "kind": rec.entry.kind,
                "state": rec.entry.state,
                "lat": rec.entry.lat,
                "lon": rec.entry.lon,
                "population": rec.entry.population,
                "confidence": round(conf, 2),
                "variant": None,  # filled later if desired
            }
            # keep max confidence per canonical
            if (key not in found) or (conf > found[key]["confidence"]):
                found[key] = cand

        # State abbreviations from RAW (uppercase only)
        for h in self._match_state_abbreviations(raw):
            key = h["canonical_key"]
            rec = self.canon_by_key.get(key) or self.state_entries.get(key)
            if rec and ((key not in found) or (h["confidence"] > found[key]["confidence"])):
                found[key] = {
                    "canonical_key": key,
                    "canonical": rec.entry.canonical,
                    "kind": rec.entry.kind,
                    "state": rec.entry.state,
                    "lat": rec.entry.lat,
                    "lon": rec.entry.lon,
                    "population": rec.entry.population,
                    "confidence": h["confidence"],
                    "variant": h["variant"],
                }

        # Tie-breaking / sorting
        kind_rank = {"city": 3, "town": 3, "village": 3, "place": 3, "region": 2, "state": 2, "country": 1}
        ordered = sorted(found.values(), key=lambda d: (d["confidence"], d["population"], kind_rank.get(d["kind"], 0)), reverse=True)
        return ordered

# ----------------------- IO & CLI -------------------------------------------

def load_gazetteer_csv(path: str) -> List[GazetteerEntry]:
    rows: List[GazetteerEntry] = []
    with open(path, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        required = {"name","kind","state","lat","lon","population"}
        missing = [c for c in required if c not in reader.fieldnames]
        if missing:
            raise SystemExit(f"Gazetteer CSV missing columns: {missing}. Present: {reader.fieldnames}")
        for r in reader:
            name = (r.get("name") or "").strip()
            kind = (r.get("kind") or "place").strip().lower()
            state = (r.get("state") or "").strip().upper() or None
            try:
                lat = float(r.get("lat")) if r.get("lat") not in (None,"") else None
                lon = float(r.get("lon")) if r.get("lon") not in (None,"") else None
            except ValueError:
                lat = lon = None
            try:
                pop = int(float(r.get("population") or 0))
            except ValueError:
                pop = 0
            variants_field = r.get("variants") or ""
            variants = [v.strip() for v in variants_field.split("|") if v.strip()]
            rows.append(GazetteerEntry(canonical=name, kind=kind, state=state, lat=lat, lon=lon, population=pop, variants=variants))
    return rows

def detect_locations_in_csv(gazetteer_csv: str, in_path: str, out_path: str, text_column: str = "query"):
    gaz_rows = load_gazetteer_csv(gazetteer_csv)
    detector = USLocationDetector(gaz_rows)
    with open(in_path, newline='', encoding='utf-8') as fin, open(out_path, 'w', newline='', encoding='utf-8') as fout:
        reader = csv.DictReader(fin)
        if text_column not in reader.fieldnames:
            raise SystemExit(f"Input CSV must contain column '{text_column}'. Found: {reader.fieldnames}")
        fieldnames = [text_column, "location_canonical", "kind", "state", "lat", "lon", "population", "confidence"]
        writer = csv.DictWriter(fout, fieldnames=fieldnames)
        writer.writeheader()
        for row in reader:
            q = row.get(text_column, "") or ""
            hits = detector.find(q)
            if hits:
                top = hits[0]
                writer.writerow({
                    text_column: q,
                    "location_canonical": top["canonical"],
                    "kind": top["kind"],
                    "state": top.get("state") or "",
                    "lat": top.get("lat") if top.get("lat") is not None else "",
                    "lon": top.get("lon") if top.get("lon") is not None else "",
                    "population": top.get("population") or 0,
                    "confidence": top.get("confidence") or 0.0,
                })
            else:
                writer.writerow({
                    text_column: q,
                    "location_canonical": "",
                    "kind": "",
                    "state": "",
                    "lat": "",
                    "lon": "",
                    "population": 0,
                    "confidence": 0.0,
                })

def _demo_quick(detector: USLocationDetector):
    tests = [
        "cheap flights to NYC tomorrow",
        "weather in San Francisco next week",
        "jobs in Washington DC",
        "roadtrip texas to New Mexico",
        "moving to CA from AZ",
        "best tacos in LA",
        "hotels near Miami Beach",
        "concerts in Seattle and Portland",
        "atl braves schedule",
        "weekend in the Bay Area",
        "campsites in Yellowstone (Wyoming)",
        "where to stay in new york city manhattan",
        "Miami vs. Orlando theme parks",
    ]
    for t in tests:
        hits = detector.find(t)
        print(f"{t:55} -> {hits[:2]}")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="USA location detector with FULL gazetteer (deterministic, no LLM)")
    parser.add_argument("--gazetteer", type=str, required=True, help="Path to gazetteer CSV (see header format in docstring)")
    parser.add_argument("--input", type=str, help="Input CSV path with queries", required=False)
    parser.add_argument("--output", type=str, help="Output CSV path", required=False)
    parser.add_argument("--text-column", type=str, default="query", help="Name of the text column (default: query)")
    parser.add_argument("--demo", action="store_true", help="Run a quick demo using the provided gazetteer")
    args = parser.parse_args()

    gaz_rows = load_gazetteer_csv(args.gazetteer)
    detector = USLocationDetector(gaz_rows)

    if args.demo:
        _demo_quick(detector)
        sys.exit(0)

    if not args.input or not args.output:
        parser.error("--input and --output are required unless --demo is used")

    detect_locations_in_csv(args.gazetteer, args.input, args.output, text_column=args.text_column)
