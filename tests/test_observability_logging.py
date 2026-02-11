from config.observability.logging import mask_sensitive


def test_mask_sensitive_masks_nested_fields():
    payload = {
        "password": "secret",
        "token": "abc",
        "nested": {"api_key": "123", "value": "ok"},
        "items": [{"authorization": "Bearer x"}, {"note": "ok"}],
    }

    masked = mask_sensitive(None, None, payload)

    assert masked["password"] == "***"
    assert masked["token"] == "***"
    assert masked["nested"]["api_key"] == "***"
    assert masked["nested"]["value"] == "ok"
    assert masked["items"][0]["authorization"] == "***"
    assert masked["items"][1]["note"] == "ok"
