#!/usr/bin/env python3
"""Verify Python environment setup for Zerna platform."""

import os
import subprocess
import sys
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def check_package_structure():
    """Verify all expected packages exist with pyproject.toml."""
    packages = [
        "apps/api",
        "packages/contracts",
        "services/compute",
        "services/gpu_abstraction",
        "methods",
        "workflows",
    ]

    missing = []
    for pkg in packages:
        pyproject = Path(pkg) / "pyproject.toml"

        if not pyproject.exists():
            missing.append(f"{pkg}/pyproject.toml")

    if missing:
        print("❌ Missing files:")
        for f in missing:
            print(f"  - {f}")
        return False

    print("✅ All package structures are correct")
    return True


def check_lock_file():
    """Verify uv.lock exists."""
    if not Path("uv.lock").exists():
        print("❌ uv.lock not found")
        return False

    print("✅ uv.lock exists")
    return True


def check_manifest_runtime_edges():
    """Verify workspace packages declare the runtime dependencies they import."""
    expected = {
        "methods/pyproject.toml": {"zerna-contracts"},
        "workflows/pyproject.toml": {"zerna-api", "zerna-contracts", "zerna-methods"},
        "services/compute/pyproject.toml": {"zerna-methods"},
    }

    ok = True
    for manifest_path, required in expected.items():
        data = tomllib.loads(Path(manifest_path).read_text())
        deps = set(data.get("project", {}).get("dependencies", []))
        missing = sorted(dep for dep in required if dep not in deps)
        if missing:
            print(f"❌ {manifest_path} is missing dependencies: {', '.join(missing)}")
            ok = False
        else:
            print(f"✅ {manifest_path} declares required workspace dependencies")
    return ok


def check_runtime_imports():
    """Verify the critical runtime modules import in the current environment."""
    modules = [
        "apps.api.main",
        "methods.preprocessing.doublet_detection",
        "workflows.run_execution.activities",
    ]

    for module_name in modules:
        result = subprocess.run(
            ["uv", "run", "python", "-c", f"import {module_name}"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip() or "unknown import failure"
            print(f"❌ Failed to import {module_name}: {detail}")
            return False
        print(f"✅ {module_name} imports successfully")

    return True


def check_r_method_runtime():
    """Verify the R-backed scientific methods are actually available."""
    if os.environ.get("ZERNA_SKIP_R_VERIFY", "").strip() in ("1", "true", "yes"):
        print(
            "⚠️  Skipping R scientific runtime check (ZERNA_SKIP_R_VERIFY is set). "
            "Docker workers still use the image R stack; for host R (e.g. Cairo), install XQuartz on macOS."
        )
        return True
    packages = [
        "scDblFinder",
        "DoubletFinder",
        "scds",
        "SoupX",
        "SingleCellExperiment",
        "Seurat",
        "BiocParallel",
        "Cairo",
        "textshaping",
        "ragg",
        "ggrastr",
    ]

    result = subprocess.run(
        [
            "Rscript",
            "-e",
            (
                "pkgs <- c(" + ", ".join(f'"{pkg}"' for pkg in packages) + "); "
                "missing <- pkgs[!vapply(pkgs, requireNamespace, logical(1), quietly=TRUE)]; "
                "cat(paste(missing, collapse=','))"
            ),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "unknown R runtime failure"
        print(f"❌ Failed to verify R scientific runtime: {detail}")
        return False

    missing = [pkg for pkg in result.stdout.strip().split(",") if pkg]
    if missing:
        print(f"❌ Missing R scientific packages: {', '.join(missing)}")
        return False

    print("✅ R scientific runtime packages are available")
    return True


def main():
    """Run all verification checks."""
    print("Verifying Python environment setup...\n")

    checks = [
        check_package_structure(),
        check_lock_file(),
        check_manifest_runtime_edges(),
        check_runtime_imports(),
        check_r_method_runtime(),
    ]

    if all(checks):
        print("\n✅ Python environment setup is complete!")
        return 0
    else:
        print("\n❌ Python environment setup has issues")
        return 1


if __name__ == "__main__":
    sys.exit(main())
