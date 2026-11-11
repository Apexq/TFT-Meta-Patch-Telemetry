"""
ASGI config for TFT Set 18 AI Coach (Server-Sent Events / Streaming support).
"""

import os
from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

application = get_asgi_application()
