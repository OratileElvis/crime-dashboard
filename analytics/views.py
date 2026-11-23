from django.shortcuts import render
from rest_framework.decorators import api_view
from rest_framework.response import Response

from . import services
from .models import Period, Province


def dashboard(request):
    """The page itself. All data arrives afterwards from the API below."""
    return render(request, "analytics/dashboard.html")


@api_view(["GET"])
def meta(request):
    """What the dropdowns need: provinces and periods that actually exist in the database."""
    periods = list(Period.objects.order_by("period_start"))
    return Response(
        {
            "provinces": list(Province.objects.values_list("name", flat=True)),
            "periods": [
                {
                    "id": p.id,
                    "label": services.period_label(p),
                    "fy_quarter": p.fy_quarter,
                }
                for p in periods
            ],
            "latest_period_id": periods[-1].id if periods else None,
        }
    )


@api_view(["GET"])
def crime_summary(request):
    """Total incidents per crime type for the chosen period and province."""
    f = services.get_filters(request)
    records = services.scoped_records(f.scope, f.period, f.province)
    return Response(
        [
            {
                "category": row["category__name"],
                "group": row["category__crime_group"],
                "incidents": row["total"],
            }
            for row in services.category_totals(records)
        ]
    )


@api_view(["GET"])
def crime_trends(request):
    """Year-on-year totals for the same season as the chosen period."""
    f = services.get_filters(request)
    quarter = f.period.fy_quarter
    rows = services.same_quarter_totals(f.scope, f.province, quarter)
    return Response(
        {
            "season": services.QUARTER_MONTHS[quarter],
            "points": [
                {
                    "period_id": row["period_id"],
                    "label": f"{services.QUARTER_MONTHS[quarter]} {row['period__period_start'].year}",
                    "total": row["total"],
                }
                for row in rows
            ],
        }
    )


@api_view(["GET"])
def crime_insights(request):
    """The headline cards: total, top crime, change on last year, murder rate."""
    f = services.get_filters(request)
    records = services.scoped_records(f.scope, f.period, f.province)

    total = services.total_incidents(records)
    top = services.category_totals(records).first()

    change_pct, compared_to = None, None
    previous = services.previous_year_period(f.period)
    if previous is not None:
        previous_total = services.total_incidents(
            services.scoped_records(f.scope, previous, f.province)
        )
        if previous_total:
            change_pct = round((total - previous_total) / previous_total * 100, 1)
            compared_to = services.period_label(previous)

    return Response(
        {
            "period": services.period_label(f.period),
            "province": f.province.name if f.province else "All provinces",
            "scope": f.scope,
            "total_incidents": total,
            "top_category": top["category__name"] if top else None,
            "change_pct": change_pct,
            "compared_to": compared_to,
            "murder_rate_per_100k": services.murder_rate_per_100k(f.period, f.province),
            # Population figures are SAPS's April-June estimates, so for other
            # quarters the rate is an approximation.
            "rate_is_approximate": f.period.period_start.month != 4,
        }
    )
