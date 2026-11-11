# Region boundaries

## karnataka_districts.geojson

The 30 districts of Karnataka, India, as a GeoJSON FeatureCollection in WGS84 (about 300 KB). Each feature
has:
- `region_id`: `KA-` followed by the source's district name, for example `KA-MYSORE`;
- `name`: the current official district name, for display, for example `Mysuru`;
- `source_name`: the name as the source spells it, for example `Mysore`;
- `source_shape_id`: the geoBoundaries shape id.

| | |
| --- | --- |
| Source | geoBoundaries, gbOpen, India ADM2, release `9469f09` (built 12 Dec 2023), simplified geometry: <https://www.geoboundaries.org/> |
| Original data | Pathways Data Pvt. Ltd., lgdirectory.gov.in; boundary year 2021 |
| Licence | **Open Database License (ODbL) 1.0**: <https://opendatacommons.org/licenses/odbl/1-0/> |
| Citation | Runfola, D. et al. (2020) geoBoundaries: A global database of political administrative boundaries. *PLoS ONE* 15(4): e0231866. <https://doi.org/10.1371/journal.pone.0231866> |
| Made by | `scripts/extract_karnataka_districts.py` |

### Licence of this file

`karnataka_districts.geojson` is a **derived database**. It is cut down from geoBoundaries' India ADM2 file
(Karnataka only, rounded coordinates, current names added) and is **published under the Open Database License
(ODbL) 1.0, share-alike**. The licence applies to this file only, not to the rest of the repository.

Anyone may use, share and adapt it. Anyone who publicly uses or shares an adapted version must:
- keep this attribution;
- publish the adapted version under ODbL 1.0 too;
- keep the version available in an open form.

Attribution:

> District boundaries: geoBoundaries (Runfola et al. 2020, www.geoboundaries.org), gbOpen IND ADM2, source
> Pathways Data Pvt. Ltd. / lgdirectory.gov.in, licensed under the Open Database License (ODbL) 1.0.
> Karnataka subset, coordinates rounded.

The same credit line is stored in the file's `attribution` field. The surveillance map shows it under the map
whenever these boundaries are loaded.

### How it was made

1. **Download** the simplified India ADM2 (districts) and ADM1 (states) files of the release above.
2. **Choose the districts.** A district is kept when its centroid lies inside the geoBoundaries outline of
   Karnataka. The ADM1 file is used only for this choice and none of its data is in the output. (The ADM1 file
   is CC BY 2.5 IN, DataMeet / Election Commission of India.)
3. **Round** coordinates to 5 decimal places (about 1 m).
4. **Add display names.** Older English spellings are mapped to the current official names, using the
   `CURRENT_NAMES` table in the script:

   | Source name | Shown as |
   | --- | --- |
   | Bangalore | Bengaluru Urban |
   | Bangalore Rural | Bengaluru Rural |
   | Belgaum | Belagavi |
   | Bellary | Ballari |
   | Bijapur | Vijayapura |
   | Chikmagalur | Chikkamagaluru |
   | Gulbarga | Kalaburagi |
   | Mysore | Mysuru |
   | Shimoga | Shivamogga |
   | Tumkur | Tumakuru |

   The region ids keep the source spelling (`KA-BANGALORE`, `KA-MYSORE`), so they never change when a name
   does.

The result is the 30 districts Karnataka had before Vijayanagara was formed from Ballari in 2021. This source
does not show Vijayanagara separately; its area is inside Ballari. The file's `notes` field says so, and the
map shows that note under the map.

The file has no population field, so the map shows reported cases rather than rates per 100,000 residents.
Only the state is included, with no national boundary, and the map cannot be zoomed out beyond the state.

### Use

```bash
# backend/.env
REGIONS_GEOJSON_PATH=data/boundaries/karnataka_districts.geojson
REGION_ID_FIELD=region_id
REGION_NAME_FIELD=name
```

The map then shows Karnataka's districts. In demo mode the weekly case reports for them are still
**simulated**. Real districts with made-up counts could be mistaken for real cases, so the map then carries a
permanent "SIMULATED DATA – NOT REAL CASES" watermark. Every PDF and CSV export (Phase 2) must carry the same
text, taken from `data_status.watermark`. Health officers' jurisdictions use these region ids,
for example `KA-MYSORE`. Give real accounts a jurisdiction under Settings.

By default the built-in demo officers cover the simulated regions R01–R12 and the four simulated hospitals sit
in evenly spread regions. To place them in districts (the hospitals keep their fictional names and SIMULATED
data):

```bash
# backend/.env
REGION_POPULATIONS_CSV=data/boundaries/karnataka_census2011_population.csv
DEMO_HOSPITAL_REGIONS=hospital_a:KA-DHARWAD,hospital_b:KA-BELGAUM,hospital_c:KA-BANGALORE,hospital_d:KA-MYSORE
DEMO_OFFICER_NORTH_LABEL=Belagavi division
DEMO_OFFICER_NORTH_REGIONS=KA-BELGAUM,KA-BAGALKOT,KA-BIJAPUR,KA-DHARWAD,KA-GADAG,KA-HAVERI,KA-UTTARA-KANNADA
DEMO_OFFICER_SOUTH_LABEL=Mysuru division
DEMO_OFFICER_SOUTH_REGIONS=KA-MYSORE,KA-CHAMARAJANAGAR,KA-MANDYA,KA-HASSAN,KA-KODAGU,KA-CHIKMAGALUR,KA-DAKSHINA-KANNADA,KA-UDUPI
```

Each district's simulated cases are split 70/30 between the two hospitals whose home districts are nearest. Use
a fresh database when switching from the simulated regions: the stored reports, alerts and forecasts are per
region.

## karnataka_census2011_population.csv

District populations from the **Census of India 2011** (Office of the Registrar General & Census
Commissioner, India), for rates per 100,000 (`REGION_POPULATIONS_CSV`; see docs/setup.md). Columns:
`region_id` (matching `karnataka_districts.geojson`), `name` and `population`.

- **Where the figures were taken from:** the district totals as tabulated at
  <https://www.census2011.co.in/census/state/districtlist/karnataka.html>, which republishes the Census 2011
  figures; they were not copied from the official Primary Census Abstract tables.
- **Check:** the 30 district totals add up to 61,095,297, Karnataka's official 2011 population.
- **Ballari:** in 2011 Ballari included the area that became Vijayanagara district in 2021. The Ballari
  figure (2,452,595) therefore matches the Ballari boundary in this source, which also includes it.
- **Age:** these are 2011 counts. Rates computed from them are per 100,000 people as counted in 2011, not
  today's population, and the dashboard and exports label them "Census 2011 population".
