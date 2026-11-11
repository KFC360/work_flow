from __future__ import annotations


class AppError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        self.message = message
        self.status_code = status_code
        super().__init__(message)


class ConflictError(AppError):
    def __init__(self, message: str) -> None:
        super().__init__(message, status_code=409)


class UnauthorizedError(AppError):
    def __init__(self, message: str = "Unauthorized") -> None:
        super().__init__(message, status_code=401)


class LoginRedirect(Exception):
    """Raised when a page request needs to go to /login."""
