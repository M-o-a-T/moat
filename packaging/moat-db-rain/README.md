# MoaT-DB-Rain

% start synopsis
% start main

This module provides irrigation scheduling and monitoring for MoaT,
migrated from the legacy Django `rainman` app to a `moat.db.rain`
SQLAlchemy + Alembic submodule. It supersedes the old `rainman` Django
app with command-line CRUD, a scheduler engine, and a per-site
`moat db rain <SITE> monitor` daemon.

% end synopsis
% end main
