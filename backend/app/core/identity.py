from fastapi import HTTPException, Request, status

from app.models.user import User


def current_user(request: Request) -> User:
    user = getattr(request.state, "auth_user", None)
    if not isinstance(user, User) or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required.")
    return user


def current_actor(request: Request) -> str:
    return current_user(request).display_name


def require_owner(request: Request) -> User:
    user = current_user(request)
    if user.role != "owner":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Owner access required.")
    return user
