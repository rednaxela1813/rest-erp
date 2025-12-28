#config/orgs/models.py

import uuid
from django.db import models


class OrgScopedModel(models.Model):
    public_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    org = models.ForeignKey("orgs.Organization", on_delete=models.CASCADE, related_name="%(class)ss")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
        
class OrgNote(OrgScopedModel):
    title = models.CharField(max_length=255)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.title



class Organization(models.Model):
    public_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)

    name = models.CharField(max_length=255)
    legal_form = models.CharField(max_length=32, blank=True, default="")

    registration_number = models.CharField(max_length=32, blank=True, default="", db_index=True)
    vat_number = models.CharField(max_length=32, blank=True, default="", db_index=True)

    country = models.ForeignKey(
        "dictionaries.Country",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="organizations",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class OrganizationMember(models.Model):
    ROLE_OWNER = "owner"
    ROLE_ADMIN = "admin"
    ROLE_MEMBER = "member"

    ROLE_CHOICES = (
        (ROLE_OWNER, "Owner"),
        (ROLE_ADMIN, "Admin"),
        (ROLE_MEMBER, "Member"),
    )

    org = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="members",
    )
    user = models.ForeignKey(
        "users.User",
        on_delete=models.CASCADE,
        related_name="org_memberships",
    )
    role = models.CharField(max_length=16, choices=ROLE_CHOICES, default=ROLE_MEMBER)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["org", "user"], name="uniq_org_member"),
        ]
        ordering = ["org_id", "user_id"]

    def __str__(self) -> str:
        return f"{self.org.name}: {self.user.email}"
