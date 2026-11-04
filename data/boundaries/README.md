# Region boundaries

## karnataka_districts.geojson

The 30 districts of Karnataka, India, as a GeoJSON FeatureCollection in WGS84 (295 KB). Each feature has:
- `region_id`: `KA-` followed by the district name, for example `KA-MYSORE`;
- `name`: the district name;
- `source_shape_id`: the geoBoundaries shape id.

| | |
| --- | --- |
| Source | geoBoundaries, gbOpen, India ADM2, release `9469f09` (built 12 Dec 2023), simplified geometry: <https://www.geoboundaries.org/> |
| Original data | Pathways Data Pvt. Ltd., lgdirectory.gov.in; boundary year 2021 |
| Licence | **Open Database License (ODbL) 1.0**: <https://opendatacommons.org/licenses/odbl/1-0/> |
| Citation | Runfola, D. et al. (2020) geoBoundaries: A global database of political administrative boundaries. *PLoS ONE* 15(4): e0231866. <https://doi.org/10.1371/journal.pone.0231866> |
| Made by | `scripts/extract_karnataka_districts.py` |

The file is a derived database. Under the ODbL it is distributed under the same licence (ODbL 1.0) and with
this attribution:

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

The result is the 30 districts Karnataka had before Vijayanagara was formed from Ballari in 2021. This source
does not show Vijayanagara separately, and it uses the older English names (Bangalore, Belgaum, Bellary,
Bijapur, Gulbarga, Mysore, Shimoga, Tumkur). Bangalore Urban appears as `Bangalore` (`KA-BANGALORE`).

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
**simulated**, and the dashboard labels them that way. Health officers' jurisdictions use these region ids,
for example `KA-MYSORE`. The built-in demo officers cover the simulated regions R01–R12, so give real accounts
a jurisdiction under Settings.
