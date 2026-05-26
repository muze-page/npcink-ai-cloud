Runtime-related test fixtures belong in this directory.

- `cloud/.runtime/**` is runtime-generated output and is ignored by git.
- Checked-in samples for tests should live under `cloud/tests/fixtures/runtime/**`.
- Keep fixtures minimal and purpose-specific so tests do not depend on live
  worker or deploy artifacts.
