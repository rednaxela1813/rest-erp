#apps/products/api_views.py
from rest_framework import generics
from rest_framework.permissions import IsAuthenticated

from config.orgs.org_context import get_request_org
from config.orgs.permissions import IsOrgMemberReadOnlyOrOrgAdmin

from .models import Unit, TaxRate
from .serializers import UnitSerializer, TaxRateSerializer

from rest_framework import status as drf_status
from rest_framework.response import Response




class UnitListCreateApi(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated, IsOrgMemberReadOnlyOrOrgAdmin]
    serializer_class = UnitSerializer

    def get_queryset(self):
        org = get_request_org(self.request)
        return Unit.objects.filter(org=org, status=Unit.STATUS_ACTIVE).order_by("id")

    def perform_create(self, serializer):
        org = get_request_org(self.request)
        serializer.save(org=org)

class UnitDetailApi(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated, IsOrgMemberReadOnlyOrOrgAdmin]
    serializer_class = UnitSerializer
    lookup_field = "public_id"
    lookup_url_kwarg = "public_id"

    def get_queryset(self):
        org = get_request_org(self.request)
        return Unit.objects.filter(org=org)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.status = Unit.STATUS_ARCHIVED
        instance.save(update_fields=["status"])
        return Response(status=drf_status.HTTP_204_NO_CONTENT)



class TaxRateListApi(generics.ListAPIView):
    permission_classes = [IsAuthenticated, IsOrgMemberReadOnlyOrOrgAdmin]
    serializer_class = TaxRateSerializer

    def get_queryset(self):
        org = get_request_org(self.request)
        return TaxRate.objects.filter(org=org, status=TaxRate.STATUS_ACTIVE).order_by("id")
