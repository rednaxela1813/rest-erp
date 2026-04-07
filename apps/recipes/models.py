#project/backend/apps/recipes/models.py
import uuid
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from config.orgs.models import OrgScopedModel
from apps.products.models import Unit, TaxRate, Product
from decimal import Decimal



class Recipe(OrgScopedModel):
    STATUS_ACTIVE = "active"
    STATUS_ARCHIVED = "archived"
    STATUS_CHOICES = (
        (STATUS_ACTIVE, "Active"),
        (STATUS_ARCHIVED, "Archived"),
    )
   
    
    product = models.OneToOneField(Product, on_delete=models.CASCADE, related_name="recipe")
    name = models.CharField(max_length=64)
    
    description = models.TextField(blank=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_ACTIVE)

    class Meta:
        ordering = ["id"]
        constraints = [
            models.UniqueConstraint(
                fields=["org", "name"],
                condition=models.Q(status="active"),
                name="uniq_active_recipe_name_per_org",
            ),
        ]

    def __str__(self) -> str:
        return self.name


class RecipeItem(OrgScopedModel):
    recipe = models.ForeignKey(Recipe, on_delete=models.CASCADE, related_name="ingredients")
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="used_in_recipes")
    quantity = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    #unit = models.ForeignKey(Unit, on_delete=models.CASCADE, related_name="recipe_ingredients")
    
    
    class Meta:
        ordering = ["id"]
        constraints = [
            models.UniqueConstraint(
                fields=["org", "recipe", "product"],
                name="uniq_product_per_recipe",
            ),
        ]
        
        
    def __str__(self) -> str:
        return f"{self.quantity} of {self.product} for {self.recipe}"
    
