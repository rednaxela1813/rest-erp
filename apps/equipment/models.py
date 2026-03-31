# project/backend/apps/equipment/models.py
from django.db import models

from config.orgs.models import OrgScopedModel
from dateutil.relativedelta import relativedelta

"""
Restaurant equipment, such as refrigerators, should be stored here.
"""


class Equipment(OrgScopedModel):
    STATUS_ACTIVE = "active"
    STATUS_ARCHIVED = "archived"
    STATUS_CHOICES = (
        (STATUS_ACTIVE, "Active"),
        (STATUS_ARCHIVED, "Archived"),
    )

    name = models.CharField(max_length=255)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_ACTIVE)
    power_kw = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)  # Power consumption in kW
    last_maintenance_date = models.DateField(null=True, blank=True)
    maintenance_interval_months = models.PositiveIntegerField(null=True, blank=True)  # Months between maintenance
    
    def next_maintenance_date(self):
        if self.last_maintenance_date and self.maintenance_interval_months:
            return self.last_maintenance_date + relativedelta(months=self.maintenance_interval_months)
        return None
    
    class Meta:
        ordering = ["id"]

    def __str__(self) -> str:
        return self.name
