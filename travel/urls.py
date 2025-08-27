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
    path('planner/save/', views.planner_save_api, name='planner_save_api'),
    path("diary/", views.diary_list, name="diary_list"),
    path("diary/new/", views.diary_create, name="diary_create"),
    path("diary/<int:pk>/", views.diary_detail, name="diary_detail"),  # 상세 페이지
    path("diary/delete/", views.diary_delete, name="diary_delete"),
    path("chatbot/", views.chatbot, name="chatbot"),
]