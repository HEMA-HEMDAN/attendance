"""
JWT authentication middleware for Django Channels WebSockets.

The standard DRF JWT authentication doesn't work for WebSockets.
This middleware extracts the token from the query string and authenticates
the user before the WebSocket consumer runs.

Usage (client):
  ws://localhost:8000/ws/sessions/{id}/?token=<access_token>
"""

from django.contrib.auth.models import AnonymousUser
from channels.middleware import BaseMiddleware
from channels.db import database_sync_to_async
from rest_framework_simplejwt.tokens import AccessToken
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError


@database_sync_to_async
def get_user_from_token(token_str: str):
    from apps.accounts.models import User
    try:
        token = AccessToken(token_str)
        user_id = token['user_id']
        return User.objects.select_related('organization').get(id=user_id, is_active=True)
    except (InvalidToken, TokenError, User.DoesNotExist, KeyError):
        return AnonymousUser()


class JWTAuthMiddleware(BaseMiddleware):
    """Attach authenticated user to WebSocket scope."""

    async def __call__(self, scope, receive, send):
        from urllib.parse import parse_qs
        query_string = scope.get('query_string', b'').decode()
        params = parse_qs(query_string)
        token_list = params.get('token', [])

        if token_list:
            scope['user'] = await get_user_from_token(token_list[0])
        else:
            scope['user'] = AnonymousUser()

        return await super().__call__(scope, receive, send)


def JWTAuthMiddlewareStack(inner):
    return JWTAuthMiddleware(inner)
