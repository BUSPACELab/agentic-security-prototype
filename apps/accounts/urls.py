from django.urls import path

from . import views

# URL patterns for the accounts app 
# This includes the signup and profile urls
urlpatterns = [
    path("signup/", views.signup, name="signup"),
    path("profile/", views.profile, name="profile"),
]