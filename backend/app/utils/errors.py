"""Service-layer errors. Routers translate these into HTTP responses."""

from __future__ import annotations


class ServiceError(Exception):
    status_code = 400

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class NotFoundError(ServiceError):
    status_code = 404


class ConflictError(ServiceError):
    status_code = 409


class ValidationFailed(ServiceError):
    status_code = 422


class PermissionDenied(ServiceError):
    status_code = 403


class AuthenticationFailed(ServiceError):
    status_code = 401


class RateLimited(ServiceError):
    status_code = 429


class UnavailableError(ServiceError):
    """A dependency (dataset, model, configuration) is not available."""

    status_code = 503
