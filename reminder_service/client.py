import asyncio
import random
import time
from typing import Literal, Optional

import httpx


class CircuitBreakerOpenException(Exception):
    pass


class TerminalClientException(Exception):
    pass


class CircuitBreaker:
    def __init__(self, failure_threshold: int = 3, recovery_time: float = 5.0):
        self.failure_threshold = failure_threshold
        self.recovery_time = recovery_time
        self.failure_count = 0
        self.state: Literal["CLOSED", "OPEN", "HALF-OPEN"] = "CLOSED"
        self.last_state_change = time.time()

    def record_success(self) -> None:
        self.failure_count = 0
        self.state = "CLOSED"

    def record_failure(self) -> None:
        self.failure_count += 1
        if self.failure_count >= self.failure_threshold or self.state == "HALF-OPEN":
            self.state = "OPEN"
            self.last_state_change = time.time()

    def allow_request(self) -> bool:
        if self.state == "OPEN":
            if time.time() - self.last_state_change > self.recovery_time:
                self.state = "HALF-OPEN"
                return True
            return False
        return True


class TTSClient:
    def __init__(
        self,
        base_url: str,
        timeout: float = 2.0,
        breaker: Optional[CircuitBreaker] = None,
        max_retries: int = 3,
        base_backoff: float = 0.1,
        max_backoff: float = 1.0,
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.breaker = breaker or CircuitBreaker()
        self.max_retries = max_retries
        self.base_backoff = base_backoff
        self.max_backoff = max_backoff
        self.transport = transport

    async def synthesize(self, ssml: str, idempotency_key: str, voice: str) -> str:
        if not self.breaker.allow_request():
            raise CircuitBreakerOpenException("Circuit breaker state is OPEN. Request dropped to protect upstream service.")

        url = f"{self.base_url}/v1/synthesize"
        payload = {"ssml": ssml, "idempotency_key": idempotency_key, "voice": voice}

        async with httpx.AsyncClient(transport=self.transport) as client:
            for attempt in range(self.max_retries):
                try:
                    response = await client.post(url, json=payload, timeout=self.timeout)

                    if response.status_code in (200, 202):
                        self.breaker.record_success()
                        return response.json()["audio_url"]

                    if response.status_code == 429:
                        if attempt == self.max_retries - 1:
                            self.breaker.record_failure()
                            raise httpx.ConnectError("Rate limited beyond retry budget.")

                        retry_after = response.json().get("retry_after", 1)
                        await asyncio.sleep(max(0.0, float(retry_after)))
                        continue

                    if 400 <= response.status_code < 500:
                        self.breaker.record_failure()
                        raise TerminalClientException(f"Terminal Client Error Exception encountered: {response.status_code}")

                    if response.status_code >= 500:
                        if attempt == self.max_retries - 1:
                            self.breaker.record_failure()
                            raise httpx.ConnectError(f"Upstream server error: {response.status_code}")

                        sleep_duration = min(self.max_backoff, (self.base_backoff * (2 ** attempt)) + random.uniform(0, 0.05))
                        await asyncio.sleep(sleep_duration)
                        continue

                    self.breaker.record_failure()
                    raise TerminalClientException(f"Unexpected response status: {response.status_code}")

                except httpx.TimeoutException:
                    if attempt == self.max_retries - 1:
                        self.breaker.record_failure()
                        raise

                    sleep_duration = min(self.max_backoff, (self.base_backoff * (2 ** attempt)) + random.uniform(0, 0.05))
                    await asyncio.sleep(sleep_duration)

                except httpx.RequestError:
                    if attempt == self.max_retries - 1:
                        self.breaker.record_failure()
                        raise

                    sleep_duration = min(self.max_backoff, (self.base_backoff * (2 ** attempt)) + random.uniform(0, 0.05))
                    await asyncio.sleep(sleep_duration)

            self.breaker.record_failure()
            raise httpx.ConnectError("Max exponential network retry pipeline cycles exhausted without resolution.")