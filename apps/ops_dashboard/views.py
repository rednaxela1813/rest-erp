from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Count
from django.shortcuts import render, redirect

from config.orgs.models import Organization, OrganizationMember
from apps.orders.models import Order
from apps.payments.models import CashierSession, DeviceCommand, OrderPayment


def _ensure_admin_or_owner(request, org) -> None:
    membership = OrganizationMember.objects.filter(org=org, user=request.user).first()
    if not membership or membership.role not in (
        OrganizationMember.ROLE_ADMIN,
        OrganizationMember.ROLE_OWNER,
    ):
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
        "fiscal_pending": OrderPayment.objects.filter(
            org=org, fiscal_status=OrderPayment.FiscalStatus.PENDING
        ).count(),
        "fiscal_failed": OrderPayment.objects.filter(
            org=org, fiscal_status=OrderPayment.FiscalStatus.FAILED
        ).count(),
    }

    order_counts = {
        "draft": Order.objects.filter(org=org, status=Order.STATUS_DRAFT).count(),
        "paid": Order.objects.filter(org=org, status=Order.STATUS_PAID).count(),
        "cancelled": Order.objects.filter(org=org, status=Order.STATUS_CANCELLED).count(),
    }

    open_sessions = CashierSession.objects.filter(
        org=org, status=CashierSession.STATUS_OPEN
    ).count()

    return {
        "fiscal_unsent_total": fiscal_qs.count(),
        "fiscal_status_counts": fiscal_counts,
        "fiscal_oldest_created_at": oldest_fiscal.created_at if oldest_fiscal else None,
        "payment_counts": payment_counts,
        "order_counts": order_counts,
        "open_sessions": open_sessions,
    }


@login_required(login_url="/cashier/login/")
def ops_dashboard_view(request):
    try:
        org = _get_request_org(request)
    except PermissionDenied as exc:
        if 'Missing "X-ORG-ID"' in str(exc):
            return redirect("ops-dashboard-select-org")
        raise
    _ensure_admin_or_owner(request, org)
    metrics = _get_dashboard_metrics(org)
    return render(
        request,
        "ops_dashboard/dashboard.html",
        {"org": org, "metrics": metrics},
    )


@login_required(login_url="/cashier/login/")
def ops_dashboard_metrics_view(request):
    org = _get_request_org(request)
    _ensure_admin_or_owner(request, org)
    metrics = _get_dashboard_metrics(org)
    return render(
        request,
        "ops_dashboard/partials/metrics.html",
        {"metrics": metrics},
    )


@login_required(login_url="/cashier/login/")
def ops_dashboard_select_org_view(request):
    memberships = (
        OrganizationMember.objects
        .select_related("org")
        .filter(user=request.user, role__in=[
            OrganizationMember.ROLE_ADMIN,
            OrganizationMember.ROLE_OWNER,
        ])
        .order_by("org__name")
    )
    orgs = [membership.org for membership in memberships]
    return render(
        request,
        "ops_dashboard/select_org.html",
        {"orgs": orgs},
    )
