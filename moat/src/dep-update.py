"""
Find cross-imports between moat packages and update pyproject.toml files
with versioned dependencies.
"""

from __future__ import annotations

import re
from pathlib import Path

import asyncclick as click
import tomlkit as toml

from moat.util import attrdict, yload


@click.command
async def cli():
    """
    Update cross-package dependencies.

    This command should be a no-op, as dependencies are auto-updated
    when building.
    """

    # Load versions.yaml
    with open("versions.yaml", "r") as f:  # noqa:ASYNC230
        versions = yload(f)

    # Map package names to their tags
    package_versions = {}
    for pkg_name, pkg_data in versions.items():
        if "tag" in pkg_data:
            package_versions[pkg_name] = pkg_data["tag"]

    print(f"Loaded {len(package_versions)} package versions")
    print()

    # Find all packages with pyproject.toml
    packages = {}
    for pkg_dir in Path("packaging").iterdir():
        if pkg_dir.is_dir():
            pyproject = pkg_dir / "pyproject.toml"
            if not pyproject.exists():
                continue
            pkg_name = pkg_dir.name
            # Determine source directory
            # Most packages have sources in moat/<subpackage>
            # e.g., moat-kv -> moat/kv, moat-lib-cmd -> moat/lib/cmd

            # Convert package name to module path
            module_parts = pkg_name.replace("moat-", "").split("-")
            if len(module_parts) == 1:
                # e.g., moat -> moat
                if pkg_name == "moat":
                    src_dir = Path("moat")
                else:
                    src_dir = Path("moat") / module_parts[0]
            else:
                # e.g., moat-lib-cmd -> moat/lib/cmd
                src_dir = Path("moat") / "/".join(module_parts)

            packages[pkg_name] = attrdict(
                pyproject=pyproject,
                src_dir=src_dir,
                imports=set(),
            )

    print(f"Found {len(packages)} packages with pyproject.toml")
    print()

    def find_imports_in_file(filepath):
        """Find all moat.* imports in a Python file, including multi-line imports."""
        imports = set()

        try:
            with open(filepath, "r") as f:
                lines = f.readlines()

            i = 0
            while i < len(lines):
                line = lines[i]

                # Check for single-line imports
                # from moat.xxx import ... or import moat.xxx
                single_match = re.match(
                    r"\s*(?:from|import)\s+(moat(?:\.[a-z_][a-z0-9_]*)+)", line
                )
                if single_match and "(" not in line:
                    imports.add(single_match.group(1))
                    i += 1
                    continue

                # Check for multi-line imports with parentheses
                # from moat.xxx import (
                multiline_match = re.match(
                    r"\s*from\s+(moat(?:\.[a-z_][a-z0-9_]*)+)\s+import\s*\(", line
                )
                if multiline_match:
                    imports.add(multiline_match.group(1))
                    # Skip to closing parenthesis
                    while i < len(lines) and ")" not in lines[i]:
                        i += 1
                    i += 1
                    continue

                # Check for import moat.xxx
                import_match = re.match(r"\s*import\s+(moat(?:\.[a-z_][a-z0-9_]*)+)", line)
                if import_match:
                    imports.add(import_match.group(1))

                i += 1

        except Exception as e:
            print(f"Error reading {filepath}: {e}")

        return imports

    # For each package, find what other moat packages it imports
    for pkg_name, pkg_info in packages.items():
        src_dir = pkg_info.src_dir

        if not src_dir.exists():
            print(f"Warning: Source directory {src_dir} does not exist for {pkg_name}")
            continue

        # Find all Python files in the source directory
        for py_file in src_dir.rglob("*.py"):
            file_imports = find_imports_in_file(py_file)

            for imported_module in file_imports:
                # Convert module path to package name
                # moat.kv -> moat-kv
                # moat.lib.rpc -> moat-lib-cmd
                # moat.util -> moat-util

                parts = imported_module.split(".")
                if len(parts) < 2:
                    continue  # Just "moat" - not a subpackage

                # Build package name
                if parts[0] == "moat":
                    if len(parts) == 2:
                        imported_pkg = f"moat-{parts[1]}"
                    else:
                        # moat.lib.rpc -> moat-lib-cmd
                        imported_pkg = "moat-" + "-".join(parts[1:])

                    # Only track if it's a different package and exists
                    if imported_pkg != pkg_name and imported_pkg in packages:
                        pkg_info.imports.add(imported_pkg)

    # Print findings
    print("Package dependencies found:")
    print("===========================")
    for pkg_name, pkg_info in packages.items():
        if pkg_info.imports:
            print(f"\n{pkg_name} imports from:")
            for imp_pkg in pkg_info.imports:
                version = package_versions.get(imp_pkg, "N/A")
                print(f"  - {imp_pkg} (version ~= {version})")

    print("===============================")
    print("\nUpdating pyproject.toml files")
    print()

    # Update pyproject.toml files
    updated_count = 0
    for pkg_name, pkg_info in packages.items():
        if not pkg_info.imports:
            continue

        try:
            with open(pkg_info.pyproject, "r") as f:  # noqa:ASYNC230
                pyproject = toml.load(f)

            try:
                current_deps = pyproject["project"]["dependencies"]
            except KeyError:
                print(f"Warning: {pkg_name} has no dependencies section")
                continue

            # Track what needs to be added/updated
            changes = []

            for imp_pkg in pkg_info.imports:
                if imp_pkg not in package_versions:
                    print(f"Warning: No version found for {imp_pkg}")
                    continue

                version = package_versions[imp_pkg]
                dep_string = f"{imp_pkg} ~= {version}"

                # Check if dependency exists
                for i, dep in enumerate(current_deps):
                    if isinstance(dep, str) and dep.startswith(imp_pkg + " "):
                        if dep != dep_string:
                            changes.append(f"  Update: {current_deps[i]} -> {dep_string}")
                            current_deps[i] = dep_string
                        break
                else:
                    # Add new dependency
                    changes.append(f"  Add: {dep_string}")
                    current_deps.append(dep_string)

            if changes:
                print(f"{pkg_name}:")
                for change in changes:
                    print(change)

                # Write updated pyproject.toml
                with open(pkg_info.pyproject, "w") as f:  # noqa:ASYNC230
                    toml.dump(pyproject, f)

                updated_count += 1
                print(f"  ✓ Updated {pkg_info.pyproject}")
                print()

        except Exception as e:
            print(f"Error updating {pkg_name}: {e}")
            import traceback  # noqa:PLC0415

            traceback.print_exc()

    print(f"\nUpdated {updated_count} pyproject.toml files")
