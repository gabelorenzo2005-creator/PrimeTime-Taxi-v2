from django.contrib import admin
from django.urls import path
from core import views, api, mobile_api

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', views.home, name='home'),
    path('api/login/', views.login_view, name='login'),
    path('api/logout/', api.Logout.as_view()),
    path('api/password/', api.PasswordChange.as_view()),
    path('api/gps/', mobile_api.DriverGPS.as_view()),
    path('api/devices/', mobile_api.Devices.as_view()),
    path('api/devices/<int:pk>/', mobile_api.DeviceDetail.as_view()),
    path('api/workspace/', api.Workspace.as_view()),
    path('api/shifts/', api.Shifts.as_view()),
    path('api/shifts/<int:pk>/<str:action>/', api.ShiftAction.as_view()),
    path('api/trips/', api.Trips.as_view()),
    path('api/trips/<int:pk>/<str:action>/', api.TripAction.as_view()),
    path('api/alerts/', api.Alerts.as_view()),
    path('api/alerts/<int:pk>/<str:action>/', api.AlertAction.as_view()),
    path('api/records/<str:resource>/', api.Records.as_view()),
    path('api/records/<str:resource>/<int:pk>/', api.Records.as_view()),
]
