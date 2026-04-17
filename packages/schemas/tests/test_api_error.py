import pytest
from pydantic import ValidationError

from workgraph_schemas import ApiError, ApiErrorCode


def test_api_error_roundtrip():
    err = ApiError(code=ApiErrorCode.validation, message="bad input", details={"field": "name"})
    dumped = err.model_dump()
    assert dumped["code"] == "validation_error"
    assert dumped["message"] == "bad input"
    assert dumped["details"] == {"field": "name"}
    assert dumped["trace_id"] is None


def test_api_error_with_trace_id():
    err = ApiError(code=ApiErrorCode.internal, message="boom", trace_id="abc-123")
    assert err.trace_id == "abc-123"


def test_api_error_rejects_empty_message():
    with pytest.raises(ValidationError):
        ApiError(code=ApiErrorCode.internal, message="")


def test_api_error_rejects_unknown_code():
    with pytest.raises(ValidationError):
        ApiError.model_validate({"code": "unknown_code", "message": "x"})


def test_api_error_rejects_extra_fields():
    with pytest.raises(ValidationError):
        ApiError.model_validate(
            {"code": "internal_error", "message": "x", "surprise": True}
        )
