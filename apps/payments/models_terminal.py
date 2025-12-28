# apps/payments/models_terminal.py
from django.db import models

from config.orgs.models import OrgScopedModel



class Terminal(OrgScopedModel):
    """
    MVP-заглушка, чтобы PaymentEvent мог ссылаться на Terminal.
    Полноценную модель (location/zone/external_id) сделаем позже отдельными тестами.
    """
    #org = models.ForeignKey("orgs.Organization", on_delete=models.PROTECT, related_name="terminals")
    pass
    

    
