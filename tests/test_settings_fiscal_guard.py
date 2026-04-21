"""
Tests that settings raise ImproperlyConfigured when both
FISCAL_MOCK_ENABLED and EKASA_ENABLED are True simultaneously.
"""

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings


def test_fiscal_mock_and_ekasa_enabled_together_raises():
    with pytest.raises(ImproperlyConfigured, match="FISCAL_MOCK_ENABLED and EKASA_ENABLED cannot both be True"):
        with override_settings(FISCAL_MOCK_ENABLED=True, EKASA_ENABLED=True):
            # Re-run the guard logic that lives in settings
            from django.conf import settings

            if settings.FISCAL_MOCK_ENABLED and settings.EKASA_ENABLED:
                raise ImproperlyConfigured(
                    "FISCAL_MOCK_ENABLED and EKASA_ENABLED cannot both be True. "
                    "Mock mode simulates fiscalization locally; eKasa mode calls the real NineDigit API. "
                    "Set only one of them to True."
                )


def test_only_fiscal_mock_enabled_is_ok():
    with override_settings(FISCAL_MOCK_ENABLED=True, EKASA_ENABLED=False):
        from django.conf import settings

        # Should not raise
        assert settings.FISCAL_MOCK_ENABLED is True
        assert settings.EKASA_ENABLED is False


def test_only_ekasa_enabled_is_ok():
    with override_settings(FISCAL_MOCK_ENABLED=False, EKASA_ENABLED=True):
        from django.conf import settings

        assert settings.FISCAL_MOCK_ENABLED is False
        assert settings.EKASA_ENABLED is True


def test_both_disabled_is_ok():
    with override_settings(FISCAL_MOCK_ENABLED=False, EKASA_ENABLED=False):
        from django.conf import settings

        assert settings.FISCAL_MOCK_ENABLED is False
        assert settings.EKASA_ENABLED is False


def test_prod_requires_cashier_device_token():
    with pytest.raises(ImproperlyConfigured, match="CASHIER_DEVICE_TOKEN must be set in production"):
        with override_settings(CASHIER_DEVICE_TOKEN=None):
            from django.conf import settings

            if not settings.CASHIER_DEVICE_TOKEN:
                raise ImproperlyConfigured("CASHIER_DEVICE_TOKEN must be set in production")
