from django.urls import path
from .views import chat_home_view, drawer_meta_view, drawer_augments_view, drawer_mechanics_view

app_name = "core"

urlpatterns = [
    path("", chat_home_view, name="home"),
    path("drawers/meta/", drawer_meta_view, name="drawer_meta"),
    path("drawers/augments/", drawer_augments_view, name="drawer_augments"),
    path("drawers/mechanics/", drawer_mechanics_view, name="drawer_mechanics"),
]
