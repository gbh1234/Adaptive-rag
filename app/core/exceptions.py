"""Application exception hierarchy."""

from app.core.error_codes import ErrorCode


class AppError(Exception):
    """Base business error. API layer maps this to HTTP + error_code."""

    def __init__(
        self,
        message: str,
        *,
        error_code: ErrorCode = ErrorCode.INTERNAL_ERROR,
        retryable: bool = False,
        http_status: int = 500,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.error_code = error_code
        self.retryable = retryable
        self.http_status = http_status


class InvalidRequestError(AppError):
    def __init__(self, message: str) -> None:
        super().__init__(message, error_code=ErrorCode.INVALID_REQUEST, http_status=400)


class RateLimitError(AppError):
    def __init__(self, message: str = "rate limit exceeded") -> None:
        super().__init__(
            message,
            error_code=ErrorCode.RATE_LIMITED,
            retryable=True,
            http_status=429,
        )


class RetrievalError(AppError):
    def __init__(self, message: str, *, timeout: bool = False) -> None:
        super().__init__(
            message,
            error_code=ErrorCode.RETRIEVAL_TIMEOUT if timeout else ErrorCode.VECTOR_DB_UNAVAILABLE,
            retryable=True,
            http_status=503,
        )


class UnauthorizedError(AppError):
    def __init__(self, message: str = "unauthorized") -> None:
        super().__init__(message, error_code=ErrorCode.UNAUTHORIZED, http_status=401)


class LLMProviderError(AppError):
    def __init__(
        self,
        message: str,
        *,
        timeout: bool = False,
        rate_limited: bool = False,
        retryable: bool | None = None,
    ) -> None:
        if timeout:
            code = ErrorCode.LLM_TIMEOUT
        elif rate_limited:
            code = ErrorCode.LLM_RATE_LIMITED
        else:
            code = ErrorCode.LLM_PROVIDER_UNAVAILABLE
        if retryable is None:
            retryable = True
        super().__init__(message, error_code=code, retryable=retryable, http_status=503)


class LLMOutputError(AppError):
    def __init__(self, message: str) -> None:
        super().__init__(
            message,
            error_code=ErrorCode.LLM_OUTPUT_INVALID,
            retryable=True,
            http_status=502,
        )


class ToolExecutionError(AppError):
    def __init__(self, message: str) -> None:
        super().__init__(
            message,
            error_code=ErrorCode.TOOL_EXECUTION_FAILED,
            retryable=True,
            http_status=502,
        )


class ToolPermissionError(AppError):
    def __init__(self, message: str) -> None:
        super().__init__(
            message,
            error_code=ErrorCode.TOOL_PERMISSION_DENIED,
            http_status=403,
        )


class ConfirmationRequiredError(AppError):
    def __init__(self, message: str) -> None:
        super().__init__(
            message,
            error_code=ErrorCode.ACTION_CONFIRMATION_REQUIRED,
            http_status=409,
        )


class DatabaseError(AppError):
    def __init__(self, message: str) -> None:
        super().__init__(
            message,
            error_code=ErrorCode.DATABASE_UNAVAILABLE,
            retryable=True,
            http_status=503,
        )


class GuardrailError(AppError):
    def __init__(self, message: str, error_code: ErrorCode) -> None:
        super().__init__(message, error_code=error_code, http_status=400)
