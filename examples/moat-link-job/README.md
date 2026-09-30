# Code snippets for `moat link job`

Snippets for MoaT-Link's job runner, stored with
`moat link code NAME set -d FILE` (the file's name is `code.NAME.yaml`).
Each has tests in `tests/moat_link_job/`.

| Snippet | Does |
| --- | --- |
| `transform.hass.override` | An override item (a value, or unset for "automatic") as two Home Assistant entities: a value (switch or number) and a "manual" switch. While manual is off, the value entity shows the controlled system's actual state. |
