from datetime import datetime, timedelta, timezone
from uuid import uuid4

import jwt
from fastapi import Request, Response

from config import Config

COOKIE_NAME = "ezlogic_guest"
GUEST_ISSUER = "ezlogic-guest"
SESSION_TTL = timedelta(days=1)


def ensure_guest_session(request: Request, response: Response) -> None:
    token = request.cookies.get(COOKIE_NAME)
    if token:
        try:
            claims = jwt.decode(
                token,
                Config.GUEST_JWT_SECRET,
                algorithms=["HS256"],
                issuer=GUEST_ISSUER,
                options={"require": ["sub", "exp", "iss"]},
            )
        except jwt.InvalidTokenError:
            pass  # Start a fresh guest session when the previous token is unusable.
        else:
            request.state.guest_id = claims["sub"]
            return

    guest_id = str(uuid4())
    token = jwt.encode(
        {
            "sub": guest_id,
            "iss": GUEST_ISSUER,
            "exp": datetime.now(timezone.utc) + SESSION_TTL,
        },
        Config.GUEST_JWT_SECRET,
        algorithm="HS256",
    )
    request.state.guest_id = guest_id
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        max_age=int(SESSION_TTL.total_seconds()),
        path="/api",
        httponly=True,
        secure=Config.GUEST_COOKIE_SECURE,
        samesite="lax",
    )
