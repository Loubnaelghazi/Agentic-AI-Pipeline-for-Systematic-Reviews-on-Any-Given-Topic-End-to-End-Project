"""Bounded retries for read-only local inference; validation errors are not retried."""

import asyncio
import logging
import time

import httpx
import requests
from ollama import ResponseError

from config import OLLAMA_RETRY_ATTEMPTS

logger = logging.getLogger(__name__)


def transient_error(error):
    if isinstance(error, ResponseError):
        return error.status_code == 429 or (error.status_code or 0) >= 500
    if isinstance(error, requests.HTTPError):
        return error.response is not None and (
            error.response.status_code == 429 or error.response.status_code >= 500
        )
    return isinstance(
        error,
        (
            httpx.TransportError,
            requests.ConnectionError,
            requests.Timeout,
            ConnectionError,
            TimeoutError,
        ),
    )


def retry_ollama(operation, attempts=None):
    attempts = OLLAMA_RETRY_ATTEMPTS if attempts is None else attempts
    for attempt in range(max(1, attempts)):
        try:
            return operation()
        except Exception as error:
            if not transient_error(error) or attempt + 1 >= attempts:
                raise
            logger.warning(
                "Ollama %s; retry %s/%s after reconnect delay",
                type(error).__name__,
                attempt + 2,
                attempts,
            )
            time.sleep(min(2 ** (attempt + 1), 8))


async def retry_ollama_async(operation, attempts=None):
    attempts = OLLAMA_RETRY_ATTEMPTS if attempts is None else attempts
    for attempt in range(max(1, attempts)):
        try:
            return await operation()
        except Exception as error:
            if not transient_error(error) or attempt + 1 >= attempts:
                raise
            logger.warning(
                "Ollama %s; async retry %s/%s",
                type(error).__name__,
                attempt + 2,
                attempts,
            )
            await asyncio.sleep(min(2 ** (attempt + 1), 8))
