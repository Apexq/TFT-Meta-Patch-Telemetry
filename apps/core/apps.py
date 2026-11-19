from django.apps import AppConfig


def _configure_sqlite_wal(sender, connection, **kwargs):
    """Enable SQLite Write-Ahead Logging (WAL) for concurrent ASGI streaming reads/writes."""
    if connection.vendor == "sqlite":
        with connection.cursor() as cursor:
            cursor.execute("PRAGMA journal_mode=WAL;")
            cursor.execute("PRAGMA synchronous=NORMAL;")
            cursor.execute("PRAGMA busy_timeout=5000;")


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.core"
    verbose_name = "Çekirdek Sistem"

    def ready(self):
        from django.db.backends.signals import connection_created
        connection_created.connect(_configure_sqlite_wal, dispatch_uid="core_configure_sqlite_wal")
