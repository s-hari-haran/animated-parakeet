# Engineering Design Specifications

## Observability

- Log request context with `appointment_id`, `locale`, and `idempotency_key` when calling the TTS client.
- Avoid logging patient phone numbers or full SSML bodies in normal operation.
- Trace outbound HTTP calls and record status code, retry count, and breaker state transitions.
- Alert on repeated `CircuitBreakerOpenException` events and sustained `5xx` or timeout spikes.

## Idempotency Strategy

- Build the idempotency key from a canonical serialization of the full appointment input.
- Keep the key deterministic across retries and repeated calls with the same input.
- Use the same key on the downstream synthesize request so cached or duplicate requests can be deduplicated.

## Feature Flags

- Locale rollout for new voices or language variants.
- Circuit breaker thresholds and retry budget tuning.
- Any future escalation from stubbed localized bodies to richer translated scripts.

## Intentionally Left Out

- No Redis or shared cache layer; the package stays stateless and lightweight.
- No framework or service wrapper; this is a library, not an HTTP server.
- No vendor SDK dependency; `httpx` is enough for the TTS contract.
- No extra speech markup abstractions beyond what the TTS boundary needs.