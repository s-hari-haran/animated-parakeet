import asyncio
from datetime import datetime

import httpx
import pytest
from hypothesis import given, settings, strategies as st

from reminder_service.client import CircuitBreaker, CircuitBreakerOpenException, TTSClient, TerminalClientException
from reminder_service.models import Appointment
from reminder_service.service import generate_reminder


@pytest.fixture
def sample_appointment() -> Appointment:
    return Appointment(
        appointment_id="appt-uuid-99992",
        patient_name="Hari Haran S",
        phone_number="+18005550199",
        appointment_time=datetime(2026, 12, 25, 9, 0),
        locale="en",
    )


def test_idempotent_ssml_generation(sample_appointment: Appointment) -> None:
    res_one = generate_reminder(sample_appointment)
    res_two = generate_reminder(sample_appointment)

    assert res_one.idempotency_key == res_two.idempotency_key
    assert res_one.ssml == res_two.ssml
    assert "1 8 0 0 5 5 5 0 1 9 9" in res_one.ssml
    assert "<break time='300ms'/>" in res_one.ssml


def test_locale_dispatch_for_spanish(sample_appointment: Appointment) -> None:
    reminder = generate_reminder(sample_appointment.model_copy(update={"locale": "es"}))
    assert "Hola" in reminder.ssml


def test_locale_dispatch_for_arabic(sample_appointment: Appointment) -> None:
    reminder = generate_reminder(sample_appointment.model_copy(update={"locale": "ar"}))
    assert "Marhaban" in reminder.ssml


def _transport_for(responses_or_errors):
    state = {"index": 0, "calls": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        state["calls"] += 1
        item = responses_or_errors[min(state["index"], len(responses_or_errors) - 1)]
        state["index"] += 1
        if isinstance(item, Exception):
            raise item
        return item

    return httpx.MockTransport(handler), state


def _run(coro):
    return asyncio.run(coro)


def test_tts_client_happy_path_200() -> None:
    transport, state = _transport_for([
        httpx.Response(200, json={"audio_url": "https://cdn.audio/vlog_out.mp3"}),
    ])
    client = TTSClient("https://api.teratts.local", transport=transport)

    url = _run(client.synthesize("<speak></speak>", "key_1", "voice_en"))

    assert url == "https://cdn.audio/vlog_out.mp3"
    assert state["calls"] == 1


def test_tts_client_happy_path_202() -> None:
    transport, state = _transport_for([
        httpx.Response(202, json={"audio_url": "https://cdn.audio/cached.mp3"}),
    ])
    client = TTSClient("https://api.teratts.local", transport=transport)

    url = _run(client.synthesize("<speak></speak>", "key_1", "voice_en"))

    assert url == "https://cdn.audio/cached.mp3"
    assert state["calls"] == 1


def test_tts_client_429_retries_using_retry_after(monkeypatch: pytest.MonkeyPatch) -> None:
    transport, state = _transport_for([
        httpx.Response(429, json={"retry_after": 2}),
        httpx.Response(200, json={"audio_url": "https://cdn.audio/recovered.mp3"}),
    ])
    client = TTSClient("https://api.teratts.local", transport=transport)
    sleeps = []

    async def fake_sleep(duration: float) -> None:
        sleeps.append(duration)

    monkeypatch.setattr("reminder_service.client.asyncio.sleep", fake_sleep)

    url = _run(client.synthesize("<speak></speak>", "key_1", "voice_en"))

    assert url == "https://cdn.audio/recovered.mp3"
    assert state["calls"] == 2
    assert sleeps == [2.0]


def test_tts_client_5xx_retries_with_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    transport, state = _transport_for([
        httpx.Response(500, json={"error": "boom"}),
        httpx.Response(200, json={"audio_url": "https://cdn.audio/recovered.mp3"}),
    ])
    client = TTSClient("https://api.teratts.local", transport=transport)
    sleeps = []

    async def fake_sleep(duration: float) -> None:
        sleeps.append(duration)

    monkeypatch.setattr("reminder_service.client.asyncio.sleep", fake_sleep)
    monkeypatch.setattr("reminder_service.client.random.uniform", lambda a, b: 0.0)

    url = _run(client.synthesize("<speak></speak>", "key_1", "voice_en"))

    assert url == "https://cdn.audio/recovered.mp3"
    assert state["calls"] == 2
    assert sleeps == [0.1]


def test_terminal_client_error_handling() -> None:
    transport, state = _transport_for([
        httpx.Response(404, json={"error": "not found"}),
    ])
    client = TTSClient("https://api.teratts.local", transport=transport)

    with pytest.raises(TerminalClientException):
        _run(client.synthesize("<speak></speak>", "key_1", "voice_en"))

    assert state["calls"] == 1


def test_circuit_breaker_trips_after_consecutive_failures() -> None:
    transport, state = _transport_for([
        httpx.ConnectError("Timeout connection drop"),
    ])
    breaker = CircuitBreaker(failure_threshold=3, recovery_time=5.0)
    client = TTSClient("https://api.teratts.local", transport=transport, breaker=breaker, max_retries=1)

    for _ in range(3):
        with pytest.raises(httpx.ConnectError):
            _run(client.synthesize("ssml", "key", "voice"))

    with pytest.raises(CircuitBreakerOpenException):
        _run(client.synthesize("ssml", "key", "voice"))

    assert state["calls"] == 3


def test_circuit_breaker_recovers_after_cooldown(monkeypatch: pytest.MonkeyPatch) -> None:
    transport, state = _transport_for([
        httpx.ConnectError("Timeout connection drop"),
        httpx.Response(200, json={"audio_url": "https://cdn.audio/recovered.mp3"}),
    ])
    breaker = CircuitBreaker(failure_threshold=1, recovery_time=5.0)
    client = TTSClient("https://api.teratts.local", transport=transport, breaker=breaker, max_retries=1)

    with pytest.raises(httpx.ConnectError):
        _run(client.synthesize("ssml", "key", "voice"))

    monkeypatch.setattr("reminder_service.client.time.time", lambda: breaker.last_state_change + 10)

    url = _run(client.synthesize("ssml", "key", "voice"))

    assert url == "https://cdn.audio/recovered.mp3"
    assert state["calls"] == 2


@settings(max_examples=20)
@given(
    st.text(min_size=1, max_size=30),
    st.from_regex(r"^\+[1-9]\d{6,12}$", fullmatch=True),
)
def test_fuzzed_property_handling(name: str, phone: str) -> None:
    appt = Appointment(
        appointment_id="id-fuzz",
        patient_name=name,
        phone_number=phone,
        appointment_time=datetime(2026, 1, 1, 12, 0),
        locale="en",
    )

    res_one = generate_reminder(appt)
    res_two = generate_reminder(appt)

    assert len(res_one.idempotency_key) == 64
    assert res_one.idempotency_key == res_two.idempotency_key
    assert res_one.ssml == res_two.ssml