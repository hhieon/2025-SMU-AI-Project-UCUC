from django.urls import path
from . import views

urlpatterns = [
    path("guide/", views.guide_view, name="guide"),
    path("guide/ics/", views.guide_ics_download, name="guide_ics"),
    path("photo/", views.photo_view, name="photo"),
    path("photo/ask/", views.photo_qa_view, name="photo_ask"),
    path("translate/", views.translate_view, name="translate"),
    path("planner/", views.planner_view, name="planner"),
    path("planner/ics/", views.planner_ics_download, name="planner_ics"),
]