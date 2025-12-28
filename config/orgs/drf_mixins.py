from .org_context import get_request_org


class OrgScopedQuerysetMixin:
    """
    Expects model has 'org' FK.
    Scopes queryset and auto-sets org on create.
    """

    def get_queryset(self):
        qs = super().get_queryset()
        org = get_request_org(self.request)
        return qs.filter(org=org)

    def perform_create(self, serializer):
        org = get_request_org(self.request)
        serializer.save(org=org)
