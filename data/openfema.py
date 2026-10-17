"""OpenFEMA disaster declarations -> NYAYA severity tiers (0-5).

Fetch real declarations (public US government data, no key needed):
    python -m data.openfema --out ~/shared/data/openfema_declarations.csv --since 2015-01-01
Then `severity_table(df)` shows how real declaration types map onto the tiers the models use.
"""
from __future__ import annotations

import argparse
import json
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://www.fema.gov/api/open/v2/DisasterDeclarationsSummaries"
FIELDS = ["disasterNumber", "state", "declarationType", "declarationDate", "incidentType", "declarationTitle",
          "incidentBeginDate", "incidentEndDate", "ihProgramDeclared", "iaProgramDeclared", "paProgramDeclared",
          "designatedArea"]

# Base tier by hazard. Cyclones, earthquakes and tsunamis displace the most people.
INCIDENT_BASE = {
    "hurricane": 4, "typhoon": 4, "tropical storm": 3, "coastal storm": 3, "earthquake": 4, "tsunami": 4,
    "flood": 3, "dam/levee break": 3, "severe storm": 2, "severe storm(s)": 2, "tornado": 3, "mud/landslide": 3,
    "fire": 2, "snowstorm": 2, "severe ice storm": 2, "winter storm": 2, "volcanic eruption": 3, "drought": 1,
    "biological": 1, "chemical": 1, "terrorist": 2, "other": 1,
}


def severity_tier(declaration_type: str, incident_type: str, ih_program: bool | int = False) -> int:
    """DR (major disaster) +1, FM (fire management) −1, Individual Housing assistance declared (+1: people
    displaced from their homes). Clamped to 1–5; 0 means no declaration."""
    tier = INCIDENT_BASE.get(str(incident_type).strip().lower(), 1)
    dt = str(declaration_type).strip().upper()
    if dt == "DR":
        tier += 1
    elif dt == "FM":
        tier -= 1
    if bool(ih_program) and str(ih_program).lower() not in ("0", "false"):
        tier += 1
    return max(1, min(5, tier))


def fetch(since: str = "2015-01-01", page: int = 1000, limit: int | None = None) -> list[dict]:
    rows, skip = [], 0
    while True:
        q = {"$filter": f"declarationDate ge '{since}T00:00:00.000z'", "$select": ",".join(FIELDS),
             "$top": str(page), "$skip": str(skip), "$orderby": "declarationDate"}
        url = API + "?" + urllib.parse.urlencode(q, safe="$,'")
        with urllib.request.urlopen(url, timeout=60) as r:
            batch = json.load(r).get("DisasterDeclarationsSummaries", [])
        rows += batch
        skip += page
        if len(batch) < page or (limit and len(rows) >= limit):
            return rows[:limit] if limit else rows


def add_tiers(df):
    df = df.copy()
    df["severity_tier"] = [severity_tier(d, i, h) for d, i, h in
                           zip(df["declarationType"], df["incidentType"], df.get("ihProgramDeclared", False))]
    return df


def severity_table(df):
    """Declarations (unique disaster numbers) per incident type and tier."""
    d = add_tiers(df).drop_duplicates("disasterNumber")
    return d.pivot_table(index="incidentType", columns="severity_tier", values="disasterNumber",
                         aggfunc="count", fill_value=0)


def main(argv=None):
    import pandas as pd

    p = argparse.ArgumentParser()
    p.add_argument("--out", type=Path, default=Path.home() / "shared" / "data" / "openfema_declarations.csv")
    p.add_argument("--since", default="2015-01-01")
    a = p.parse_args(argv)
    df = add_tiers(pd.DataFrame(fetch(a.since)))
    a.out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(a.out, index=False)
    print(f"{len(df)} rows, {df['disasterNumber'].nunique()} declarations -> {a.out}")
    print(severity_table(df))


if __name__ == "__main__":
    main()
