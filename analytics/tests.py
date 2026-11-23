import datetime
from pathlib import Path
from unittest import skipUnless

from django.conf import settings
from django.core.management import call_command
from django.urls import reverse
from rest_framework.test import APITestCase

from .models import CrimeCategory, CrimeRecord, Period, Population, Province


class ApiRulesTests(APITestCase):
    """Small, hand-made data set so every expected number can be checked by eye."""

    @classmethod
    def setUpTestData(cls):
        cls.gp = Province.objects.create(name="Gauteng")
        cls.wc = Province.objects.create(name="Western Cape")

        cls.last_year = Period.objects.create(
            period_start=datetime.date(2025, 4, 1), period_end=datetime.date(2025, 6, 30),
            financial_year="2025/26", fy_quarter=1, source="test",
        )
        cls.this_year = Period.objects.create(
            period_start=datetime.date(2026, 4, 1), period_end=datetime.date(2026, 6, 30),
            financial_year="2026/27", fy_quarter=1, source="test",
        )
        cls.other_season = Period.objects.create(
            period_start=datetime.date(2025, 7, 1), period_end=datetime.date(2025, 9, 30),
            financial_year="2025/26", fy_quarter=2, source="test",
        )

        subtotal = CrimeCategory.objects.create(
            name="Contact crime (subtotal)", level="group_total", counts_in_total=False)
        murder = CrimeCategory.objects.create(
            name="Murder", level="crime", parent=subtotal,
            crime_group="Contact crime", counts_in_total=True)
        burglary = CrimeCategory.objects.create(
            name="Burglary", level="crime",
            crime_group="Property-related crime", counts_in_total=True)
        drugs = CrimeCategory.objects.create(
            name="Drug-related crime", level="crime",
            crime_group="Detected by police action", counts_in_total=True)

        def add(province, category, period, n):
            CrimeRecord.objects.create(province=province, category=category, period=period, incidents=n)

        # last year: Gauteng murder 10, burglary 90 (community total 100)
        add(cls.gp, murder, cls.last_year, 10)
        add(cls.gp, burglary, cls.last_year, 90)
        # this year: Gauteng murder 12, burglary 108 (community total 120), drugs 500, subtotal 120
        add(cls.gp, murder, cls.this_year, 12)
        add(cls.gp, burglary, cls.this_year, 108)
        add(cls.gp, drugs, cls.this_year, 500)
        add(cls.gp, subtotal, cls.this_year, 120)
        add(cls.wc, murder, cls.this_year, 8)
        # a different season, which must never appear in the Apr-Jun trend
        add(cls.gp, murder, cls.other_season, 99)

        Population.objects.create(province=cls.gp, year=2026, population=1000)
        Population.objects.create(province=cls.wc, year=2026, population=1000)

    def get(self, name, **params):
        return self.client.get(reverse(f"analytics_api:{name}"), params)

    def test_subtotals_are_never_in_the_summary(self):
        names = [row["category"] for row in self.get("crime-summary", province="Gauteng").json()]
        self.assertNotIn("Contact crime (subtotal)", names)

    def test_default_scope_excludes_police_detected_crime(self):
        names = [row["category"] for row in self.get("crime-summary", province="Gauteng").json()]
        self.assertNotIn("Drug-related crime", names)
        names_all = [r["category"] for r in self.get("crime-summary", province="Gauteng", scope="all").json()]
        self.assertIn("Drug-related crime", names_all)

    def test_total_is_not_double_counted(self):
        data = self.get("crime-insights", province="Gauteng").json()
        self.assertEqual(data["total_incidents"], 120)  # not 240 (subtotal) or 620 (drugs)

    def test_change_is_against_the_same_season_last_year(self):
        data = self.get("crime-insights", province="Gauteng").json()
        self.assertEqual(data["change_pct"], 20.0)  # 100 -> 120
        self.assertIn("2025/26 Q1", data["compared_to"])

    def test_no_comparison_when_previous_year_missing(self):
        data = self.get("crime-insights", period=self.other_season.id).json()
        self.assertIsNone(data["change_pct"])

    def test_trend_only_contains_the_same_season(self):
        points = self.get("crime-trends", province="Gauteng").json()["points"]
        self.assertEqual([p["total"] for p in points], [100, 120])  # the 99 is Jul-Sep

    def test_murder_rate_per_100k(self):
        data = self.get("crime-insights", province="Gauteng").json()
        self.assertEqual(data["murder_rate_per_100k"], 1200.0)  # 12 / 1000 * 100,000
        self.assertFalse(data["rate_is_approximate"])

    def test_bad_input_gets_clean_errors(self):
        self.assertEqual(self.get("crime-summary", province="Atlantis").status_code, 404)
        self.assertEqual(self.get("crime-summary", period=9999).status_code, 404)
        self.assertEqual(self.get("crime-summary", scope="nonsense").status_code, 400)
        self.assertEqual(self.get("crime-summary", period="abc").status_code, 400)

    def test_meta_lists_what_exists(self):
        data = self.get("meta").json()
        self.assertEqual(data["provinces"], ["Gauteng", "Western Cape"])
        self.assertEqual(data["latest_period_id"], self.this_year.id)


@skipUnless((Path(settings.BASE_DIR) / "data").exists(), "data/ folder not found")
class RealDataTests(APITestCase):
    """Loads your real SAPS files and checks them against SAPS's published figures."""

    @classmethod
    def setUpTestData(cls):
        call_command("import_crime_stats", verbosity=0)

    def get(self, name, **params):
        return self.client.get(reverse(f"analytics_api:{name}"), params).json()

    def test_import_loaded_everything(self):
        self.assertEqual(CrimeRecord.objects.count(), 2331)
        self.assertEqual(Period.objects.count(), 6)

    def test_community_total_matches_sapss_own_17_crime_figure(self):
        """The dashboard total must equal the number SAPS publishes (339,395 for Apr-Jun 2026)."""
        data = self.get("crime-insights")
        self.assertEqual(data["total_incidents"], 339_395)

    def test_national_murder_rate_matches_published_ratio(self):
        self.assertEqual(self.get("crime-insights")["murder_rate_per_100k"], 8.5)

    def test_gauteng_murder_rate_matches_published_ratio(self):
        self.assertEqual(self.get("crime-insights", province="Gauteng")["murder_rate_per_100k"], 7.4)

    def test_top_crime_is_a_real_crime_not_a_subtotal(self):
        top = self.get("crime-insights")["top_category"]
        self.assertNotIn("Contact crime (Crimes against the person)", top)
        self.assertEqual(top, "All theft not mentioned elsewhere")

    def test_aprjun_trend_has_five_years(self):
        self.assertEqual(len(self.get("crime-trends")["points"]), 5)
