#config/orgs/api_views.py

from rest_framework.generics import ListAPIView, CreateAPIView
from rest_framework.permissions import IsAuthenticated

from .models import Organization, OrganizationMember
from .serializers import OrganizationSerializer, OrgNoteSerializer, OrgMemberListSerializer, OrgMemberUpdateSerializer



from rest_framework.views import APIView
from rest_framework.response import Response
from .org_context import get_request_org


from rest_framework.generics import ListCreateAPIView

from .drf_mixins import OrgScopedQuerysetMixin
from .models import OrgNote
from .serializers import OrgNoteSerializer

from .permissions import IsOrgMemberReadOnlyOrOrgAdmin

from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated

from config.orgs.models import OrganizationMember
from config.orgs.serializers import OrgMemberListSerializer

from config.orgs.permissions import IsOrgMemberReadOnlyOrOrgAdmin
from rest_framework.exceptions import PermissionDenied





class MyOrganizationsView(ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = OrganizationSerializer

    def get_queryset(self):
        return Organization.objects.filter(members__user=self.request.user).distinct()


class OrganizationCreateView(CreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = OrganizationSerializer
    queryset = Organization.objects.all()

    def perform_create(self, serializer):
        org = serializer.save()
        OrganizationMember.objects.create(org=org, user=self.request.user, role="owner")

class OrgContextView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        org = get_request_org(request)
        data = OrganizationSerializer(org).data
        return Response(data)
    
    
class OrgNoteListCreateView(OrgScopedQuerysetMixin, ListCreateAPIView):
    permission_classes = [IsAuthenticated, IsOrgMemberReadOnlyOrOrgAdmin]
    queryset = OrgNote.objects.all()
    serializer_class = OrgNoteSerializer
    
    
class OrgMemberListApi(generics.ListAPIView):
    """
    GET /api/v1/orgs/members/
    Список участников активной организации (X-ORG-ID).
    """
    serializer_class = OrgMemberListSerializer
    permission_classes = [IsAuthenticated, IsOrgMemberReadOnlyOrOrgAdmin]

    def get_queryset(self):
        org = get_request_org(self.request)
        return (
            OrganizationMember.objects
            .select_related("user")
            .filter(org=org)
            .order_by("id")
        )
        

class OrgMemberListCreateApi(generics.ListCreateAPIView):
    """
    GET  /api/v1/orgs/members/  -> list members (SAFE всем членам org)
    POST /api/v1/orgs/members/  -> add member (только owner/admin)
    """
    permission_classes = [IsAuthenticated, IsOrgMemberReadOnlyOrOrgAdmin]

    def get_queryset(self):
        org = get_request_org(self.request)
        return (
            OrganizationMember.objects
            .select_related("user")
            .filter(org=org)
            .order_by("id")
        )

    def get_serializer_class(self):
        if self.request.method == "POST":
            from .serializers import OrgMemberCreateSerializer
            return OrgMemberCreateSerializer
        from .serializers import OrgMemberListSerializer
        return OrgMemberListSerializer

    def perform_create(self, serializer):
        org = get_request_org(self.request)
        serializer.save(org=org)


class OrgMemberDetailApi(generics.RetrieveUpdateDestroyAPIView):
    """
    PATCH /api/v1/orgs/members/<id>/   change role
    DELETE /api/v1/orgs/members/<id>/  remove member
    """
    permission_classes = [IsAuthenticated, IsOrgMemberReadOnlyOrOrgAdmin]
    lookup_field = "id"

    def get_queryset(self):
        org = get_request_org(self.request)
        return OrganizationMember.objects.select_related("user").filter(org=org)

    def get_serializer_class(self):
        if self.request.method in ("PATCH", "PUT"):
            return OrgMemberUpdateSerializer
        return OrgMemberListSerializer

    def _guard_owner_demote(self, request, instance):
        new_role = request.data.get("role")

        # интересует только попытка изменить owner -> НЕ owner
        if instance.role != "owner":
            return None
        if not new_role or new_role == "owner":
            return None

        # 1) только owner может менять owner
        is_requester_owner = OrganizationMember.objects.filter(
            org=instance.org,
            user=request.user,
            role="owner",
        ).exists()
        if not is_requester_owner:
            raise PermissionDenied("Only an owner can modify owner role.")

        # 2) нельзя понизить последнего owner
        owners_count = OrganizationMember.objects.filter(org=instance.org, role="owner").count()
        if owners_count <= 1:
            return Response(
                {"detail": "Cannot demote the last owner."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return None

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        guard_resp = self._guard_owner_demote(request, instance)
        if guard_resp is not None:
            return guard_resp
        return super().update(request, *args, **kwargs)

    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        guard_resp = self._guard_owner_demote(request, instance)
        if guard_resp is not None:
            return guard_resp
        return super().partial_update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()

        # guard: нельзя удалить последнего owner
        if instance.role == "owner":
            owners_count = OrganizationMember.objects.filter(org=instance.org, role="owner").count()
            if owners_count <= 1:
                return Response(
                    {"detail": "Cannot remove the last owner."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        return super().destroy(request, *args, **kwargs)
