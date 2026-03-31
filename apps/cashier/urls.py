from django.urls import path

from . import views


app_name = "cashier"

urlpatterns = [
    path("login/", views.cashier_login, name="login"),
    path("logout/", views.cashier_logout, name="logout"),
    path("session/open/", views.session_open, name="session_open"),
    path("session/cash-in/", views.cash_in, name="cash_in"),
    path("", views.cashier_home, name="home"),
    path("products/", views.product_list, name="product_list"),
    path("cart/", views.cart_panel, name="cart_panel"),
    path("cart/add/<int:product_id>/", views.cart_add, name="cart_add"),
    path("cart/add-barcode/", views.cart_add_barcode, name="cart_add_barcode"),
    path("cart/remove/<int:product_id>/", views.cart_remove, name="cart_remove"),
    path("cart/clear/", views.cart_clear, name="cart_clear"),
    path("kitchen/", views.kitchen_board, name="kitchen_board"),
    path("kitchen/panel/", views.kitchen_panel, name="kitchen_panel"),
    path("kitchen/next/", views.kitchen_claim_next, name="kitchen_claim_next"),
    path("kitchen/tickets/<uuid:public_id>/", views.kitchen_update, name="kitchen_update"),
    path("checkout/", views.checkout, name="checkout"),
    path("payments/<uuid:public_id>/", views.payment_wait, name="payment_wait"),
    path("payments/<uuid:public_id>/status/", views.payment_status, name="payment_status"),
    path("payments/<uuid:public_id>/retry-fiscal/", views.payment_retry_fiscal, name="payment_retry_fiscal"),
    path("payments/<uuid:public_id>/confirm/cash/", views.payment_confirm_cash, name="payment_confirm_cash"),
    path("payments/<uuid:public_id>/confirm/card/", views.payment_confirm_card, name="payment_confirm_card"),
    path("device/payments/<uuid:public_id>/cash/", views.device_cash_confirm, name="device_cash_confirm"),
    path("device/payments/<uuid:public_id>/card/", views.device_card_confirm, name="device_card_confirm"),
    path("drafts/<uuid:public_id>/pay/<str:tender>/", views.draft_pay, name="draft_pay"),
    path("drafts/<uuid:public_id>/cancel/", views.draft_cancel, name="draft_cancel"),
    path("orders/<uuid:public_id>/refund/", views.order_refund, name="order_refund"),
]
