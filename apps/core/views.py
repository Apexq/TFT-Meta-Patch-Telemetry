from django.http import JsonResponse
from django.shortcuts import render


def index_view(request):
    """Placeholder view for initial setup verification."""
    return JsonResponse({"status": "ok", "app": "TFT Set 18 AI Coach & Meta Platform", "version": "v2"})
