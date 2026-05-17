# reminder_service

Small Python 3.11+ library for generating reminder SSML and calling a TTS backend.

## Install

```bash
pip install pydantic httpx pytest hypothesis
```

## Run Tests

```bash
pytest
```

## Contract Decisions

- `Appointment` is a Pydantic boundary model; `phone_number` is validated as strict E.164 with a leading `+`.
- `generate_reminder()` is deterministic: the same appointment input produces the same SSML and the same idempotency key.
- English is a full SSML script with pauses, prosody, and digit-by-digit phone readback; Spanish and Arabic are production-shaped stubs.
- `TTSClient` is async, uses bounded exponential backoff with jitter, treats `4xx` as terminal except `429`, and uses a circuit breaker for repeated upstream failures.
- No web framework is used; this stays a lightweight library.

## AI Assistance

This implementation was drafted with AI assistant support and then checked against the test suite.