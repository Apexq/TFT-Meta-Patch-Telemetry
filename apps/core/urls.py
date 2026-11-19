from django.urls import path
from .views import (
    chat_home_view,
    drawer_meta_view,
    drawer_augments_view,
    drawer_mechanics_view,
    drawer_pbe_view,
    health_check_view,
)

app_name = "core"

urlpatterns = [
    path("", chat_home_view, name="home"),
    path("health/", health_check_view, name="health"),
    path("drawers/meta/", drawer_meta_view, name="drawer_meta"),
    path("drawers/augments/", drawer_augments_view, name="drawer_augments"),
    path("drawers/mechanics/", drawer_mechanics_view, name="drawer_mechanics"),
    path("drawers/pbe/", drawer_pbe_view, name="drawer_pbe"),
]
