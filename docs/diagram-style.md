# Cloud solution diagrams — Personal Custom

This document applies the user's **Diagram Design — Personal Custom** style to Portfolio-Lab diagrams. The ZIP package is the canonical visual reference; the rules below keep lab diagrams consistent while preserving each provider's technical model. The lab brief and official provider documentation remain the source for architecture facts.

Style attribution: adapted from Cathryn Lavery / LittleMight, [diagram-design](https://github.com/cathrynlavery/diagram-design) (MIT).

## Visual target and palette

Use a clean, information-first architecture plate: a very pale paper or white canvas, recognizable official service icons, labels beneath icons, truthful nested scope frames, softly tinted functional tiers, and clearly routed arrows. Use one figure per question, or an overview plus detail when one figure becomes crowded. Never add components just to fill the canvas.

Use the following default palette consistently. Select roughly 3–5 meaningful roles for a small solution, and use both labels and visual treatments so meaning never depends on color alone.

| Role | Border / heading | Light background |
|---|---|---|
| Canvas / paper | Ink #1F2937 | #F7FAFF |
| Compute / application | #2563EB | #EFF6FF |
| Network / VPC | #0F766E | #F0FDFA |
| Ingress / load balancing | #C2410C | #FFF7ED |
| Data / storage | #7C3AED | #F5F3FF |
| Administration / identity | #475569 | #F1F5F9 |
| Healthy / recovery | #15803D | #F0FDF4 |
| Failure / blocked path | #B91C1C | #FEF2F2 |

Use status colors only for documented states; a proposed design does not imply that a test passed. Avoid shadows, decorative gradients/glows, and giant rounded pills. Keep borders thin and consistent, use a 4 px spacing grid and modest 4–8 px corners, and maintain readable contrast.

## Composition and boundaries

- Place clients, users, on-premises actors and external platforms outside the cloud boundary. Show only actors relevant to the solution.
- Draw actual containment: provider/account or project, region where relevant, VPC/VNet, availability zone, subnet and workload group. Nest only where technically true. Global services may sit inside the provider/project frame but outside regional or VPC frames. External SaaS remains outside the provider boundary.
- Follow the provider's model. For example, a GCP regional subnet can serve VMs in multiple zones; do not imply one subnet per zone unless configured. AWS subnets are zonal.
- Distinguish frames with thin colored borders, selectively dashed for secondary scopes, and top-left header tabs/icons. Show actual region, zone and subnet labels when supplied.
- Group actual application tiers in pale green, blue, teal, orange or lavender panels with functional headings such as Public ingress, Application, Data, Management or Security. Keep the request flow dominant. Do not add DevOps, AI, databases or observability products merely to fill space.
- Keep small solutions compact. Do not imitate an enterprise-sized reference when the system has only a few components.

## Service icons, labels and accessibility

- Prefer verified official GCP/AWS/Azure assets, retaining original geometry, colors and proportions from one coherent icon set. Do not draw fake vendor symbols or recolor official glyphs.
- Use service icons around 48–72 px at the intended viewing size, with short centered names beneath and optional resource IDs on a second line. Use 24–32 px boundary/header icons. Disclose clearly labeled generic fallbacks.
- Use readable sans typography, with monospace only for technical IDs and ports. Typical service labels are 13–16 px, scope headings 16–20 px; adjust to final rendered size. Support Thai glyphs and avoid clipping.
- Preserve an editable SVG source and a PNG preview when rendering is available. Embed the diagram in its requested Markdown guide; do not build an application UI unless requested.
- Give SVGs `role="img"`, `aria-labelledby`, a title and description. Use readable contrast and redundant labels/dashes so a monochrome view remains understandable.
- Record official asset source URLs and attribution. Keep embedded assets and CSS namespaced to avoid collisions.

## Connections

- Route orthogonal arrows through clear gutters. Attach them to visible icon edges or explicit group/resource attachment points, avoiding labels and unrelated frames.
- Draw actual request direction and dependencies; proximity does not establish a connection. Distinguish user traffic, management, replication and health checks with consistent line treatments where useful. Label protocol/port and primary/standby semantics when they affect understanding.
- Use thin lines for routine calls; emphasize the primary flow only when it improves hierarchy. Add a compact legend only when color/dash meanings need explanation.
- Prefer direct routes or one short elbow. Share a visible trunk only for a real one-to-many relationship, with a junction dot where needed. Never share a trunk between unrelated protocols; give traffic types distinct attachment points.
- Distinguish unavoidable unrelated-line crossings from junctions with a gap or bridge. A junction dot means a true shared branch. Leave a clear gap at a crossing and put arrowheads only at destinations.

## Connectivity-first layout selection

Before fixing coordinates, sketch the main connections and compare row and column arrangements for repeated workloads. Choose the arrangement that makes important connections short and legible; visual symmetry is secondary.

For a left-to-right flow with one load balancer feeding two backends, consider vertically stacking the backends with a compact branch between the load balancer and backends. Place management on the opposite side for short direct connections, and keep health checks in their own clear routing lane. This is an option, not a rule that all compute must be vertical.

Review routes by crossings first, then unnecessary bends, then total length. If a line wraps around a tier, passes behind a sibling group, or circles the diagram edge to reach a nearby node, reconsider node order, tier orientation or panel position. Do not hide a weak layout with long perimeter connectors. Preserve real cloud scope boundaries and keep connectors out of header/label bands. Crossing a boundary on the way to a contained resource is acceptable; crossing an unrelated resource is not.

## Final review at document width

Render at the intended document width, typically 900–1000 px, and inspect the saved final source. Check scope placement, global versus regional resources, readable labels, boundary headers, connector endpoints, crossings, clipping and wasted margins. Make operational resource IDs prominent enough to correlate with test evidence.

Account for transparent SVG viewBox padding so arrow tips meet visible glyph geometry; avoid floating tips, glyph overlap or endpoints beside unrelated labels. Trim empty top margins and unused panel space without crowding scope labels, then re-render and inspect again. A preview must show the final saved source.

Describe the system itself in lab artifacts. Do not include conversation history or commentary about future portfolio plans.

## Repository asset contract (Lab 01–20)

Every solution Lab publishes its **editable architecture diagram** in `GCP/LAB-NNN-*/assets/diagrams/` and links that location **relatively** from its README:

- `assets/diagrams/solution.svg`: primary architecture plate, accessible title/description and truthful scope
- `assets/diagrams/*-flow.svg`, `operations.svg` or `recovery.svg`: secondary technical views only when useful
- `assets/diagrams/*-preview.png`: optional rendered preview from the corresponding SVG
- `assets/diagrams/solution.html`: optional standalone offline preview; not a substitute for SVG

Existing paths in `assets/` remain **temporary compatibility mirrors** for old scripts/renderers/tests. They contain the same bytes as the corresponding published assets. Future changes must update the `assets/diagrams/` publication and mirror the old path until migration is complete. Run `python scripts/check-diagram-mirrors.py` from repository root to detect drift and broken local links; this check is not a visual QA substitute. Do not delete the compatibility paths while tests/render scripts still refer to them.

The requested Diagram Design Personal Custom Skill must be used when **creating or visually redesigning** diagrams if it is available in the execution environment. Styling rules or a provenance string alone **do not prove the Skill ran**. When unavailable, keep the existing editable SVG and record the limitation; do not claim the diagrams were redrawn with the Skill. `diagram-design.zip` is an external visual reference in the user's environment and is not version-controlled in this repository.

## Visual consistency acceptance gate

Use the same layout tokens, provider-icon geometry/provenance and semantics across all 20 Lab architectures while respecting differences in system topologies. Before marking each diagram `Visual-reviewed`, open its **actual rendered image** at ~1000 px reading width and confirm: (1) correct GCP project/region/VPC scope, (2) all significant flows/routes and labels readable, (3) no connector crossings through icons/text, (4) no clipping or tiny type, (5) no misleading network containment, and (6) no decoration misrepresenting service operation. An automated color test alone is insufficient.

See [the 20-Lab diagram alignment audit](diagram-audit.md). The audit is intentionally **not** marked visually complete solely because SVGs exist or CI renders successfully.
