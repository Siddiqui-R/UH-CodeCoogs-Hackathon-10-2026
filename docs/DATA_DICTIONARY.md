# Data dictionary

CSV blanks mean unknown or unavailable unless a field's definition says otherwise. Numeric zero is an observed or computed zero. Read five-digit FIPS as strings. All `source_row` references count CSV records starting with the header as record 1; they are record indices, not guaranteed physical line numbers for CSVs with quoted multiline fields.

## `county_storm_hour.csv`

Primary key: `(county_fips, storm_event, time_utc)`. Exactly one row per supplied county–storm weather hour. It has no claim totals.

| Columns | Type / unit | Definition |
| --- | --- | --- |
| `county_fips`, `county_name` | string | Five-digit FIPS and county name |
| `storm_event` | string | One of the four weather storm identifiers |
| `time_utc`, `time_local` | ISO 8601 | Start of the hourly interval; UTC Z and explicit local offset |
| `weather_point_latitude`, `weather_point_longitude` | degrees | County reference sampling point, WGS84 |
| `weather_source_row` | integer | Record in the root weather CSV |
| `temperature_c` | °C | 2m air temperature |
| `precipitation_in`, `rain_in` | inches/hour interval | Total precipitation and its rain component, respectively; do not add together |
| `surface_pressure_hpa` | hPa | Surface pressure |
| `wind_speed_10m_mph`, `wind_speed_100m_mph` | mph | Sustained wind at 10m and 100m |
| `wind_direction_deg` | degrees | 10m wind direction |
| `wind_gusts_10m_mph` | mph | Hourly 10m gust |
| `soil_moisture_m3_m3` | m³/m³ | Volumetric soil moisture at 0–7cm |
| `track_sid` | string | IBTrACS storm ID, explicitly mapped by storm and year |
| `track_status` | enum | `observed`, `center_interpolated_le_3h`, `outside_available_track`, or `track_gap_over_3h` |
| `track_latitude`, `track_longitude` | degrees | Available/interpolated storm-center coordinates |
| `track_distance_to_weather_point_km` | km | Haversine distance from the county reference point |
| `track_center_max_sustained_wind_kt` | knots | IBTrACS USA_WIND at the storm center; not local wind |
| `track_nearest_category` | numeric code | Nearest source USA_SSHS value; source values preserved; not interpolated |
| `track_source_row_before`, `track_source_row_after` | integer | Bracketing records in the root track CSV; same row for exact observations |
| `outage_observed_quarters`, `outage_expected_quarters` | integer | Usable source count and expected count (4) |
| `outage_record_presence_fraction` | fraction 0–1 | Usable source counts / 4; not verified customer coverage |
| `outage_customers_mean_observed` | customers | Mean over available snapshots only |
| `outage_customers_mean_complete_hour` | customers | Full-hour snapshot mean; blank unless all four counts exist |
| `outage_customers_peak_observed` | customers | Maximum available count within the hour |
| `outage_observed_sample_customer_hours` | customer-hours | 0.25 × sum of available snapshots; blank for no usable snapshots |
| `outage_status` | enum | `complete_source_hour`, `partial_source_hour`, `no_source_records` (no usable counts) |
| `outage_source_rows` | semicolon-separated integers | Records in `data/raw/houston_power_outages_15min_eaglei.csv` |
| `outage_geography` | string | Always `county_all_reporting_utilities` |

## `county_storm.csv`

Primary key: `(county_fips, storm_event)`. Twenty rows. All weather and outage summaries are limited to the supplied weather window. Claims use their own explicitly reported date window.

| Columns | Type / unit | Definition |
| --- | --- | --- |
| `county_fips`, `county_name`, `storm_event` | string | Shared keys and display name |
| `window_start_utc`, `window_end_utc_exclusive` | ISO 8601 UTC | Half-open weather/outage observation bounds |
| `weather_hours` | integer | Number of supplied hourly rows |
| `precipitation_observed_hours` | integer | Hours with a nonmissing precipitation value |
| `total_precipitation_in` | inches | Sum of total precipitation; blank if any hourly value is missing |
| `peak_wind_gust_mph` | mph | Maximum available reference-point gust |
| `min_track_distance_to_weather_point_km` | km | Closest available hourly center within the window |
| `track_covered_hours` | integer | Hours with valid storm-center distance |
| `outage_observed_quarters`, `outage_expected_quarters` | integer | Usable source counts and 4 × weather_hours |
| `outage_record_presence_fraction` | fraction 0–1 | Usable quarter-hour counts / expected quarter-hours |
| `outage_complete_hours` | integer | Hours with all four usable snapshots |
| `outage_peak_customers_observed` | customers | Largest available quarter-hour count |
| `outage_observed_sample_customer_hours` | customer-hours | Sum of observed-snapshot contributions, not gap-filled full-event burden |
| `recovery_duration_status` | string | Recovery duration intentionally not estimated |
| `nfip_recorded_claims` | integer | Assigned source records; not number of all damaged buildings |
| `nfip_building_payment_usd`, `nfip_contents_payment_usd` | nominal USD | Sum of populated net payment components from assigned claims |
| `nfip_building_payment_observed_claims`, `nfip_contents_payment_observed_claims` | integer | Claims with a populated component, including explicit zero |
| `nfip_total_net_payment_usd` | nominal USD | Sum of available building and contents component totals; blank if a whole component is unknown |
| `nfip_payment_missing_component_claims` | integer | Assigned claims lacking at least one net payment component |
| `nfip_loss_date_first`, `nfip_loss_date_last` | YYYY-MM-DD | Actual assigned record bounds; blank for no assigned records |
| `nfip_claim_window_start`, `nfip_claim_window_end` | YYYY-MM-DD | Explicit inclusive eligibility window |

## Harvey supplement tables

Harvey only. These are separate sources from EAGLE-I and NFIP and are never joined into the hourly or four-storm tables. Dates are calendar dates as published; the time of day of each outage snapshot is not stated.

**`harvey_county_supplement.csv`**: primary key `county_fips`; five study counties.

| Columns | Type / unit | Definition |
| --- | --- | --- |
| `zips_assigned` | integer | ZIP codes whose majority area is in the county |
| `report_days`, `first_report_date`, `last_report_date` | integer, YYYY-MM-DD | Days with at least one reporting ZIP |
| `zip_outage_peak_daily_count` | customers | Largest county daily sum of ZIP outage counts |
| `zip_outage_peak_date` | YYYY-MM-DD | Date of that sum |
| `zip_outage_peak_pct_of_reporting_customers` | percent | Peak sum / that day's reporting-ZIP customer total × 100 |
| `reporting_zip_customers_on_peak_date` | customers | Sum of `Total_Customers` across reporting ZIPs that day |
| `fema_affected_minor_total`, `fema_major_destroyed_total`, `fema_total_observations` | housing units | FEMA modeled damage counts (see below) |

**`harvey_county_outages_daily.csv`**: primary key `(county_fips, report_date)`; 45 rows. `zips_assigned`, `zips_reporting`, `split_zips_reporting` (integers); `outage_count_sum` and `reporting_zip_customers_sum` (customers, blank when no ZIP reported); `outage_pct_of_reporting_zip_customers` (percent); `zips_with_outages_exceeding_customers`; `geography` = `zip_codes_assigned_by_majority_area`.

**`harvey_zip_outages_daily.csv`**: primary key `(zip_code, report_date)`; 1,782 rows. `outage_count`, `total_customers` (customers, as published); `source_outage_pct` (published percent, capped at 100); `outages_exceed_customers` (flag; the record is kept); `study_county_fips` (blank when the ZIP's majority is outside the study counties); `majority_area_share`; `source_objectid` (geodatabase OBJECTID).

**`harvey_zip_county_assignments.csv`**: primary key `zip_code`; 198 rows. `sampled_centroid_longitude/latitude` (degrees, mean of sampled interior points); `area_samples` (interior grid points; 0 means a sliver fell back to its first vertex); `majority_county_fips/name` (any of the nine supplied counties, blank if outside all of them); `majority_area_share` (0–1); `split_across_counties` (true when the share is below 0.9); `other_area_shares` (`fips:share` pairs, `outside` for area beyond the supplied counties); `study_county_fips`; `assignment_reason` (`majority_area_in_study_county`, `majority_in_county_outside_study`, `majority_outside_supplied_county_boundaries`).

**`harvey_fema_damage_assessments.csv`**: primary key `county_fips`; eight counties with an `in_study_counties` flag. Housing-unit counts `fema_affected_minor_*` and `fema_major_destroyed_*` for `100yr_floodplain`, `500yr_floodplain`, and `outside_floodplain`; their two totals; `fema_total_observations` (equals the sum of the six categories); `source_objectid`. Modeled assessments, not claims or dollars.

## Supporting tables

- **CenterPoint milestones:** `storm_event`; `report_time_local` (UTC−05:00) and `report_time_utc`; `metric` (`customers_restored` or `percent_impacted_restored`); `reported_value` in customers or percent according to metric; `qualifier` (`greater_than`, `nearly`, `reported_rounded`); `geography`; blank `county_fips`; `status`; `timestamp_meaning`; exact short `source_phrase`; `source_url`. The numeric value must always be interpreted with its qualifier.
- **Claim assignments:** `source_row` in the root FEMA CSV, `county_fips`, calendar `date_of_loss`, `source_event_label`, `assigned_storm_event` (blank for excluded), and `assignment_reason`. Reasons distinguish blank labels, other named events, wrong years, out-of-window dates, and counties outside scope.
- **Excluded outages:** `source_row` in the raw extracted outage CSV, `county_fips`, `time_utc` (original UTC serialization), `reason`. These records remain in the raw source extract.
- **Descriptive associations:** `storm_event` (or `all_four_storms`), `x` and `y` column names from the event summary, `n_county_storm_pairs`, `pearson_r` (blank when undefined), and `interpretation`. No p-values or confidence intervals are implied.
- **Raw outage extract:** `fips_code`, `county`, `state`, `customers_out`, `run_start_time` (UTC), `total_customers` (preserved where supplied, not used as a denominator), `storm_event`, and official Figshare `source_file_id`. The 2024 source denominator has not been independently validated.
- **County boundaries:** GeoJSON `FeatureCollection`, subset from the organizer file; `properties.id` is the FIPS join key. Existing Census properties and polygons are preserved.

The source manifest links file fingerprints and provenance status to the original provider. The processing manifest captures exact storm windows, payment field choices, units, code fingerprints, and derived output fingerprints. The validation report exposes limitations and acquisition/assignment counts.
