# Methodology and interpretation

## Geography and time

The analysis joins five-digit county FIPS and stable storm identifiers. Source geography is preserved: the county outage archive contains all reporting utilities, while CenterPoint milestones cover the Houston Electric service territory. A county can have more than one utility. Neither source is used to allocate the other geographically.

Weather timestamps are America/Chicago local time according to the challenge brief. They are converted with IANA time zone rules to UTC before joining EAGLE-I. All four weather windows occur during daylight saving time (UTC−05:00). NOAA track timestamps and EAGLE-I timestamps are UTC. Loss dates are treated as calendar dates, not shifted from their serialized midnight timestamps.

| Storm | Weather/outage window in local calendar days, inclusive | NFIP loss-date eligibility, inclusive |
| --- | --- | --- |
| Harvey | 2017-08-23 through 2017-09-03 | 2017-08-24 through 2017-09-13 |
| Imelda | 2019-09-16 through 2019-09-22 | 2019-09-17 through 2019-09-24 |
| Nicholas | 2021-09-12 through 2021-09-17 | 2021-09-13 through 2021-09-16 |
| Beryl | 2024-07-05 through 2024-07-12 | 2024-07-07 through 2024-07-09 |

Claim windows cover the observed date range for each exact named event in the starter extract. They are explicit reproducible inclusion rules, not independently established meteorological storm durations. Extending the dataset requires reviewing these rules rather than automatically assigning unlabeled losses near a storm date.

## Weather and track processing

The weather file has one sampling point per county. The brief attributes it to Open-Meteo/ERA5 and specifies inches of hourly precipitation and mph for wind. Temperature is stored as Celsius, pressure as hPa, soil moisture as m³/m³, and direction as degrees. Rain and total precipitation are kept separate; **total precipitation is summed once**, without adding rain again. No silent unit conversion or guessed rescaling occurs.

Hourly track centers are linearly interpolated between bracketing IBTrACS observations only when the gap is at most three hours. No extrapolation occurs. Track-center maximum sustained wind is interpolated only if both endpoints have it. Category is taken from the nearest observation (earlier on ties), not numerically interpolated. Track coordinates here do not cross the dateline.

Distance is the haversine great-circle distance in km from the county's weather reference point to that storm center, using mean Earth radius 6371.0088 km. It is **not distance to the county boundary**. Track rows are clipped to the starter's Gulf bounding box; blank track values outside it do not mean there was no storm. Minimum distance is restricted to available track hours within the weather window. Storm-center intensity is not local surface wind exposure.

## Outage processing

The acquisition pins Figshare article 24237376, version 4. Original annual file IDs, names, publisher MD5s, byte lengths, download URLs, and downloaded range SHA-256s are preserved in `data/raw/retrieval_manifest.json`. Earlier annual files are extracted using their UTC timestamp sort order; each downloaded event range is checked for monotonic order and correct bounds. The 2024 CSV has at least one out-of-order county record (a Brown County record inside the Brazoria block), so that year is scanned in full rather than using county binary search. Only selected county/event records are retained locally.

A quarter-hour source record with a valid integer customer count is usable. Negative, fractional, nonfinite, or off-grid records fail validation. Blank counts remain unknown and appear in the exclusion audit. Duplicate county/timestamp keys fail rather than being silently summed or averaged. Source zero, if explicitly present, is a valid observed zero. Absent records are never inferred as zero; the extract cannot distinguish every reporting failure from other reasons for absence.

For an hourly interval `[t,t+1h)`, collect source snapshots at `t`, `t+15m`, `t+30m`, and `t+45m`:

- `outage_customers_mean_observed` is their arithmetic mean over usable snapshots only.
- `outage_customers_mean_complete_hour` is populated only when all four snapshots are usable.
- `outage_customers_peak_observed` is the largest usable snapshot, not a count of unique customers affected.
- `outage_observed_sample_customer_hours` is `0.25 × sum(usable snapshot counts)`. It is a rectangular sample-based integral restricted to observed snapshots, not a reconstruction of exact outage durations. Unknown intervals contribute no estimate, and an entirely unobserved hour is blank rather than zero.
- `outage_record_presence_fraction` is usable snapshots divided by expected snapshots. It does not measure utility participation or customer coverage.

Event peak is the maximum usable snapshot in the supplied weather window. Recovery duration and time to 90% restoration are deliberately not calculated: the available window can truncate recovery, and county aggregate counts do not identify individual customer restoration times.

## Claims and payments

A claim is assigned only when county FIPS, exact `floodEvent` label, `yearOfLoss`, and the explicit loss-date window agree. The audit lists every record, including the 4,887 with blank event labels and other excluded events. Nicholas uses the source label `Tropical Storm Nicholas` even though the weather identifier is `Hurricane_Nicholas_2021`.

No approximate lat/lon join is performed. NFIP coordinates are rounded and unsuitable for assigning individual properties. Identical redacted records are retained because no stable claim identifier is supplied; apparent duplicates cannot safely be assumed to be duplicate claims.

Payments use **only** `netBuildingPaymentAmount` and `netContentsPaymentAmount`. They are aggregated separately with decimal arithmetic before being added. Alternative `amountPaidOn...` columns are not added to the same totals. Missing component counts are exposed. When some claims have missing payment components, component totals represent available payments; if an entire component is missing, the total is blank. All currently assigned claims have both net payment components populated.

County–storm payment totals appear only in the event summary. They are never duplicated into the hourly table. No insurance-coverage, insured-building, population, or customer denominator is inferred. Cross-storm dollar comparisons are nominal and not adjusted for inflation, settlement maturity, insurance uptake, or exposure. NFIP loss dates and weather windows describe different observation periods and are shown separately.

## CenterPoint evidence

Eight achieved Beryl restoration milestones are transcribed from the official dated release index. Each statement is checked within the matching dated/time-stamped headline, not merely found somewhere on the page. The numeric value is accompanied by a qualifier: `greater_than`, `nearly`, or `reported_rounded`. “Nearly 1 million” is not converted into exactly 1 million or a manufactured interval. Customer-restoration totals and percentage milestones are different metrics and cannot be subtracted or added to each other.

Release timestamps identify publication time; they do not establish the precise measurement time. Goals, forecasts, and future targets are excluded. `county_fips` stays blank. These reports are company-reported at publication, not independently reconciled outage measurements. The original HTML snapshot is bundled, so evidence remains reviewable if the live page changes.

## Harvey supplement (ZIP outages and FEMA modeled damage)

Two organizer-supplied ArcGIS File Geodatabases cover Harvey only. The challenge brief names no publisher, URL, or collection method for them, so the source manifest records `organizer_supplied_no_upstream_attribution`. `stormdata/filegdb.py` reads their tables straight from the zips using the public OpenFileGDB format description. Every output row keeps its source `OBJECTID`, and validation re-reads the zips to reconcile counts.

**ZIP outages.** 198 ZIP codes × 9 calendar dates (2017-08-27 through 2017-09-04), one record per ZIP per day with `Outage_Count`, `Total_Customers`, and `Outage_Pct`. The time of day of each snapshot is not stated, so these are dated snapshots, not daily peaks or averages. Duplicate ZIP–days fail the build. Two records report more outages than customers (the source caps their percentage at 100); they are kept and flagged. `Total_Customers` changes from day to day (Harris reporting ZIPs fall from about 1.85M to 0.92M by Sep 4), so daily percentages use shifting denominators. Customer totals across all ZIPs (about 2.3M) resemble one large utility's service area, but the file does not say which.

**ZIP-to-county assignment.** ZIP polygons are stored in NAD83 Texas South Central State Plane (US feet). They are converted to longitude/latitude with an ellipsoidal inverse Lambert Conformal Conic, using the parameters in the file's own projection definition. Each ZIP is sampled on a 24 × 24 grid over its bounding box, and points inside the ZIP are classified by county. The ZIP is assigned whole to the county holding the largest share of sampled area. Shares below 0.9 set `split_across_counties`; 22 ZIPs are split. Outages are not apportioned between counties, because customers are not spread evenly across area. County outlines are the organizer's simplified cartographic boundaries (14–105 vertices), so shares near county lines are approximate. ZIPs whose majority falls in Austin, Waller, Chambers, or Liberty, or outside all nine supplied counties, stay in the ZIP files and are excluded from study-county sums.

**County daily sums** add the outage counts and customer totals of ZIPs assigned to each study county. They describe reporting ZIPs, not every customer in the county. The county peak is the largest daily sum.

**EAGLE-I comparison.** The two outage sources are kept apart and never combined or used to fill each other's gaps. For Harvey they disagree substantially: Harris peaks at 1,089 customers in EAGLE-I versus 89,319 in one ZIP-file daily snapshot, while Montgomery is higher in EAGLE-I (22,109 vs 5,341). Montgomery and Galveston are partly served by other utilities, which fits the ZIP file covering only part of the region. Neither source should be read as a complete count.

**FEMA modeled damage.** One row per county (eight counties, including Chambers, Liberty, and Waller outside the study set) with housing-damage counts split by severity (`Affected/Minor`, `Major/Destroyed`) and floodplain designation (100-year, 500-year, outside). The six categories must sum to `Total_Observations` or the build fails. These are modeled assessments of damaged housing units, not insured claims, payments, or dollar losses, and are not comparable one-to-one with NFIP claim counts. The workbook in the same zip appears to restate the same table and is not used.

The USGS flow geodatabase (`Hurricane_Harvey_Flow.zip`) is readable with the same tools but is not yet part of the build.

## Official reports and discrepancies

Reports were downloaded on 2026-10-23 (URLs and fingerprints are in `data/raw/reports/reports.json` and the source manifest). Text was extracted once with `pypdf` outside the project and saved with page markers, so the build stays standard-library only. Page numbers are PDF page positions. Findings were hand-curated into a fixed list of issue categories. A quote must appear on its stated page after whitespace and quote-mark normalization, or the build fails. OCR artifacts in the source text (e.g. "Iockouts") are quoted as extracted. The PA Consulting after-action report could not be downloaded (the server returned HTML), so it appears only where the PUCT cites it.

Consensus counts distinct reports per issue, not findings. Outage-scale and restoration-timeline findings are kept as metrics and left out of the issue bars.

Discrepancy verdicts: `unit_mismatch` (people vs customers), `different_geography` (e.g. statewide vs five counties; the ratio is context, not an error), `agree_within_10pct`, `disagree`, and `not_comparable` (outside the data window). CenterPoint-implied outages are the PUCT's 2.2M peak minus the milestone's restored count; milestones marked "greater than" make that implied figure an upper bound. EAGLE-I comparisons use the five-county hourly mean and require all five counties to be observed.

## Restoration time

For each county series, the peak is the largest known value. The time to 50% (or 10%) of peak is the first point after the peak from which **every later known value stays at or below** the threshold. This sustained rule ignores one-off source dropouts (Harris EAGLE-I reads about 2,300 at Jul 9 20:00, between hours of about 1M). If the data ends first, the result is "not reached"; nothing is extrapolated. Harvey uses daily ZIP snapshots (step = 1 day); Beryl uses EAGLE-I hourly observed means (step = 1 hour).

## Staging what-if

Three tabs share one method. **Power outages:** CenterPoint service centers serving Harvey ZIP outage burden (below). **Flood relief:** the George R. Brown and NRG Center mega-shelters (CBS News, Aug 2017; geocoded with the Census geocoder and OpenStreetMap) serving Harvey NFIP claims in the five counties, counted per 0.1-degree cell because claim coordinates are rounded to 0.1 degree. **Disaster relief:** both mega-shelters plus the Katy Buc-ee's responder staging area (Eye of the Storm, p.100), serving a combined need index that gives the outage burden and the flood claims equal total weight.

Sites: four CenterPoint service centers from CenterPoint's service-center list (dated 2017-10-25, seen via search because the PDF blocks direct download). They were geocoded with the US Census Geocoder. The list is partial. Demand: each Harvey ZIP's sampled centroid, weighted by customer-days out (sum of daily snapshots). Crew trip = straight-line km × 1.3 road circuity, converted to minutes at an assumed 30 km/h storm-period speed. Both are stated assumptions, not measurements. Candidate new sites form a 0.05° grid within 8 km of a demand ZIP; the best single addition is precomputed, and the dashboard recomputes any clicked site in the browser with the same formula.

Evidence check: Pearson r between road distance to the nearest site and days to halve outages (ZIPs that reached half), and between distance and customer-days per customer. Both are near zero for Harvey, so the what-if claims only the travel-time saving, not shorter outages. Traffic and road-closure data would be needed to model actual drive times.

## What the longest outages had in common

Outage length per ZIP is customer-days without power (the sum of Harvey daily ZIP snapshots) divided by the ZIP's customers on its peak day. Each ZIP's traits are: Harvey NFIP claims per 1,000 customers (matched on `reportedZipCode`), the share of those claims in A or V flood zones, the average reported water depth, road distance to the nearest CenterPoint service center (from the staging what-if), customer count, and latitude. Rank (Spearman) correlation with average ranks for ties is the headline statistic, because ZIPs with under 500 customers produce extreme ratios; those ZIPs stay in the table but are left out of hotspot grouping. The fastest and slowest quarters are compared by medians (means for water depth, which is mostly whole numbers). Hotspots are slowest-quarter ZIPs grouped when their centroids are within 8 km, ranked by median outage length, and named after the worst-hit ZIP with a common area name. Each recommendation cites the statistic it rests on and page-cited report findings, and validation checks that every cited finding exists. These are associations within one storm, not causal estimates. Beryl has county-level outage data only, so its tree and vegetation recommendation rests on the reports.

Maps use Leaflet 1.9.4 (BSD-2, bundled in `dashboard/vendor/leaflet`) with Esri light-gray tiles, which need an internet connection; the data layers draw without it.

## Associations and reproducibility

The descriptive association file calculates Pearson r for (1) peak gust vs. observed peak customers out and (2) rainfall total vs. NFIP net payments. It contains per-storm results and an explicitly pooled result. Pairs with an unknown outcome are omitted and `n_county_storm_pairs` records the resulting sample size. Pooled county rows are not independent storms. Raw outage/claim counts are confounded by county exposure, utility reporting, and insurance participation. No p-values, prediction claims, causal claims, or population risk rankings are produced.

If prediction is added later, collect more independent storm labels, use entire storms as held-out groups, compare with a simple baseline, fit preprocessing on training data only, and restrict features to information available at the prediction time. Reanalysis, final tracks, subsequent claims, and realized full-storm peaks cannot be presented as pre-storm inputs.

Input fingerprints, processing rules, source-row references, output fingerprints, and validation results support auditing. Starter-source retrieval dates are unknown; the original upstream data were not independently re-downloaded. Source identity and weather units are attributed by the organizer brief. This is a reproducible analysis of those supplied extracts, not certification of their original collection process.
