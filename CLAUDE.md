# platmon

Lightweight platform monitor (board/system status) for Jetson, Raspberry Pi, PCs and other Linux hosts. Personal project, licensed Apache-2.0.

## Dependency rules

- Allowed licenses only: MIT, BSD-2-Clause, BSD-3-Clause, Apache-2.0.
- Forbidden: GPL, LGPL, AGPL (e.g. jetson-stats/jtop), unlicensed or unknown-license code.
- Check the license before adding any dependency, including transitive ones. Do not copy code from forbidden sources.
- Read system data directly from `/proc`, `/sys`, or `tegrastats` output. Call `tegrastats` at runtime; never bundle NVIDIA binaries.

## Scope

- Keep it generic. No company-, AMR-, or customer-specific code, configs, or names.
- "NVIDIA" / "Jetson" only to describe compatibility, never as the product name.
