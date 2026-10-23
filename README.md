# Houston Storm Impact & Recovery

Historical evidence for the question: **How did wind and rainfall relate to power disruption and insured flood losses across Greater Houston?**

The dataset covers Harris, Fort Bend, Montgomery, Brazoria, and Galveston counties during Harvey (2017), Imelda (2019), Nicholas (2021), and Beryl (2024). It combines the organizer-supplied weather, IBTrACS tracks, NFIP claims, and county boundaries with official DOE/ORNL EAGLE-I outage records and eight published CenterPoint Beryl restoration milestones.

## Open the dashboard

Start the localhost application from this repository:

```powershell
python app.py
```

Then open <http://127.0.0.1:8000/>. Stop with Ctrl+C. If the port is occupied, use `python app.py --port 8001`.

The application includes:

- **Live file checks:** revalidate the current source fingerprints, exported totals, keys, and time alignment. “Check files again” reruns validation without changing data.
- **Evidence answers:** choose questions about cleanliness, missing data, defensible conclusions, and CenterPoint geography. Answers use the selected county and storm.
- **Data collection checklist:** recommendations and requested fields for historical comparisons, prediction, or emergency resource priorities.
- **Storm explorer:** the county map, weather/outage timelines, claims, downloads, and source notes.

No API key or external AI service is used. Evidence answers follow explicit rules and local records. A successful file check validates processing, not the accuracy of every upstream measurement. The server listens only on this computer and serves the dashboard, generated downloads, and documentation.

You can also open [dashboard/index.html](dashboard/index.html) directly for the offline storm explorer. Live checks and evidence answers require `python app.py`. A plain static server supports the explorer but does not provide the readiness API:

```powershell
python -m http.server 8000 --bind 127.0.0.1
```

Then visit <http://127.0.0.1:8000/dashboard/>. Stop the server with Ctrl+C.

The read-only `/api/readiness` endpoint accepts `storm`, `county`, and `goal` (`history`, `forecasting`, or `preparedness`). Add `refresh=1` to rerun integrity validation. Responses include current integrity status, per-selection usable snapshot counts, limitations, and collection recommendations. Failed checks are surfaced rather than presented as a clean dataset.

## Official reports, discrepancies, response time, staging what-if

Five official sources are bundled in `data/raw/reports/`: the PUCT Beryl investigation (Nov 2024), CenterPoint's Beryl presentation to the PUCT, the NWS Houston/Galveston Beryl impact summary, the City of Houston's PUCT filing, and the Governor's Commission *Eye of the Storm* (Harvey). There are 47 findings in `report_findings.csv`, each with a page number and an exact quote. The build fails if any quote is missing from its page in the extracted text (`data/raw/reports/text/`).

- **Consensus:** unreliable information for customers and responders was raised in 4 of 5 reports, across both storms, by both the utility and the regulator. Staging, travel and coordination problems were raised in 3 reports, across both storms. Trees and vegetation were raised in 3 reports.
- **Discrepancies (17 checks):** people and customers are used interchangeably for the 2.7M and 2.2M peaks. CenterPoint's damage model forecast at most 2,559 workers; about 14,000 were needed. CenterPoint used 22 staging sites; the PUCT recommends planning for 25–30. EAGLE-I shows 18–25% more customers still out in the five counties than CenterPoint's own milestones imply (partly other utilities). EAGLE-I's Harvey count for Harris is about 80× lower than the ZIP file's.
- **Response time:** Beryl took 50–74 hours to halve outages in each county, and no county reached 90% restored before the EAGLE-I window ends. Harvey ZIP data takes 1–3 days to halve.
- **What the longest outages had in common:** across 198 Harvey ZIPs, the slowest-restored quarter had 4.5× the flood-claim rate of the fastest (rank correlation +0.40). The worst hotspots cluster around Lake Houston (Porter, Kingwood, Lake Houston area). Five recommendations each cite their statistic and report pages.
- **Staging what-if:** clicking the map adds a staging site and recomputes the outage-weighted crew trip. Across 195 Harvey ZIPs, distance to a service center did **not** explain restoration time (r = −0.08), so the tool reports only the travel-time saving.

## Reproduce and validate

Python 3.10+ is required. `tzdata` supplies the IANA time zone database on Windows. The remaining Python code uses the standard library.

```powershell
python -m pip install -r requirements.txt
python -m stormdata.build
python -m stormdata.validate
python -m unittest discover -s tests -v
```

The build also reads two organizer-supplied ArcGIS geodatabase zips in the repository root (`Hurricane_Harvey_Power_Outages_by_Zip_Code.zip`, `Hurricane_Harvey_FEMA_Modeled_Damages.zip`) directly, using a standard-library reader (`stormdata/filegdb.py`). No unzipping or GIS software is needed. To inspect one: `python -m stormdata.filegdb <zip>`.

The official outage extraction and CenterPoint evidence are already bundled under `data/raw`. To retrieve them again:

```powershell
python -m stormdata.fetch
python -m stormdata.build
python -m stormdata.validate
```

The fetcher pins [EAGLE-I release v4](https://doi.org/10.6084/m9.figshare.24237376.v4), licensed CC BY 4.0. It extracts the three earlier storms from their UTC time-sorted annual archives using checked HTTP byte ranges. **The 2024 source contains misplaced county rows, so Beryl requires a full 1.45 GB source scan**; only the selected records are saved. Completed per-event extractions are cached in ignored `data/cache/`. Remove only that cache directory if a fresh source scan is wanted. Fetching also checks each CenterPoint figure against its dated headline, saves the official HTML index, and records source file IDs, publisher checksums, HTTP range hashes, and extraction bounds.

The first acquisition requires internet access and may take several minutes. The build and validation commands run offline. The pipeline fails on duplicate timestamps, negative or noninteger outage counts, off-grid outage times, unknown storms, or missing required input files. Blank source outage counts are excluded and audited, never converted to zero.

## Exported files

| File in `data/processed/` | Grain / purpose |
| --- | --- |
| `county_storm_hour.csv` | 3,960 unique county–storm–hours; weather, track distance/intensity, observed outage averages and peaks |
| `county_storm.csv` | 20 county–storm summaries; weather, outage sample coverage, claims, net payments |
| `centerpoint_beryl_milestones.csv` | Eight achieved restoration milestones; territory geography, publication times, and numeric qualifiers |
| `claim_assignments.csv` | All 80,547 input claim records, with assignment or exclusion reason and source row reference |
| `excluded_outage_records.csv` | One source record with a blank customer count |
| `descriptive_associations.csv` | Unadjusted Pearson correlations, per storm and pooled; sample counts included |
| `counties.geojson` | The five selected county polygons, keyed by five-digit FIPS |
| `harvey_county_supplement.csv` | 5 counties; Harvey peak daily ZIP-file outages and FEMA modeled damage counts |
| `harvey_county_outages_daily.csv` | 45 county–days (5 counties × 9 days) summed from assigned ZIP codes |
| `harvey_zip_outages_daily.csv` | All 1,782 ZIP–day outage records, with county assignment and source OBJECTID |
| `harvey_zip_county_assignments.csv` | 198 ZIP codes; majority county, sampled area shares, split-ZIP flag |
| `harvey_fema_damage_assessments.csv` | 8 counties; FEMA modeled housing damage by severity and floodplain zone |
| `source_manifest.json` | Input SHA-256 fingerprints, upstream attribution and retrieval metadata |
| `processing_manifest.json` | Build policies, code fingerprints and output fingerprints |
| `validation_report.json` | Checks, counts, missing usable snapshots, and limitations |

Read [the methodology](docs/METHODOLOGY.md) and [the data dictionary](docs/DATA_DICTIONARY.md) before interpreting results. Keep FIPS as strings when importing CSVs.

## What is defensible

- Every hourly weather/track/outage value has a source row reference. Every claim assignment is auditable against the unchanged input CSV. Payment totals are independently reconciled to assigned source claims.
- Outages represent reporting utilities at county scale. CenterPoint milestones represent its Houston Electric service territory and are **never allocated to counties**.
- Missing source snapshots remain unknown. Harvey has no usable EAGLE-I outage snapshots for Brazoria or Fort Bend in the selected window. The UI renders those outcomes as **Unknown**.
- A separate Harvey supplement adds daily ZIP-code outage counts and FEMA modeled damage counts. It never fills EAGLE-I gaps: the two outage sources disagree (EAGLE-I is far lower for Harris, higher for Montgomery) and neither covers every utility.
- Complete quarter-hour snapshots exist for all five counties during the supplied Beryl and Nicholas windows. This establishes record presence, not independent verification of utility coverage or reported counts.
- NFIP net payments are insured flood payments in nominal USD, not total economic damage or all households' flood losses. Weather is a point-sampled reanalysis proxy, not countywide observation or a forecast.
- Only four storms are represented. Correlations are historical descriptions; no causal, predictive-accuracy, or statistical-significance claim is made. Recovery may continue after the supplied weather windows end.

The starter files' upstream sources and weather units are attributed to the challenge brief; their original download requests, timestamps and independent source reconciliation were not supplied. This limitation is retained in the manifest and dashboard.

## Attribution

Outages: Tansakul et al., *The Environment for Analysis of Geo-Located Energy Information's Recorded Electricity Outages 2014–2025*, [Figshare v4](https://doi.org/10.6084/m9.figshare.24237376.v4), DOE/ORNL, CC BY 4.0. CenterPoint: [official Beryl release index](https://origin-hmong.centerpointenergy.com/en-us/residential/services/hurricane-beryl-response?sa=mn), company-reported figures. Starter inputs: NOAA IBTrACS, Open-Meteo historical archive/ERA5, OpenFEMA NFIP Redacted Claims v3, U.S. Census county boundaries, as identified in the challenge brief.
