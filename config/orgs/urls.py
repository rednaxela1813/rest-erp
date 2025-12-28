from django.urls import path
from .api_views import MyOrganizationsView, OrganizationCreateView, \
OrgContextView, OrgNoteListCreateView, OrgMemberListCreateApi, OrgMemberDetailApi


urlpatterns = [
    path("my/", MyOrganizationsView.as_view(), name="my-orgs"),
    path("context/", OrgContextView.as_view(), name="org-context"),
    path("notes/", OrgNoteListCreateView.as_view(), name="org-notes"),
    path("members/", OrgMemberListCreateApi.as_view(), name="org-members-list"),
    path("members/<int:id>/", OrgMemberDetailApi.as_view(), name="org-member-detail"),
    path("", OrganizationCreateView.as_view(), name="org-create"),
]
