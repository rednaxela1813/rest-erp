from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from datetime import date, datetime, timedelta
import structlog

from django.db.models import Count, Q, Sum
from django.shortcuts import render, redirect
from django.utils import timezone

from config.orgs.models import Organization, OrganizationMember
from apps.orders.models import Order, OrderItem
from apps.payments.models import CashierSession, DeviceCommand, OrderPayment, FiscalReceipt
from apps.products.models import Product

logger = structlog.get_logger(__name__)


def _ensure_admin_or_owner(request, org) -> None:
    membership = OrganizationMember.objects.filter(org=org, user=request.user).first()
    if not membership or membership.role not in (
        OrganizationMember.ROLE_ADMIN,
        OrganizationMember.ROLE_OWNER,
    ):
        logger.warning(
            "ops_dashboard_access_denied_insufficient_role",
            org_id=str(org.public_id),
            user_id=str(request.user.id),
        )
        raise PermissionDenied("Admin/owner access required.")


def _get_request_org(request):
    org_id = request.headers.get("X-ORG-ID") or request.GET.get("org")
    if not org_id:
        raise PermissionDenied('Missing "X-ORG-ID" header or "org" query param.')

    try:
        org = Organization.objects.get(public_id=org_id)
    except Organization.DoesNotExist:
        raise PermissionDenied("Organization not accessible")

    is_member = OrganizationMember.objects.filter(org=org, user=request.user).exists()
    if not is_member:
        raise PermissionDenied("Organization not accessible")

    return org


def _get_dashboard_metrics(org) -> dict:
    # Fiscal command backlog
    fiscal_qs = DeviceCommand.objects.filter(
        org=org,
        command_type__in=[
            DeviceCommand.Type.FISCALIZE_SALE,
            DeviceCommand.Type.FISCALIZE_REFUND,
            DeviceCommand.Type.FISCALIZE_STORNO,
        ],
    ).exclude(status=DeviceCommand.Status.ACKED)

    fiscal_counts = {
        DeviceCommand.Status.PENDING: 0,
        DeviceCommand.Status.SENT: 0,
        DeviceCommand.Status.FAILED: 0,
    }
    for row in fiscal_qs.values("status").annotate(count=Count("id")):
        fiscal_counts[row["status"]] = row["count"]

    oldest_fiscal = fiscal_qs.order_by("created_at").first()

    payment_counts = {
        "capture_timeout": OrderPayment.objects.filter(
            org=org, capture_status=OrderPayment.CaptureStatus.TIMEOUT
        ).count(),
        "capture_pending": OrderPayment.objects.filter(
            org=org, capture_status=OrderPayment.CaptureStatus.PENDING
        ).count(),
        "fiscal_pending": OrderPayment.objects.filter(org=org, fiscal_status=OrderPayment.FiscalStatus.PENDING).count(),
        "fiscal_failed": OrderPayment.objects.filter(org=org, fiscal_status=OrderPayment.FiscalStatus.FAILED).count(),
    }

    order_counts = {
        "draft": Order.objects.filter(org=org, status=Order.STATUS_DRAFT).count(),
        "paid": Order.objects.filter(org=org, status=Order.STATUS_PAID).count(),
        "cancelled": Order.objects.filter(org=org, status=Order.STATUS_CANCELLED).count(),
    }

    open_sessions = CashierSession.objects.filter(org=org, status=CashierSession.STATUS_OPEN).count()

    return {
        "fiscal_unsent_total": fiscal_qs.count(),
        "fiscal_status_counts": fiscal_counts,
        "fiscal_oldest_created_at": oldest_fiscal.created_at if oldest_fiscal else None,
        "payment_counts": payment_counts,
        "order_counts": order_counts,
        "open_sessions": open_sessions,
    }


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def _get_period(request) -> tuple[datetime, datetime, str, str]:
    start_raw = request.GET.get("start")
    end_raw = request.GET.get("end")
    start_date = _parse_date(start_raw)
    end_date = _parse_date(end_raw)

    if not end_date:
        end_date = timezone.localdate()
    if not start_date:
        start_date = end_date - timedelta(days=7)

    start_dt = datetime.combine(start_date, datetime.min.time())
    end_dt = datetime.combine(end_date + timedelta(days=1), datetime.min.time())
    start_dt = timezone.make_aware(start_dt)
    end_dt = timezone.make_aware(end_dt)
    return start_dt, end_dt, start_date.isoformat(), end_date.isoformat()


def _get_management_tables(org, start_dt, end_dt) -> dict:
    paid_orders = Order.objects.filter(
        org=org,
        status=Order.STATUS_PAID,
        created_at__gte=start_dt,
        created_at__lt=end_dt,
    )
    orders_count = paid_orders.count()
    revenue = paid_orders.aggregate(total=Sum("total")).get("total") or 0
    avg_check = (revenue / orders_count) if orders_count else 0

    payments = OrderPayment.objects.filter(
        org=org,
        status=OrderPayment.Status.CAPTURED,
        created_at__gte=start_dt,
        created_at__lt=end_dt,
    )
    payments_by_tender = []
    for tender, _label in OrderPayment.Tender.choices:
        total = payments.filter(tender=tender).aggregate(amount=Sum("amount")).get("amount") or 0
        payments_by_tender.append({"tender": tender, "amount": total})

    refunds_total = (
        FiscalReceipt.objects.filter(
            org=org,
            receipt_type=FiscalReceipt.Type.REFUND,
            created_at__gte=start_dt,
            created_at__lt=end_dt,
        )
        .aggregate(total=Sum("total"))
        .get("total")
        or 0
    )
    storno_total = (
        FiscalReceipt.objects.filter(
            org=org,
            receipt_type=FiscalReceipt.Type.STORNO,
            created_at__gte=start_dt,
            created_at__lt=end_dt,
        )
        .aggregate(total=Sum("total"))
        .get("total")
        or 0
    )

    top_products = (
        OrderItem.objects.filter(order__in=paid_orders)
        .values("product_name")
        .annotate(qty=Sum("qty"))
        .order_by("-qty")[:10]
    )

    stock_levels = (
        Product.objects.filter(org=org)
        .annotate(
            stock_qty_annotated=Sum(
                "stock_lots__remaining_qty",
                filter=Q(stock_lots__status="active"),
            )
        )
        .filter(stock_qty_annotated__isnull=False)
        .order_by("stock_qty_annotated", "name")[:50]
    )

    return {
        "sales_summary": {
            "orders_count": orders_count,
            "revenue": revenue,
            "avg_check": avg_check,
        },
        "money_movement": {
            "payments_by_tender": payments_by_tender,
            "refunds_total": refunds_total,
            "storno_total": storno_total,
        },
        "goods_movement": {
            "top_products": list(top_products),
            "stock_levels": list(stock_levels),
        },
    }


@login_required(login_url="/cashier/login/")
def ops_dashboard_view(request):
    try:
        org = _get_request_org(request)
    except PermissionDenied as exc:
        if 'Missing "X-ORG-ID"' in str(exc):
            logger.info("ops_dashboard_redirect_select_org", user_id=str(request.user.id))
            return redirect("ops-dashboard-select-org")
        raise
    _ensure_admin_or_owner(request, org)
    metrics = _get_dashboard_metrics(org)
    start_dt, end_dt, start_value, end_value = _get_period(request)
    management = _get_management_tables(org, start_dt, end_dt)
    return render(
        request,
        "ops_dashboard/dashboard.html",
        {
            "org": org,
            "metrics": metrics,
            "management": management,
            "start_date": start_value,
            "end_date": end_value,
        },
    )


@login_required(login_url="/cashier/login/")
def ops_dashboard_metrics_view(request):
    org = _get_request_org(request)
    _ensure_admin_or_owner(request, org)
    logger.info(
        "ops_dashboard_metrics_view_rendered",
        org_id=str(org.public_id),
        user_id=str(request.user.id),
    )
    metrics = _get_dashboard_metrics(org)
    return render(
        request,
        "ops_dashboard/partials/metrics.html",
        {"metrics": metrics},
    )


@login_required(login_url="/cashier/login/")
def ops_dashboard_select_org_view(request):
    memberships = (
        OrganizationMember.objects.select_related("org")
        .filter(
            user=request.user,
            role__in=[
                OrganizationMember.ROLE_ADMIN,
                OrganizationMember.ROLE_OWNER,
            ],
        )
        .order_by("org__name")
    )
    orgs = [membership.org for membership in memberships]
    logger.info(
        "ops_dashboard_select_org_view_rendered",
        user_id=str(request.user.id),
        org_count=len(orgs),
    )
    return render(
        request,
        "ops_dashboard/select_org.html",
        {"orgs": orgs},
    )
