#project/backend/apps/recipes/admin.py
from urllib import request

from django.contrib import admin
from .models import Recipe, RecipeItem
from apps.products.models import Unit, Product


class RecipeItemInline(admin.TabularInline):
    model = RecipeItem
    extra = 1
    
    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        print(f"DEBUG: db_field.name = {db_field.name}")
        if db_field.name == "unit":
            kwargs["queryset"] = Unit.objects.all()
        if db_field.name == "product":
            kwargs["queryset"] = Product.objects.all()
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

@admin.register(Recipe)
class RecipeAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "product", "status")
    list_filter = ("status",)
    search_fields = ("name", "product__name")
    inlines = [RecipeItemInline]
    
    
@admin.register(RecipeItem)
class RecipeItemAdmin(admin.ModelAdmin):
    list_display = ("id", "recipe", "product", "quantity")
    search_fields = ("recipe__name", "product__name")   

