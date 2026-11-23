from rest_framework import serializers


class FilterSerializer(serializers.Serializer):
    """Checks the ?province=...&period=...&scope=... part of a URL.

    DRF does the validation for us: a bad value becomes a clean 400 error
    instead of crashing the server (the old code crashed on ?year=abc).
    """

    province = serializers.CharField(required=False, allow_blank=True)
    period = serializers.IntegerField(required=False, min_value=1)
    scope = serializers.ChoiceField(choices=["community", "all"], default="community")
