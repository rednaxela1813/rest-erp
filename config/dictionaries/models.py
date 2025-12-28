# -*- coding: utf-8 -*-
# config/dictionaries/models.py

from django.db import models


class Currency(models.Model):
    code = models.CharField(max_length=3, unique=True)  # ISO 4217
    name = models.CharField(max_length=64)
    symbol = models.CharField(max_length=8, blank=True, default="")

    class Meta:
        ordering = ["code"]

    def __str__(self) -> str:
        return self.code


class Country(models.Model):
    code = models.CharField(max_length=2, unique=True)  # ISO 3166-1 alpha-2
    name = models.CharField(max_length=128)

    class Meta:
        ordering = ["code"]

    def __str__(self) -> str:
        return self.code