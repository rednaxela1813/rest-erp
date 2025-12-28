def test_get_user_model_is_custom_user():
    from django.contrib.auth import get_user_model

    User = get_user_model()

    assert User.__module__ == "config.users.models"
    assert User.__name__ == "User"
    assert User.USERNAME_FIELD == "email"

