"""Load the cleaned SAPS crime CSVs from the project's data/ folder into the database.

Usage (run from the folder that contains manage.py):

    python manage.py import_crime_stats --dry-run   # test everything, save nothing
    python manage.py import_crime_stats             # load for real

It is safe to run more than once: existing rows are updated, not duplicated.
If anything is wrong (bad number, unknown category, a subtotal that does not
equal the sum of its parts) the whole import is cancelled and nothing is saved.
"""
import csv
import datetime
from collections import defaultdict
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from analytics.models import (
    CrimeCategory,
    CrimeRecord,
    Period,
    Population,
    Province,
)

# Categories that SAPS publishes as a total of other categories.
# For these, the number must equal the sum of their children.
SUBTOTAL_LEVELS = {
    CrimeCategory.Level.HEADLINE_TOTAL.value,
    CrimeCategory.Level.GROUP_TOTAL.value,
    CrimeCategory.Level.SUBTOTAL.value,
}


def read_csv(path, required_columns):
    """Read a CSV into a list of (line_number, row_dict), trimming whitespace."""
    if not path.exists():
        raise CommandError(f"Missing file: {path}")
    # utf-8-sig quietly handles the invisible marker Excel sometimes adds
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        missing = set(required_columns) - set(reader.fieldnames or [])
        if missing:
            raise CommandError(f"{path.name} is missing column(s): {sorted(missing)}")
        return [
            (line, {k: (v or "").strip() for k, v in row.items()})
            for line, row in enumerate(reader, start=2)  # line 1 is the header
        ]


def to_bool(value, where):
    if value.lower() in ("true", "1"):
        return True
    if value.lower() in ("false", "0"):
        return False
    raise CommandError(f"{where}: expected True/False but found '{value}'")


def to_int(value, where):
    try:
        number = int(value)
    except ValueError:
        raise CommandError(f"{where}: '{value}' is not a whole number")
    if number < 0:
        raise CommandError(f"{where}: {number} is negative")
    return number


def to_date(value, where):
    try:
        return datetime.date.fromisoformat(value)
    except ValueError:
        raise CommandError(f"{where}: '{value}' is not a date like 2026-04-01")


class Command(BaseCommand):
    help = "Import the cleaned SAPS provincial crime statistics from the data/ folder."

    def add_arguments(self, parser):
        parser.add_argument(
            "--data-dir",
            help="Folder with the CSV files (default: <project>/data)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Run all checks, then undo everything instead of saving",
        )

    def handle(self, *args, **options):
        data_dir = (
            Path(options["data_dir"])
            if options["data_dir"]
            else Path(settings.BASE_DIR) / "data"
        )

        category_rows = read_csv(
            data_dir / "crime_category_map.csv",
            ["category", "level", "parent_category", "crime_group",
             "counts_in_total", "in_prior_schema"],
        )
        population_rows = read_csv(
            data_dir / "province_population.csv",
            ["year", "province", "population"],
        )
        record_rows = read_csv(
            data_dir / "saps_provincial_quarterly_clean.csv",
            ["period_start", "period_end", "financial_year", "fy_quarter",
             "province", "category", "incidents", "source"],
        )

        # atomic = all-or-nothing: if any step fails, nothing is saved
        with transaction.atomic():
            provinces = self.load_provinces(population_rows, record_rows)
            categories = self.load_categories(category_rows)
            periods = self.load_periods(record_rows)
            self.load_population(population_rows, provinces)
            self.load_records(record_rows, provinces, categories, periods)
            checks = self.check_subtotals()

            if options["dry_run"]:
                transaction.set_rollback(True)

        summary = (
            f"Provinces: {len(provinces)} | Categories: {len(categories)} | "
            f"Periods: {len(periods)} | Population rows: {len(population_rows)} | "
            f"Crime records: {len(record_rows)}"
        )
        self.stdout.write(summary)
        self.stdout.write(f"Subtotal check: {checks} comparisons, all matched.")
        if options["dry_run"]:
            self.stdout.write(self.style.WARNING("DRY RUN: nothing was saved."))
        else:
            self.stdout.write(self.style.SUCCESS("Import complete."))

    # ---------- step 1: provinces ----------
    def load_provinces(self, population_rows, record_rows):
        names = {row["province"] for _, row in population_rows}
        names |= {row["province"] for _, row in record_rows}
        return {
            name: Province.objects.get_or_create(name=name)[0]
            for name in sorted(names)
        }

    # ---------- step 2: categories (two passes) ----------
    def load_categories(self, category_rows):
        valid_levels = set(CrimeCategory.Level.values)
        by_name = {}

        # Pass 1: create every category, without parents yet
        for line, row in category_rows:
            where = f"crime_category_map.csv line {line}"
            if row["level"] not in valid_levels:
                raise CommandError(f"{where}: unknown level '{row['level']}'")
            by_name[row["category"]], _ = CrimeCategory.objects.update_or_create(
                name=row["category"],
                defaults={
                    "level": row["level"],
                    "crime_group": row["crime_group"],
                    "counts_in_total": to_bool(row["counts_in_total"], where),
                    "in_prior_schema": to_bool(row["in_prior_schema"], where),
                },
            )

        # Pass 2: now every category exists, so parents can be linked
        for line, row in category_rows:
            parent_name = row["parent_category"]
            if parent_name and parent_name not in by_name:
                raise CommandError(
                    f"crime_category_map.csv line {line}: parent '{parent_name}' not found"
                )
            parent = by_name[parent_name] if parent_name else None
            category = by_name[row["category"]]
            if category.parent_id != (parent.id if parent else None):
                category.parent = parent
                category.save(update_fields=["parent"])
        return by_name

    # ---------- step 3: periods ----------
    def load_periods(self, record_rows):
        wanted = {}
        for line, row in record_rows:
            where = f"quarterly csv line {line}"
            details = {
                "period_end": to_date(row["period_end"], where),
                "financial_year": row["financial_year"],
                "fy_quarter": to_int(row["fy_quarter"], where),
                "source": row["source"],
            }
            start = to_date(row["period_start"], where)
            if start in wanted and wanted[start] != details:
                raise CommandError(f"{where}: period {start} has conflicting details")
            wanted[start] = details
        return {
            start: Period.objects.update_or_create(period_start=start, defaults=d)[0]
            for start, d in sorted(wanted.items())
        }

    # ---------- step 4: population ----------
    def load_population(self, population_rows, provinces):
        for line, row in population_rows:
            where = f"province_population.csv line {line}"
            Population.objects.update_or_create(
                province=provinces[row["province"]],
                year=to_int(row["year"], where),
                defaults={"population": to_int(row["population"], where)},
            )

    # ---------- step 5: the crime numbers ----------
    def load_records(self, record_rows, provinces, categories, periods):
        records, seen = [], set()
        for line, row in record_rows:
            where = f"quarterly csv line {line}"
            if row["category"] not in categories:
                raise CommandError(f"{where}: unknown category '{row['category']}'")
            start = to_date(row["period_start"], where)
            key = (start, row["province"], row["category"])
            if key in seen:
                raise CommandError(f"{where}: duplicate row for {key}")
            seen.add(key)
            records.append(
                CrimeRecord(
                    province=provinces[row["province"]],
                    category=categories[row["category"]],
                    period=periods[start],
                    incidents=to_int(row["incidents"], where),
                )
            )
        # update_conflicts: if the row already exists, update it instead of failing
        CrimeRecord.objects.bulk_create(
            records,
            batch_size=500,
            update_conflicts=True,
            unique_fields=["province", "category", "period"],
            update_fields=["incidents"],
        )

    # ---------- step 6: does every subtotal equal the sum of its parts? ----------
    def check_subtotals(self):
        children = defaultdict(list)
        for cat_id, parent_id in CrimeCategory.objects.exclude(
            parent=None
        ).values_list("id", "parent_id"):
            children[parent_id].append(cat_id)

        subtotal_ids = set(
            CrimeCategory.objects.filter(level__in=SUBTOTAL_LEVELS).values_list(
                "id", flat=True
            )
        )
        values = {
            (period, province, category): incidents
            for period, province, category, incidents in CrimeRecord.objects.values_list(
                "period_id", "province_id", "category_id", "incidents"
            )
        }

        problems, checks = [], 0
        for (period, province, category), total in values.items():
            if category not in subtotal_ids:
                continue
            checks += 1
            parts = [values.get((period, province, child)) for child in children[category]]
            if None in parts or sum(parts) != total:
                problems.append((period, province, category, total, parts))

        if problems:
            names = dict(CrimeCategory.objects.values_list("id", "name"))
            lines = [
                f"  {Province.objects.get(id=pr)} | {Period.objects.get(id=pe)} | "
                f"{names[ca]}: published {tot}, parts add up to "
                f"{'(missing part)' if None in parts else sum(parts)}"
                for pe, pr, ca, tot, parts in problems[:10]
            ]
            raise CommandError(
                f"{len(problems)} subtotal(s) do not match their parts. "
                "Nothing was saved.\n" + "\n".join(lines)
            )
        return checks
