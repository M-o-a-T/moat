# Notification gateway

% start synopsis
% start main

Notification gateway for MoaT-Link.

This package provides notification services for MoaT-Link, allowing you to send
notifications to external services.

It includes an error mirror that watches the `error.*` subtree and forwards
qualifying entries to the `notify.*` subtree based on dynamically-configured
rules stored in a notify-vecs tree below `conv.*`.

% end synopsis

## Backends

Currently the only implemented backend is `ntfy.sh`.

% end main

## Usage

The notification gateway can be configured through MoaT-Link's configuration system.

### Error mirroring

Run `moat link notify mirror` to start the error mirror.  Set
`link.notify.vecs` to a path below `conv.*` holding the mirroring rules.
See `docs/moat-link/errors.md` for details.

## License

This project is licensed under the same terms as MoaT.
