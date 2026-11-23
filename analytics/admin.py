from django.contrib import admin

from .models import CrimeCategory, CrimeRecord, Period, Population, Province


@admin.register(Province)
class ProvinceAdmin(admin.ModelAdmin):
    search_fields = ["name"]


@admin.register(Period)
class PeriodAdmin(admin.ModelAdmin):
    list_display = ["__str__", "period_start", "period_end", "source"]


@admin.register(CrimeCategory)
class CrimeCategoryAdmin(admin.ModelAdmin):
    list_display = ["name", "level", "parent", "crime_group", "counts_in_total"]
    list_filter = ["level", "counts_in_total", "crime_group"]
    search_fields = ["name"]


@admin.register(Population)
class PopulationAdmin(admin.ModelAdmin):
    list_display = ["province", "year", "population"]
    list_filter = ["year", "province"]


@admin.register(CrimeRecord)
class CrimeRecordAdmin(admin.ModelAdmin):
    list_display = ["province", "category", "period", "incidents"]
    list_filter = ["period", "province", "category__level"]
    search_fields = ["category__name"]
    list_select_related = ["province", "category", "period"]  # avoids one query per row
    list_per_page = 50
