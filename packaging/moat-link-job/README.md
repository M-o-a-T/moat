# Background job runner

% start synopsis
% start main

Background job runner for MoaT-Link.

This package provides ``moat link job``: a service that periodically
runs code snippets stored in MoaT-Link, mirroring the behaviour of the
legacy ``moat kv job``.

% end synopsis

## Storage

Static job records live below ``cfg.link.job.prefix`` (default ``job``).
Per-run dynamic status lives below ``cfg.link.job.state`` (default
``run.job``).  Code snippets are resolved through ``moat.link.code``.

% end main

## Usage

```
moat link job [-n NODE] [-g GROUP] info
moat link job [-n NODE] [-g GROUP] at PATH list|get|set|delete|state|path
moat link job [-n NODE] [-g GROUP] run [-n NODES]
moat link job [-n NODE] [-g GROUP] monitor
```

## Services

| Unit | Runs |
| --- | --- |
| ``moat-link-job`` | any-node runner, group ``default`` (enabled on install) |
| ``moat-link-job@GROUP`` | any-node runner for GROUP |
| ``moat-link-job-all[@GROUP]`` | all-nodes runner |
| ``moat-link-job-single[@GROUP]`` | single-node runner; ``NAME`` from ``/etc/moat/link.env`` |

They mirror the ``moat-kv-run-*`` units. See the cutover procedure in the
documentation for switching from ``moat kv job``.

## License

This project is licensed under the same terms as MoaT.
