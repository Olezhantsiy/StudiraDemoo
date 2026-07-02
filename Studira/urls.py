from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("research.urls")),
    path("api/", include("stud.urls")),
    path("api/users/", include("users.urls")),
    path("api/", include("meetings.urls")),
]
