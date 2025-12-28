from rest_framework.permissions import BasePermission, SAFE_METHODS

from .models import Organization, OrganizationMember


class IsOrgMemberReadOnlyOrOrgAdmin(BasePermission):
    """
    SAFE methods: any org member
    Write methods: org admin/owner only
    Requires X-ORG-ID header.
    """

    message = "You don't have permission for this organization."

    def has_permission(self, request, view):
        # get_request_org already checks membership and header
        org_id = request.headers.get("X-ORG-ID")
        if not org_id:
            return False

        try:
            org = Organization.objects.get(public_id=org_id)
        except Organization.DoesNotExist:
            return False

        try:
            membership = OrganizationMember.objects.get(org=org, user=request.user)
        except OrganizationMember.DoesNotExist:
            return False

        if request.method in SAFE_METHODS:
            return True

        return membership.role in (OrganizationMember.ROLE_ADMIN, OrganizationMember.ROLE_OWNER)
