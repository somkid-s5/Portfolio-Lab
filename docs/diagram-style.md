# Cloud solution diagrams — reference style

## Visual target

Match the user's supplied cloud architecture reference in visual language: a white canvas, recognizable provider service icons as the main visual objects, names directly beneath icons, nested scope frames, pastel tier backgrounds, and clearly routed arrows. Think of a complete solution architecture plate rather than a dashboard of text cards. Apply this style to GCP, AWS or Azure using that provider's actual services and boundaries.

The reference is a style example, not a source of technical requirements. Do not copy its service list, ambiguous labels, layout mistakes or connections into a different solution.

## Composition

- Place users, clients, on-premises actors and external platforms outside the cloud boundary. Show only actors relevant to the requested system.
- Draw real containment explicitly: provider/account or project, region where relevant, VPC/VNet, availability zone, subnet and workload group. Nest only where technically true. Global services may sit inside the provider/project frame but outside regional or VPC frames.
- Follow the provider's model. For example, a GCP regional subnet can serve VMs in multiple zones: do not imply one separate subnet per zone unless that is actually configured. AWS subnets are zonal. External SaaS remains outside the provider boundary.
- Distinguish frames with thin colored borders, selectively dashed for secondary scopes, and top-left header tabs/icons. Show actual region, zone and subnet labels when supplied.
- Group application tiers in pale green, blue, teal, orange or lavender panels with colored headings. Use functional names such as Public ingress, Application, Data, Management or Security only when those parts exist.
- Keep central request flow dominant. Place supporting operations/security groups to a side only when they belong to the solution. Do not add DevOps, AI, databases or observability products merely to fill space.
- For a small solution keep the same nested/icon-led style with fewer objects and compact dimensions. Do not imitate the reference's enterprise size without need.

## Service objects and typography

- Make official service icons prominent, normally 48–72 px at the intended viewing size, with short centered service names beneath and optional resource IDs on a second line.
- Use the provider's original full-color glyphs or colored icon tiles from one coherent official set. Do not draw fake vendor symbols, recolor official glyphs or place every service in a large generic text card.
- Use small boundary/header icons around 24–32 px. Pad labels away from frame borders and connectors. Keep service labels readable at normal document width, around 13–16 px; scope headings around 16–20 px.
- If many service objects are required, enlarge the canvas or split an overview and detail rather than shrinking icons and text into illegibility.
- Preserve an editable SVG source and a PNG preview when rendering is available. Embed the diagram in a requested Markdown guide; do not build an application UI unless requested.

## Connections

- Route orthogonal arrows through clear gutters between groups. Connect to icon edges or a clear group attachment point, avoiding labels and unrelated frames.
- Use distinct, consistent treatments for user traffic, management, replication or health checks when present. Label protocol/port and special semantics such as primary/standby where they affect understanding.
- Prefer fine lines for routine calls and a heavier arrow only for the primary flow when it improves hierarchy. Include a compact legend if color/dashing meanings need explanation.
- Draw actual request direction and dependencies; proximity does not establish a connection. Avoid misleading apparent links at line crossings.

## Review before delivery

Check scope placement, global versus regional resources, readable icon labels, boundary headers, arrow endpoints and crossings. Render at the target document width and fix clipping or crowding. Keep the technical model truthful even when a reference image uses different or incorrect containment. When reusing this style, describe the resulting system directly rather than mentioning the user's conversation or future portfolio plans inside the artifact.

## Connectivity-first layout selection

Before fixing coordinates, sketch the main connections and compare at least a row and a column arrangement for repeated workloads. Choose the arrangement that makes the important connections short and legible; visual symmetry is secondary to easy tracing.

For a left-to-right flow with one load balancer feeding two backends, consider stacking those backends vertically, with a compact branch in the gap between the balancer and backends. Put management on the opposite side for short direct connections, and place health checks near their own clear routing lane. This is a layout option, not a rule that all compute must be vertical.

Review routes by crossings first, then unnecessary bends, then total length. Prefer direct lines or one short elbow where feasible. Share a clearly visible trunk for one-to-many relationships, with a junction dot where needed; never share a trunk between unrelated protocols. Fan separate traffic types into different attachment points on each icon.

If a line wraps around a tier, passes behind an entire sibling group, or circles a diagram edge just to return to a nearby node, reconsider node order, tier orientation, or panel position. Do not preserve a weak layout and hide its cost with long perimeter connectors. Maintain required cloud scope boundaries and keep connectors out of header/label bands. Crossing a boundary on the way to a contained resource is acceptable; crossing an unrelated resource is not.

## Final connector and document-width review

At actual document width (typically 900–1000 px), inspect the rendered figure rather than judging only full-resolution source. Make operational resource IDs such as app-a/app-b prominent enough to correlate with test results; service category and group metadata can be secondary.

Distinguish crossings from junctions: use a gap or bridge for unavoidable unrelated-line crossings and a junction dot only for a true shared branch. Keep a small clear gap around the crossing so it does not look electrically connected. Avoid markers at intermediate gap endpoints; arrows belong at the destination.

Connect arrows to the visible icon geometry or an explicit resource attachment point, accounting for transparent padding in SVG viewBoxes. Do not leave a conspicuous floating arrow, cover the glyph, or terminate beside an unrelated label. Give protocols separate attachment points when needed.

Trim empty top margins and unused panel space after routing, without crowding headers or breaking scope containment. Re-render after these adjustments and check label clipping, actual arrow tips, crossing clarity and primary-name readability at document width. A preview should show the final saved source.

