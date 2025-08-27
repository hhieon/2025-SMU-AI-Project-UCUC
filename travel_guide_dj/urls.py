from django.contrib import admin
from django.urls import path, include
from django.shortcuts import redirect

urlpatterns = [
    path("", include("travel.urls")),
    path("admin/", admin.site.urls),
    path("", lambda r: redirect("guide/")),
    
]
