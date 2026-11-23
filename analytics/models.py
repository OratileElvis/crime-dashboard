from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import F, Q


class Province(models.Model):
    """One of South Africa's nine provinces."""

    name = models.CharField(max_length=100, unique=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Period(models.Model):
    """A reporting quarter, e.g. Apr-Jun 2026 = financial year 2026/27, quarter 1.

    SAPS reports by financial year (April to March), so Q1 = Apr-Jun,
    Q2 = Jul-Sep, Q3 = Oct-Dec, Q4 = Jan-Mar.
    """

    period_start = models.DateField(unique=True)
    period_end = models.DateField()
    financial_year = models.CharField(max_length=7)  # e.g. "2026/27"
    fy_quarter = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(4)]
    )
    source = models.CharField(max_length=200)  # which SAPS release this came from

    class Meta:
        ordering = ["period_start"]
        constraints = [
            models.UniqueConstraint(
                fields=["financial_year", "fy_quarter"],
                name="uniq_period_fy_quarter",
            ),
            models.CheckConstraint(
                condition=Q(period_end__gte=F("period_start")),
                name="period_end_after_start",
            ),
        ]

    def __str__(self):
        return f"{self.financial_year} Q{self.fy_quarter}"


class CrimeCategory(models.Model):
    """A crime type OR a subtotal that SAPS publishes alongside it.

    SAPS mixes individual crimes with subtotals (e.g. "Contact crime" is the sum
    of Murder, Rape, ...). Adding everything together double counts.
    `counts_in_total` marks the rows that are safe to add up.
    """

    class Level(models.TextChoices):
        HEADLINE_TOTAL = "headline_total", "Headline total"
        GROUP_TOTAL = "group_total", "Group total"
        SUBTOTAL = "subtotal", "Subtotal"
        CRIME = "crime", "Crime"
        BREAKDOWN = "breakdown", "Breakdown of a crime"
        CRIME_OTHER = "crime_other", "Other crime (outside headline groups)"

    name = models.CharField(max_length=150, unique=True)
    level = models.CharField(max_length=20, choices=Level.choices)
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="children",
    )
    crime_group = models.CharField(max_length=60, blank=True)
    counts_in_total = models.BooleanField(default=False)
    in_prior_schema = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "crime categories"

    def __str__(self):
        return self.name


class Population(models.Model):
    """Mid-year population estimate per province, used for per-100,000 rates."""

    province = models.ForeignKey(
        Province, on_delete=models.PROTECT, related_name="populations"
    )
    year = models.PositiveSmallIntegerField()
    population = models.PositiveIntegerField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["province", "year"],
                name="uniq_population_province_year",
            ),
        ]

    def __str__(self):
        return f"{self.province} {self.year}: {self.population:,}"


class CrimeRecordQuerySet(models.QuerySet):
    def additive(self):
        """Only rows that can be safely summed (no subtotals, no double counting)."""
        return self.filter(category__counts_in_total=True)


class CrimeRecord(models.Model):
    """Number of incidents of one crime, in one province, in one quarter."""

    province = models.ForeignKey(
        Province, on_delete=models.PROTECT, related_name="records"
    )
    category = models.ForeignKey(
        CrimeCategory, on_delete=models.PROTECT, related_name="records"
    )
    period = models.ForeignKey(
        Period, on_delete=models.PROTECT, related_name="records"
    )
    incidents = models.PositiveIntegerField()

    objects = CrimeRecordQuerySet.as_manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["province", "category", "period"],
                name="uniq_record_province_category_period",
            ),
        ]
        indexes = [
            models.Index(fields=["period", "category"]),
        ]

    def __str__(self):
        return f"{self.province} | {self.category} | {self.period}: {self.incidents}"
