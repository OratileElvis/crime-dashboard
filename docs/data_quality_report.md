# SAPS crime data: cleaning and validation report

**Sources**
- `2026-2027_-_1st_Quarter_WEB.xlsm`: SAPS Q1 2026/27 (Apr-Jun 2026) workbook. Hidden sheet `RAW Data` holds station, district, province and national rows for Apr-Jun 2022-2026, by month.
- `cleaned_stats_sa_crime_2025_q2.csv`: your earlier file. It is SAPS Q2 2025/26 (Jul-Sep 2025), not a calendar year.

**What was done**
- Used the official province-level rows (9 provinces x 44 categories x 5 years). National rows are used only for checks and are NOT in the output, so nothing is double counted.
- Dropped about 1,250 stray rows below the data (leftover lookup/"BAD PERFORMERS" cells with no category).
- Normalised category capitalisation to match your earlier CSV ("Property-related Crime" -> "Property-related crime", and so on).
- Converted quarter and month figures to integers; replaced the loose "year" with period_start, period_end, financial_year and fy_quarter.
- Added your Jul-Sep 2025 file in the same shape, so the database holds 6 periods: Apr-Jun 2022-2026 plus Jul-Sep 2025.
- Macros in the .xlsm were not executed. Only cell values were read.

**Checks (all passed)**
- Quarter total = Apr + May + Jun for every row; no nulls, negatives or non-integers.
- Station, district and province totals agree; province totals = national, 2022-2025 exactly.
- 432 hierarchy checks (parent = sum of children, per province, per period): 0 failures.
- Additive total (counts_in_total = True) = 17 community-reported + police-action + kidnapping, every period and province.
- 18 per-100k figures (murder, rape x 9 provinces) reproduce SAPS's published ratios using province_population.csv.
- National murder, 17 community-reported, contact crime, property-related, carjacking, drug-related, kidnapping, rape and police-action totals match the published Q1 2026/27 deck.

**Issues found in the source**
1. Station-level 2026 rows: station "Tafalehashe" is tagged City of Cape Town / Western Cape, but its figures are counted in Amathole District / Eastern Cape in the district and province rows. That is 57 of the 17 community-reported crimes. It does not affect these province files (they use the province rows, which match the deck). Fix or exclude it if you later load station-level data.
2. Category names are inconsistent in capitalisation (fixed above), and the "Count offence group" column mixes 0, "17 Community reported serious crime" and "17 Community reported serious Crime" (not used).
3. Five categories exist here that are not in your earlier file: Culpable homicide, Public violence, Crimen injuria, Neglect and ill-treatment of children, Abduction. They are loaded with in_prior_schema = False and counts_in_total = False.

**Cautions for the database and dashboard**
- Periods are NOT all the same season (Apr-Jun vs Jul-Sep). Compare year on year for the same fy_quarter only.
- Prior-year figures in SAPS releases can be restated. Keep the `source` column and never silently overwrite.
- Population in province_population.csv is SAPS's Apr-Jun (mid-May) estimate for 2022-2026. There is no population in this workbook for Jul-Sep 2025, so per-100k for that quarter needs an estimate from Stats SA.
- Use counts_in_total = True rows (25 crimes) for any "total incidents" figure. Subtotals, breakdowns and the headline 17-crime total are for drill-down only.
