from django.contrib import admin

from .models import OrgNote, Organization, OrganizationMember


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ("name", "legal_form", "registration_number", "vat_number", "country", "created_at")
    search_fields = ("name", "registration_number", "vat_number")
    list_filter = ("country",)


@admin.register(OrganizationMember)
class OrganizationMemberAdmin(admin.ModelAdmin):
    list_display = ("org", "user", "role", "created_at")
    search_fields = ("org__name", "user__email")
    list_filter = ("role",)


@admin.register(OrgNote)
class OrgNoteAdmin(admin.ModelAdmin):
    list_display = ("org", "title", "created_at")
    search_fields = ("org__name", "title")
