# project/backend/apps/orders/urls.py
from django.urls import path
from .api_views import (
    OrderListCreateApi,
    OrderDetailApi,
    OrderItemListCreateApi,
    OrderStatusEventListApi,
)

urlpatterns = [
    path("orders/", OrderListCreateApi.as_view(), name="orders-list-create"),
    path("orders/<uuid:public_id>/", OrderDetailApi.as_view(), name="orders-detail"),  # <-- ВАЖНО
    path("orders/<uuid:order_public_id>/items/", OrderItemListCreateApi.as_view(), name="order-items"),
    path("orders/<uuid:public_id>/status-events/", OrderStatusEventListApi.as_view()),

]
