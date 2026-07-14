# Robot WebUI Chinese Localization Design

## Goal

Make the robot login and engineer command/flow workbench display Chinese when
the active locale is `zh-CN`, without changing API behavior, permissions, or
robot execution behavior.

## Scope

- Replace hard-coded English UI text in the login preflight area and engineer
  workbench with translation keys.
- Add the corresponding `zh-CN` strings.
- Keep English strings available through the existing language switcher.
- Cover Chinese rendering in the affected UI tests.

## Design

The existing `useTranslation` pattern remains the single UI text source. New
keys live under `login.preflight` and `library.workbench`, so the login page
and workbench components do not embed locale-specific text. Existing API error
messages are not translated in this change because they are server responses,
not presentation labels.

## Safety and verification

This change only changes displayed labels. It does not create, publish, execute,
or alter robot commands and flows. Verification will run the localized UI
tests, workbench tests, and the production frontend build.
