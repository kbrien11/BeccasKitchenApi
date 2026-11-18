"""Issuing tokens and setting/clearing the httpOnly auth cookie."""
from django.conf import settings
from rest_framework.authtoken.models import Token

from .authentication import token_expired


def issue_token(user):
    """Reuse the user's current token, or replace it if it has expired."""
    token, created = Token.objects.get_or_create(user=user)
    if not created and token_expired(token):
        token.delete()
        token = Token.objects.create(user=user)
    return token


def set_auth_cookie(response, token):
    response.set_cookie(
        settings.AUTH_COOKIE_NAME,
        token.key,
        max_age=int(settings.AUTH_TOKEN_TTL.total_seconds()),
        httponly=True,  # JavaScript can never read it.
        secure=settings.AUTH_COOKIE_SECURE,
        samesite=settings.AUTH_COOKIE_SAMESITE,
        path="/",
    )
    return response


def clear_auth_cookie(response):
    response.delete_cookie(settings.AUTH_COOKIE_NAME, path="/", samesite=settings.AUTH_COOKIE_SAMESITE)
    return response
