from django.urls import path

from . import views


app_name = "cashier"

# Все URL кассового интерфейса сгруппированы по смыслу.
#
# Соглашение об именовании:
#   session/*  — операции со сменой (открытие, закрытие, внесение)
#   cart/*     — корзина текущего заказа
#   kitchen/*  — кухонный экран
#   payments/* — страницы ожидания и подтверждения оплаты
#   device/*   — эндпоинты для физических устройств (терминал, кассовый ящик)
#   drafts/*   — действия с черновиками заказов
#   orders/*   — действия с завершёнными заказами (возврат)

urlpatterns = [
    # ── Аутентификация ──────────────────────────────────────────────────────
    path("login/", views.cashier_login, name="login"),
    path("logout/", views.cashier_logout, name="logout"),

    # ── Управление сменой ───────────────────────────────────────────────────
    # session_open: выбор организации, терминала и внесение разменной монеты.
    path("session/open/", views.session_open, name="session_open"),
    # cash_in: внесение наличных в ящик в течение смены (инкассация, сдача).
    path("session/cash-in/", views.cash_in, name="cash_in"),
    # session_close: двухшаговое закрытие смены — сначала Z-отчёт (GET),
    # затем подтверждение и logout (POST).
    path("session/close/", views.session_close, name="session_close"),

    # ── Главная страница кассы ───────────────────────────────────────────────
    path("", views.cashier_home, name="home"),

    # ── Каталог товаров ─────────────────────────────────────────────────────
    # Используется как HTMX-партиал для поиска в реальном времени.
    path("products/", views.product_list, name="product_list"),

    # ── Корзина ─────────────────────────────────────────────────────────────
    # cart_panel: полный HTML корзины (HTMX-партиал).
    path("cart/", views.cart_panel, name="cart_panel"),
    # cart_add: добавить товар по id из каталога.
    path("cart/add/<int:product_id>/", views.cart_add, name="cart_add"),
    # cart_add_barcode: добавить товар по штрихкоду со сканера.
    path("cart/add-barcode/", views.cart_add_barcode, name="cart_add_barcode"),
    # cart_remove: убрать одну единицу товара из корзины.
    path("cart/remove/<int:product_id>/", views.cart_remove, name="cart_remove"),
    # cart_clear: очистить корзину полностью.
    path("cart/clear/", views.cart_clear, name="cart_clear"),
    
    path("cart/restore/", views.cart_restore, name="cart_restore"),

    # ── Кухонный экран ──────────────────────────────────────────────────────
    path("kitchen/", views.kitchen_board, name="kitchen_board"),
    # kitchen_panel: HTMX-партиал со списком активных тикетов.
    path("kitchen/panel/", views.kitchen_panel, name="kitchen_panel"),
    # kitchen_claim_next: повар берёт следующий тикет в работу.
    path("kitchen/next/", views.kitchen_claim_next, name="kitchen_claim_next"),
    # kitchen_update: обновить статус конкретного тикета (ready/cancelled).
    path("kitchen/tickets/<uuid:public_id>/", views.kitchen_update, name="kitchen_update"),

    # ── Оформление заказа ───────────────────────────────────────────────────
    # checkout: создать Order из корзины и перейти к выбору способа оплаты.
    path("checkout/", views.checkout, name="checkout"),

    # ── Оплата ──────────────────────────────────────────────────────────────
    # payment_wait: страница ожидания подтверждения оплаты.
    # HTMX каждые 2с делает запрос на payment_status для обновления статуса.
    path("payments/<uuid:public_id>/", views.payment_wait, name="payment_wait"),
    # payment_status: HTMX-партиал — текущий статус оплаты и фискализации.
    path("payments/<uuid:public_id>/status/", views.payment_status, name="payment_status"),
    # payment_retry_fiscal: повторить фискализацию если eKasa вернула ошибку.
    path("payments/<uuid:public_id>/retry-fiscal/", views.payment_retry_fiscal, name="payment_retry_fiscal"),
    # payment_confirm_cash/card: ручное подтверждение оплаты (debug-режим).
    # В production сигнал приходит от физического устройства через device/*.
    path("payments/<uuid:public_id>/confirm/cash/", views.payment_confirm_cash, name="payment_confirm_cash"),
    path("payments/<uuid:public_id>/confirm/card/", views.payment_confirm_card, name="payment_confirm_card"),

    # ── Эндпоинты для физических устройств ─────────────────────────────────
    # Вызываются кассовым ящиком или терминалом, а не браузером кассира.
    # Защищены токеном CASHIER_DEVICE_TOKEN из .env (X-DEVICE-TOKEN header).
    # Не требуют CSRF — используют @csrf_exempt.
    path("device/payments/<uuid:public_id>/cash/", views.device_cash_confirm, name="device_cash_confirm"),
    path("device/payments/<uuid:public_id>/card/", views.device_card_confirm, name="device_card_confirm"),

    # ── Действия с черновиками ───────────────────────────────────────────────
    # draft_pay: начать оплату черновика (tender = cash | card).
    # Создаёт OrderPayment и редиректит на payment_wait.
    path("drafts/<uuid:public_id>/pay/<str:tender>/", views.draft_pay, name="draft_pay"),
    # draft_cancel: отменить черновик без оплаты, вернуть товары на склад.
    path("drafts/<uuid:public_id>/cancel/", views.draft_cancel, name="draft_cancel"),

    # ── Действия с завершёнными заказами ────────────────────────────────────
    # order_refund: возврат оплаченного заказа.
    # Отменяет заказ, возвращает товары на склад, создаёт фискальный чек возврата.
    path("orders/<uuid:public_id>/refund/", views.order_refund, name="order_refund"),
    
]
