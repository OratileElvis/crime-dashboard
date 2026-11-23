"""The 'business logic' of the dashboard: all the database questions live here.

Views stay thin (read the URL, call a function here, return JSON) and this
module is the only place that decides what counts as a "total".
"""
from collections import namedtuple

from django.db.models import Sum
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import NotFound

from .models import CrimeRecord, Period, Population, Province
from .serializers import FilterSerializer

# SAPS's headline measure: the "17 community-reported serious crimes" are made of
# these four groups. Crimes detected by police action (e.g. drug offences) and
# kidnapping are published separately, so they are left out of the default scope.
COMMUNITY_GROUPS = (
    "Contact crime",
    "Contact-related crime",
    "Property-related crime",
    "Other serious crime",
)

QUARTER_MONTHS = {1: "Apr–Jun", 2: "Jul–Sep", 3: "Oct–Dec", 4: "Jan–Mar"}

Filters = namedtuple("Filters", "province period scope")


def period_label(period):
    months = QUARTER_MONTHS[period.fy_quarter]
    return f"{months} {period.period_start.year} (FY {period.financial_year} Q{period.fy_quarter})"


def get_filters(request):
    """Read and validate the URL parameters. Defaults to the latest period."""
    serializer = FilterSerializer(data=request.query_params)
    serializer.is_valid(raise_exception=True)  # bad input -> HTTP 400
    data = serializer.validated_data

    province = None
    if data.get("province"):
        province = get_object_or_404(Province, name=data["province"])  # unknown -> 404

    if data.get("period"):
        period = get_object_or_404(Period, pk=data["period"])
    else:
        period = Period.objects.order_by("-period_start").first()
        if period is None:
            raise NotFound("No data loaded yet. Run: python manage.py import_crime_stats")

    return Filters(province=province, period=period, scope=data["scope"])


def scoped_records(scope, period=None, province=None):
    """The rows that are safe to add together, narrowed by the chosen filters."""
    records = CrimeRecord.objects.additive()  # never subtotals -> no double counting
    if scope == "community":
        records = records.filter(category__crime_group__in=COMMUNITY_GROUPS)
    if period is not None:
        records = records.filter(period=period)
    if province is not None:
        records = records.filter(province=province)
    return records


def total_incidents(records):
    return records.aggregate(total=Sum("incidents"))["total"] or 0


def category_totals(records):
    """One query: total per crime, biggest first."""
    return (
        records.values("category__name", "category__crime_group")
        .annotate(total=Sum("incidents"))
        .order_by("-total", "category__name")
    )


def same_quarter_totals(scope, province, fy_quarter):
    """Total per year for ONE season (e.g. every Apr-Jun), oldest first.

    Comparing like with like matters: crime has a seasonal pattern, so a line
    that jumps from Apr-Jun to Jul-Sep would mix seasonality with real change.
    """
    records = scoped_records(scope, province=province).filter(period__fy_quarter=fy_quarter)
    return (
        records.values("period_id", "period__period_start")
        .annotate(total=Sum("incidents"))
        .order_by("period__period_start")
    )


def previous_year_period(period):
    """The same season one year earlier (Apr-Jun 2026 -> Apr-Jun 2025), if loaded."""
    start = period.period_start
    return Period.objects.filter(period_start=start.replace(year=start.year - 1)).first()


def murder_rate_per_100k(period, province):
    """Murders per 100,000 people, using SAPS's own population estimates."""
    murders = CrimeRecord.objects.filter(period=period, category__name="Murder")
    people = Population.objects.filter(year=period.period_start.year)
    if province is not None:
        murders = murders.filter(province=province)
        people = people.filter(province=province)
    murder_count = murders.aggregate(t=Sum("incidents"))["t"]
    population = people.aggregate(t=Sum("population"))["t"]
    if murder_count is None or not population:
        return None
    return round(murder_count / population * 100_000, 1)
