# config/orgs/org_context.py

from rest_framework.exceptions import ParseError, PermissionDenied

from .models import Organization, OrganizationMember


def get_request_org(request):
    org_id = request.headers.get("X-ORG-ID")
    if not org_id:
        raise ParseError('Missing "X-ORG-ID" header')

    try:
        org = Organization.objects.get(public_id=org_id)
    except Organization.DoesNotExist:
        # можно 404, но для безопасности чаще 404
        raise PermissionDenied("Organization not accessible")

    is_member = OrganizationMember.objects.filter(org=org, user=request.user).exists()
    if not is_member:
        raise PermissionDenied("Organization not accessible")

    return org
