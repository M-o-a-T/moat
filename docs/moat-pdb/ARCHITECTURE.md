# Architecture — moat.pdb

Rudimentary debugging entry point (`pdb/_main.py:1`: "Rudimentary
debugging").

## Implementation

A single `main_` command (`cli`) that calls `breakpoint()` then optionally
forwards remaining args to `main_.main(args)`. This drops into Python's
built-in PDB before continuing CLI processing.

## Integration

Registered on the top-level `moat.lib.run.main_` Click group (**not**
`load_subgroup`), so it appears as a direct `moat pdb` command. Essentially
standalone — no subsystem coupling.

## Entry point

`moat pdb [args…]` → `breakpoint()` → forward `args` to the main CLI.
