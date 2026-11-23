from django.urls import path

from . import views

app_name = "analytics_api"

urlpatterns = [
    path("meta/", views.meta, name="meta"),
    path("crime-summary/", views.crime_summary, name="crime-summary"),
    path("crime-trends/", views.crime_trends, name="crime-trends"),
    path("crime-insights/", views.crime_insights, name="crime-insights"),
]
