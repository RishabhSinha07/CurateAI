"""
Shared LLM factory with retry logic for transient Bedrock errors.

All agents should use `get_bedrock_llm()` instead of creating ChatBedrock directly.
"""

import logging
from typing import Any, Dict, Optional

from langchain_aws import ChatBedrock
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception,
    before_sleep_log,
)

from app.config import get_settings

logger = logging.getLogger(__name__)


def _is_transient_bedrock_error(exc: BaseException) -> bool:
    """Check if an exception is a transient Bedrock error worth retrying."""
    from botocore.exceptions import ClientError

    if isinstance(exc, ClientError):
        error_code = exc.response.get("Error", {}).get("Code", "")
        if error_code in (
            "ModelErrorException",
            "ThrottlingException",
            "ServiceUnavailableException",
            "ModelTimeoutException",
            "ModelNotReadyException",
        ):
            return True

    # Also catch generic errors that wrap Bedrock transient failures
    error_msg = str(exc).lower()
    if any(
        term in error_msg
        for term in ("modelerrorexception", "throttling", "service unavailable", "too many requests")
    ):
        return True

    return False


# Reusable retry decorator for Bedrock calls
bedrock_retry = retry(
    retry=retry_if_exception(_is_transient_bedrock_error),
    stop=stop_after_attempt(4),  # 1 initial + 3 retries
    wait=wait_exponential(multiplier=1, min=1, max=8),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True,
)


class _RetryingRunnable:
    """Thin wrapper that adds retry logic around a LangChain Runnable's invoke/ainvoke."""

    def __init__(self, runnable):
        self._runnable = runnable

    @bedrock_retry
    def invoke(self, *args, **kwargs):
        return self._runnable.invoke(*args, **kwargs)

    @bedrock_retry
    async def ainvoke(self, *args, **kwargs):
        return await self._runnable.ainvoke(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._runnable, name)


def get_bedrock_llm(
    model_kwargs: Optional[Dict[str, Any]] = None,
    structured_output_schema=None,
):
    """
    Create a ChatBedrock instance with automatic retry on transient errors.

    Args:
        model_kwargs: Override default model kwargs (default: {"temperature": 0}).
        structured_output_schema: If provided, wraps with .with_structured_output().

    Returns:
        A wrapper with retry-aware invoke/ainvoke methods.
    """
    settings = get_settings()

    if model_kwargs is None:
        model_kwargs = {"temperature": 0}

    llm = ChatBedrock(
        model_id=settings.bedrock_model_id,
        region_name=settings.aws_region,
        model_kwargs=model_kwargs,
    )

    if structured_output_schema is not None:
        runnable = llm.with_structured_output(structured_output_schema)
    else:
        runnable = llm

    return _RetryingRunnable(runnable)
