# Diagram sources — Lab 005

- Official entry point: https://cloud.google.com/icons
- Official archive: https://services.google.com/fh/files/misc/google-cloud-legacy-icons.zip
- Service icons: Compute Engine, Cloud Load Balancing, Cloud SQL. Original geometry and colors preserved; embedded SVGs have no remote image dependency.
- Browser, scope frames and operational annotations are generic, not official service icons.
- Archive and individual icon hashes: [diagram-provenance.json](diagram-provenance.json).
- Layout follows [diagram conventions](../../../docs/diagram-style.md): regional subnets span both zones; managed SQL producer is outside the workload VPC; vertical VM pairs keep fan-out short.
- Both SVG sources were rendered at 960 px and visually reviewed in GitHub Actions run 39928910636, source 1d7d8fdba7b9d77dae492c6baf38c035e4040346. PNGs are saved beside their SVG sources.
- These are architecture and operational-design illustrations, not GCP execution evidence or measured availability claims.
