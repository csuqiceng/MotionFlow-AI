# Login Preflight Health Design

## Goal

Rework the WebUI login page into a controller-style center card based on the supplied legacy reference, and add real pre-login checks for the controller, voice service, and active AI provider.

## User Experience

The page keeps the existing operator and engineer role tabs, then presents the following order:

1. Controller connection section with an editable IP field. It defaults to the currently configured value (`10.168.3.21`).
2. A **Detect connection** action that runs all three checks and displays controller, voice, and AI results before the credentials.
3. Username and password fields, followed by the login action.

The layout uses a light, centered legacy-style card with a blue outline, a compact segmented role switch, and a green login button. Each service reports `checking`, `healthy` with latency, or `unhealthy` with a short actionable reason.

Changing the controller IP changes the controller status to `pending`; an operator must run a successful check for that exact IP before the login action is enabled. Controller failure blocks operator login. Voice and AI failure remain visible warnings and do not block either role. Engineer login remains available when the controller is unavailable so configuration and diagnosis remain possible.

## Architecture

Add one bootstrap-token-protected, pre-auth health endpoint. It accepts the editable controller IP and returns a normalized three-service payload in a single response. The browser calls it on login-page bootstrap and when the user presses **Detect connection**.

The controller check uses a read-only backend connection for the requested address; it never writes a command to the device. The server validates the address as an allowed local/private controller address before making a connection, preventing arbitrary network probing through the unauthenticated login page.

The voice check performs a real, non-interactive transport/provider availability probe for the currently active voice configuration. It does not record from the microphone, play audio, or synthesize audible output. The AI check performs a lightweight request against the currently active AI provider. Provider-specific non-generating health/model metadata endpoints are preferred; where unavailable, the explicit preflight action may make the smallest supported provider request. Results include a safe status reason and elapsed milliseconds, never credentials or provider responses.

## Error Handling and Security

- The endpoint requires the temporary bootstrap bearer token already minted for the login page.
- Controller targets are limited to valid private/loopback addresses and the configured controller; public, malformed, and hostname targets are rejected before networking.
- All checks use bounded timeouts and return structured per-service failures instead of failing the whole request.
- No user password, API secret, raw provider payload, voice content, or robot command is sent in a check response.
- Controller checks remain read-only and do not alter the configured runtime controller host; the entered IP is a per-check value until an authenticated engineer changes persistent configuration elsewhere.

## State and Accessibility

The login UI tracks a checked controller IP, current service results, checking state, and the active role. The operator submit button is disabled while controller status is pending, checking, or unhealthy; its explanatory status remains accessible to screen readers. Engineering login is not disabled by controller status. The existing login throttle, credential errors, bootstrap failure state, focus behavior, and keyboard submit behavior remain intact.

## Testing

Backend tests cover bootstrap-token enforcement, controller-target validation, timeout/error normalization, no-write controller probing, and independent voice/AI failure handling. Frontend tests cover initial detection, manual retry, editable IP resetting controller readiness, operator blocking, engineer availability, accessible status messages, and preservation of existing login error behavior.
