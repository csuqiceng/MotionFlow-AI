# Engineer Command and Flow Workbench Design

## Goal

Provide engineers a WebUI workbench for safely creating, editing, validating, and publishing robot commands and flows without changing a currently published definition in place.

## Scope

- Add engineer-only command and flow authoring views beside the existing read-only library.
- Keep published versions immutable. Editing a published item creates or resumes one draft; publishing atomically promotes the validated draft to the next version.
- Keep operator access read-only.
- Record creation, draft edits, publishing, and archiving in the existing audit trail.
- Do not execute robot motion as part of authoring or publishing.

## User Flow

1. An engineer opens the library and chooses Commands or Flows.
2. The engineer selects an existing item or chooses New.
3. The workbench opens a draft editor. Existing published items first create a draft from their current published version.
4. The engineer saves the draft, validates it, then explicitly publishes it.
5. A publish replaces only the active version pointer after validation succeeds; the prior published version remains retained for audit/history.

## Command Workbench

The command editor uses the existing versioned command registry and engineer API. It exposes name, aliases, description, component, and component parameters. It uses the existing lifecycle: create entity, start or update draft, publish, archive. The frontend adds an engineer client and editor UI; it must not bypass the existing role and revision checks.

## Flow Workbench

Flows gain a versioned registry parallel to commands. A flow draft contains name, description, delay and rehearsal settings, plus ordered steps. Each step identifies an action/component, parameters, speed, position reference, and description. The editor supports add, remove, and reorder. Validation rejects invalid step shape, unknown command/component references, invalid parameters, and an empty flow. Publishing is explicit and versioned.

## API and Security

The gateway continues to use the authenticated GET transport with `X-Nanobot-Robot-Body` and an engineer action header for mutations. Endpoints require both a valid gateway token and an engineer user token. Every write verifies optimistic revision state and returns a conflict rather than silently overwriting another draft.

## Verification

- Unit tests cover command and flow draft lifecycle, role denial, validation, revision conflicts, and audit events.
- Frontend tests cover role-gated workbench controls, editing drafts, validation errors, and publish confirmation.
- Browser verification creates only a test draft and confirms that publishing changes library metadata; it sends no robot execution request.
