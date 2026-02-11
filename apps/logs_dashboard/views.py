import csv

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import HttpResponse, HttpResponseForbidden
from django.shortcuts import render, redirect
from django.db.models import Q

from config.orgs.org_context import get_request_org
from config.orgs.models import Organization, OrganizationMember

from apps.logs_dashboard.models import LogEntry


@login_required
def logs_list(request):
    # Allow selecting org via session to avoid X-ORG-ID header in browser.
    if request.GET.get("org"):
        org_candidate = request.GET.get("org")
        org_obj = Organization.objects.filter(public_id=org_candidate, members__user=request.user).first()
        if org_obj:
            request.session["active_org_id"] = str(org_obj.public_id)
            return redirect("logs-list")

    try:
        org = get_request_org(request)
    except Exception:
        # If user belongs to exactly one org, auto-select it.
        memberships = OrganizationMember.objects.filter(user=request.user).select_related("org")
        if memberships.count() == 1:
            request.session["active_org_id"] = str(memberships[0].org.public_id)
            return redirect("logs-list")
        return HttpResponseForbidden("Organization not accessible")

    membership = OrganizationMember.objects.filter(org=org, user=request.user).first()
    if not membership or membership.role not in {
        OrganizationMember.ROLE_ADMIN,
        OrganizationMember.ROLE_OWNER,
    }:
        return HttpResponseForbidden("Insufficient permissions")

    qs = LogEntry.objects.filter(org_id=str(org.public_id)).order_by("-created_at")

    level = request.GET.get("level") or ""
    if level:
        qs = qs.filter(level__iexact=level)

    query = request.GET.get("q") or ""
    if query:
        qs = qs.filter(Q(message__icontains=query) | Q(event__icontains=query))

    request_id = request.GET.get("request_id") or ""
    if request_id:
        qs = qs.filter(request_id__icontains=request_id)

    user_id = request.GET.get("user_id") or ""
    if user_id:
        qs = qs.filter(user_id__icontains=user_id)

    path = request.GET.get("path") or ""
    if path:
        qs = qs.filter(path__icontains=path)

    method = request.GET.get("method") or ""
    if method:
        qs = qs.filter(method__iexact=method)

    task_id = request.GET.get("task_id") or ""
    if task_id:
        qs = qs.filter(task_id__icontains=task_id)

    task_name = request.GET.get("task_name") or ""
    if task_name:
        qs = qs.filter(task_name__icontains=task_name)

    if request.GET.get("format") == "csv":
        max_rows = int(request.GET.get("limit") or 5000)
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = "attachment; filename=logs.csv"
        writer = csv.writer(response)
        writer.writerow(
            [
                "created_at",
                "level",
                "event",
                "message",
                "request_id",
                "org_id",
                "user_id",
                "path",
                "method",
                "task_id",
                "task_name",
            ]
        )
        for row in qs[:max_rows]:
            writer.writerow(
                [
                    row.created_at.isoformat(),
                    row.level,
                    row.event,
                    row.message,
                    row.request_id,
                    row.org_id,
                    row.user_id,
                    row.path,
                    row.method,
                    row.task_id,
                    row.task_name,
                ]
            )
        return response

    paginator = Paginator(qs, 50)
    page = paginator.get_page(request.GET.get("page"))

    user_orgs = [
        {"id": str(m.org.public_id), "name": m.org.name}
        for m in OrganizationMember.objects.filter(user=request.user).select_related("org")
    ]

    return render(
        request,
        "logs_dashboard/logs_list.html",
        {
            "page": page,
            "level": level,
            "q": query,
            "request_id": request_id,
            "user_id": user_id,
            "path": path,
            "method": method,
            "task_id": task_id,
            "task_name": task_name,
            "user_orgs": user_orgs,
            "active_org_id": str(org.public_id),
        },
    )
