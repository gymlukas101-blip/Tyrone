"""Write THIRD_PARTY_LICENSES.txt: every installed Python package that ships in the app, with its license.

Run in the build environment right before PyInstaller (CI does). Hand-written notices for models, data and the web
UI's libraries are in THIRD_PARTY_NOTICES.md; both files ship next to Monkey.exe.
"""
from __future__ import annotations

import sys
from importlib import metadata
from pathlib import Path

SKIP = {"pip", "setuptools", "wheel", "pyinstaller", "pyinstaller-hooks-contrib", "pytest", "pluggy", "iniconfig",
        "altgraph", "pefile", "macholib", "monkey"}


def license_of(dist: metadata.Distribution) -> str:
    md = dist.metadata
    expr = md.get("License-Expression")
    if expr:
        return expr
    classifiers = [c.split("::")[-1].strip() for c in md.get_all("Classifier") or [] if c.startswith("License ::")]
    if classifiers:
        return "; ".join(dict.fromkeys(classifiers))
    lic = (md.get("License") or "").strip()
    if lic and len(lic) < 80 and "\n" not in lic:
        return lic
    return "see the package's license file" if lic else "not stated in package metadata"


def main(out: Path) -> None:
    rows = []
    for d in metadata.distributions():
        name = d.metadata.get("Name") or ""
        if not name or name.lower() in SKIP:
            continue
        home = d.metadata.get("Home-page") or next(
            (u.split(",", 1)[1].strip() for u in d.metadata.get_all("Project-URL") or [] if "," in u), "")
        rows.append((name.lower(), name, d.version, license_of(d), home))
    rows.sort()
    lines = ["Third-party Python packages included in Monkey", "=" * 48,
             "Generated from the build environment's package metadata. Each package's own license text is in its",
             "distribution (site-packages/<name>.dist-info). Models and data: see THIRD_PARTY_NOTICES.md.", ""]
    for _, name, ver, lic, home in dict.fromkeys(rows):
        lines.append(f"{name} {ver} — {lic}" + (f" — {home}" if home else ""))
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {out} ({len(rows)} packages)")


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else Path("THIRD_PARTY_LICENSES.txt"))
