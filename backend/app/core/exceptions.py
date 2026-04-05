from __future__ import annotations


class AppError(Exception):
    def __init__(self, message: str, code: str, status: int = 400) -> None:
        self.message = message
        self.code = code
        self.status = status
        super().__init__(message)


class NotFoundError(AppError):
    def __init__(self, entity: str, entity_id: int | str) -> None:
        super().__init__(f"{entity} {entity_id} not found", f"{entity.upper()}_NOT_FOUND", 404)


class GeocodingError(AppError):
    def __init__(self, address: str) -> None:
        super().__init__(f"Failed to geocode: {address}", "GEOCODING_FAILED", 502)


class TelegramAuthError(AppError):
    def __init__(self, detail: str = "") -> None:
        message = f"Telegram authentication failed: {detail}" if detail else "Telegram authentication failed"
        super().__init__(message, "TELEGRAM_AUTH_FAILED", 503)


class LLMExtractionError(AppError):
    def __init__(self, detail: str = "") -> None:
        message = f"LLM extraction failed: {detail}" if detail else "LLM extraction failed"
        super().__init__(message, "LLM_EXTRACTION_FAILED", 502)


class ExternalServiceCircuitOpen(AppError):
    def __init__(self, service: str) -> None:
        super().__init__(f"{service} circuit open — skipping for remainder of cycle", "CIRCUIT_OPEN", 503)
