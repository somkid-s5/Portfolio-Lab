"""Generate Lab 07 architecture and event-flow diagrams from official Google Cloud icons."""
import base64
import hashlib
from html import escape
import json
from pathlib import Path
from urllib.request import urlopen
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
URL = "https://services.google.com/fh/files/misc/google-cloud-legacy-icons.zip"
EXPECTED_ARCHIVE_SHA256 = "a6d9d7921758042538b462f03cf64614c2cebd96743b3ed63580a769fc7de3e9"


def load_icon(archive, name, sources):
    matches = [
        path for path in archive.namelist()
        if path.endswith("/" + name + "/" + name + ".svg")
        or path == name + "/" + name + ".svg"
    ]
    if len(matches) != 1:
        raise ValueError("official_icon_not_unique:" + name)
    path = matches[0]
    data = archive.read(path)
    sources.append({
        "service": name.replace("_", " ").title(),
        "path": path,
        "sha256": hashlib.sha256(data).hexdigest(),
    })
    return "data:image/svg+xml;base64," + base64.b64encode(data).decode("ascii")


def text(x, y, value, cls="small", anchor=None):
    align = f' text-anchor="{anchor}"' if anchor else ""
    return f'<text x="{x}" y="{y}" class="{cls}"{align}>{escape(str(value))}</text>'


def service(href, x, y, name, resource, detail=""):
    cx = x + 34
    result = (
        f'<image x="{x}" y="{y}" width="68" height="68" '
        f'preserveAspectRatio="xMidYMid meet" xlink:href="{href}"/>'
        + text(cx, y + 84, name, "node", "middle")
        + text(cx, y + 105, resource, "resource", "middle")
    )
    if detail:
        result += text(cx, y + 125, detail, "small", "middle")
    return result


def actor(x, y, title, detail):
    return (
        f'<rect x="{x}" y="{y}" width="92" height="70" rx="5" '
        'fill="#fff7ed" stroke="#c2410c" stroke-width="1.5"/>'
        + text(x + 46, y + 29, title, "node", "middle")
        + text(x + 46, y + 51, detail, "small", "middle")
    )


def base(title, description, width, height, body):
    return f'''<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">
<title id="title">{escape(title)}</title><desc id="desc">{escape(description)}</desc>
<style>
text{{font-family:Arial,sans-serif;fill:#1f2937}}
.title{{font-size:27px;font-weight:700}}
.subtitle{{font-size:16px;fill:#526174}}
.frame-title{{font-size:19px;font-weight:700}}
.node{{font-size:16px;font-weight:700}}
.resource{{font-size:13px;font-family:monospace;fill:#334155}}
.small{{font-size:14px;fill:#526174}}
.flow-blue{{fill:none;stroke:#2563eb;stroke-width:2.5;marker-end:url(#arrow-blue)}}
.flow-purple{{fill:none;stroke:#7c3aed;stroke-width:2.5;marker-end:url(#arrow-purple)}}
.flow-teal{{fill:none;stroke:#0f766e;stroke-width:2.5;marker-end:url(#arrow-teal)}}
.flow-dashed{{fill:none;stroke:#475569;stroke-width:2;stroke-dasharray:6 5;marker-end:url(#arrow-gray)}}
.card-title{{font-size:17px;font-weight:700}}
.card-line{{font-size:14px;fill:#334155}}
</style>
<defs>
 <marker id="arrow-blue" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M0 0L10 5L0 10Z" fill="#2563eb"/></marker>
 <marker id="arrow-purple" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M0 0L10 5L0 10Z" fill="#7c3aed"/></marker>
 <marker id="arrow-teal" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M0 0L10 5L0 10Z" fill="#0f766e"/></marker>
 <marker id="arrow-gray" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M0 0L10 5L0 10Z" fill="#475569"/></marker>
</defs>
<rect width="100%" height="100%" fill="#ffffff"/>
{body}
</svg>'''


def solution_diagram(icons):
    body = '''
<text x="28" y="42" class="title">Order Queue Desk — architecture</text>
<text x="28" y="70" class="subtitle">Lab 07 • asynchronous order processing with business-level idempotency</text>
<rect x="110" y="100" width="1100" height="850" rx="5" fill="#ffffff" stroke="#1f2937" stroke-width="1.8"/>
<rect x="110" y="100" width="34" height="38" fill="#1f2937"/>
<text x="127" y="125" fill="#ffffff" class="small" text-anchor="middle" style="fill:#ffffff;font-weight:700">GCP</text>
<text x="158" y="128" class="frame-title">Dedicated Lab project • no public Cloud SQL IP</text>
<rect x="140" y="150" width="1040" height="170" rx="4" fill="#f8fafc" stroke="#64748b"/>
<text x="160" y="178" class="frame-title">Global services / project resources</text>
<rect x="140" y="340" width="1040" height="570" rx="4" fill="#fbfdff" stroke="#2563eb" stroke-width="1.5" stroke-dasharray="7 5"/>
<text x="160" y="370" class="frame-title">asia-southeast1 • regional services and customer network</text>
<rect x="165" y="400" width="500" height="320" rx="5" fill="#eff6ff" stroke="#2563eb" stroke-width="1.5"/>
<text x="185" y="428" class="frame-title">Cloud Run • app and bootstrap</text>
<rect x="690" y="420" width="210" height="280" rx="5" fill="#f0fdfa" stroke="#0f766e" stroke-width="1.5"/>
<text x="795" y="452" class="frame-title" text-anchor="middle">Customer VPC</text>
<text x="795" y="480" class="resource" text-anchor="middle">lab007-vpc</text>
<line x1="712" y1="495" x2="878" y2="495" stroke="#99f6e4"/>
<text x="795" y="528" class="small" text-anchor="middle">Direct VPC Egress</text>
<text x="795" y="555" class="small" text-anchor="middle">PRIVATE_RANGES_ONLY</text>
<text x="795" y="595" class="small" text-anchor="middle">Subnet lab007-run</text>
<text x="795" y="619" class="resource" text-anchor="middle">10.77.10.0/26</text>
<text x="795" y="663" class="small" text-anchor="middle">Private Services Access</text>
<rect x="920" y="420" width="235" height="280" rx="5" fill="#f5f3ff" stroke="#7c3aed" stroke-width="1.5"/>
<text x="1037" y="452" class="frame-title" text-anchor="middle">Managed database</text>
<text x="1037" y="678" class="small" text-anchor="middle">Private IP • PostgreSQL 16</text>
'''
    body += service(icons["secret_manager"], 240, 190, "Secret Manager", "5 secrets • global API", "single replica in asia-southeast1")
    body += service(icons["pubsub"], 600, 190, "Pub/Sub source", "dispatcher publish", "authenticated Worker push")
    body += service(icons["pubsub"], 900, 190, "Pub/Sub dead letter", "orders-dead", "poison • operator pull")
    body += service(icons["cloud_run"], 205, 440, "Portal", "lab007-portal", "public • login")
    body += service(icons["cloud_run"], 355, 440, "Dispatcher", "lab007-dispatcher", "IAM • bounded")
    body += service(icons["cloud_run"], 505, 440, "Worker", "lab007-worker", "IAM • push")
    body += service(icons["cloud_run"], 205, 585, "Bootstrap Job", "lab007-bootstrap", "one-off • private")
    body += service(icons["cloud_sql"], 1005, 480, "Cloud SQL for PostgreSQL", "lab007-orders", "PSA private IP • no public IP")
    body += service(icons["artifact_registry"], 190, 770, "Artifact Registry", "lab007-images", "regional • image@sha256")
    body += service(icons["cloud_scheduler"], 430, 770, "Cloud Scheduler", "lab007-outbox", "OIDC • dispatcher trigger")
    body += actor(10, 470, "Customer", "Browser")
    body += '''
<path class="flow-blue" d="M102 505H155V474H205"/>
<text x="126" y="492" class="small">HTTPS</text>
<path class="flow-teal" d="M665 570H690"/>
<path class="flow-teal" d="M900 570H920"/>
<text x="160" y="925" class="small">Blue: customer HTTPS • Teal: private SQL path through Direct VPC Egress and PSA. The companion flow diagram shows queue and Scheduler directions.</text>
<text x="160" y="945" class="small">Secret versions are numeric and image references use digests; Secret Manager is a global endpoint with one Asia replica, not a regional access boundary.</text>
'''
    return base(
        "Lab 07 Order Queue Desk architecture",
        "GCP project, global services, regional Cloud Run workloads, Direct VPC Egress, private Cloud SQL over PSA, Pub/Sub and operational resources.",
        1320, 980, body,
    )


def event_flow_diagram():
    body = '''
<text x="32" y="42" class="title">Order Queue Desk — delivery, retry and recovery</text>
<text x="32" y="70" class="subtitle">The HTTP response, queue delivery and business outcome are separate checkpoints</text>
'''
    cards = [
        (40, "1  Submit", ["POST /api/orders", "owner-scoped key", "202 = accepted", "not yet confirmed"], "#fff7ed", "#c2410c"),
        (250, "2  Persist", ["PostgreSQL transaction:", "order + items + outbox", "one canonical event ID"], "#eff6ff", "#2563eb"),
        (460, "3  Dispatch", ["Scheduler OIDC trigger", "bounded claim / lease", "publish outside SQL tx", "unknown → retry same ID"], "#f1f5f9", "#475569"),
        (670, "4  Queue", ["Pub/Sub at-least-once", "OIDC push to Worker", "duplicate delivery expected"], "#f5f3ff", "#7c3aed"),
        (880, "5  Process", ["validate event + owner", "SQL transaction:", "dedupe + reserve all/none", "record business result"], "#f0fdfa", "#0f766e"),
        (1090, "6  Acknowledge", ["commit before HTTP 2xx", "redelivery reads ledger", "no second reservation"], "#f0fdf4", "#15803d"),
    ]
    for x, title, lines, fill, stroke in cards:
        body += f'<rect x="{x}" y="150" width="190" height="240" rx="5" fill="{fill}" stroke="{stroke}" stroke-width="1.5"/>'
        body += text(x + 14, 184, title, "card-title")
        for i, line in enumerate(lines):
            body += text(x + 14, 220 + i * 31, line, "card-line")
    for x in [230, 440, 650, 860, 1070]:
        body += f'<path class="flow-blue" d="M{x} 270H{x + 20}"/>'
    body += '''
<rect x="40" y="435" width="610" height="155" rx="5" fill="#faf5ff" stroke="#7c3aed" stroke-width="1.5"/>
<text x="62" y="472" class="card-title">Unknown publish outcome</text>
<text x="62" y="510" class="card-line">A timeout does not prove Pub/Sub rejected the event.</text>
<text x="62" y="540" class="card-line">Keep the same outbox/event ID; resolve or retry safely.</text>
<rect x="670" y="435" width="610" height="155" rx="5" fill="#f0fdf4" stroke="#15803d" stroke-width="1.5"/>
<text x="692" y="472" class="card-title">Worker commit succeeded, HTTP reply was lost</text>
<text x="692" y="510" class="card-line">Redelivery checks processed_events / reservation ledger.</text>
<text x="692" y="540" class="card-line">Return the saved result; do not reserve stock twice.</text>
<rect x="40" y="630" width="1240" height="220" rx="5" fill="#fef2f2" stroke="#b91c1c" stroke-width="1.5"/>
<text x="62" y="668" class="card-title">Poison event and operator redrive</text>
<rect x="72" y="700" width="250" height="90" rx="4" fill="#ffffff" stroke="#b91c1c"/>
<text x="197" y="735" class="node" text-anchor="middle">Source subscription</text>
<text x="197" y="762" class="small" text-anchor="middle">max attempts ≈ 10</text>
<rect x="470" y="700" width="250" height="90" rx="4" fill="#ffffff" stroke="#b91c1c"/>
<text x="595" y="735" class="node" text-anchor="middle">Dead-letter topic</text>
<text x="595" y="762" class="small" text-anchor="middle">inspect original envelope</text>
<rect x="870" y="700" width="360" height="90" rx="4" fill="#ffffff" stroke="#475569"/>
<text x="1050" y="735" class="node" text-anchor="middle">Operator audit → canonical replay</text>
<text x="1050" y="762" class="small" text-anchor="middle">ack only after terminal audit is recorded</text>
<path class="flow-purple" d="M322 745H470"/>
<path class="flow-blue" d="M720 745H870"/>
<text x="62" y="824" class="small">Pub/Sub delivery attempts are approximate; the threshold is not a precise timer or hard business counter.</text>
'''
    return base(
        "Lab 07 delivery, retry and recovery",
        "Transactional order and outbox, bounded dispatcher, at-least-once Pub/Sub delivery, transaction-before-ack and audited poison-event redrive.",
        1320, 900, body,
    )


def main():
    with urlopen(URL, timeout=60) as response:
        archive_bytes = response.read(30_000_001)
    if len(archive_bytes) > 30_000_000:
        raise ValueError("official_archive_exceeds_bound")
    archive_hash = hashlib.sha256(archive_bytes).hexdigest()
    print("LAB007_ICON_ARCHIVE_SHA256=" + archive_hash)
    if archive_hash != EXPECTED_ARCHIVE_SHA256:
        raise ValueError("official_archive_checksum_mismatch:" + archive_hash)

    sources = []
    with ZipFile(__import__("io").BytesIO(archive_bytes)) as archive:
        names = ["cloud_run", "cloud_sql", "pubsub", "secret_manager", "cloud_scheduler", "artifact_registry"]
        icons = {name: load_icon(archive, name, sources) for name in names}

    outputs = {
        "solution": solution_diagram(icons),
        "event-flow": event_flow_diagram(),
    }
    ASSETS.mkdir(parents=True, exist_ok=True)
    for name, svg in outputs.items():
        path = ASSETS / (name + ".svg")
        path.write_text(svg, encoding="utf-8")
        print("LAB007_SVG_" + name.upper().replace("-", "_") + "="
              + base64.b64encode(svg.encode("utf-8")).decode("ascii"))

    provenance = {
        "archive_url": URL,
        "archive_sha256": archive_hash,
        "entrypoint": "https://cloud.google.com/icons",
        "icons": sources,
        "style_attribution": {
            "upstream": "https://github.com/cathrynlavery/diagram-design",
            "license": "MIT",
            "note": "Diagram Design conventions adapted; official Google Cloud glyphs keep original geometry and colors."
        },
        "layout_decision": "Role-specific Cloud Run services remain individually identifiable; Scheduler, queue, and private database links use direct, non-perimeter routes; global services stay outside the regional boundary; Cloud SQL remains outside the customer VPC behind PSA.",
        "verification": "Architecture and event-flow diagrams are design artifacts only; no GCP deployment or Cloud verification is implied."
    }
    provenance_path = ASSETS / "diagram-provenance.json"
    provenance_path.write_text(json.dumps(provenance, indent=2) + "\n", encoding="utf-8")
    print("LAB007_DIAGRAM_PROVENANCE=" + json.dumps(provenance, sort_keys=True))


if __name__ == "__main__":
    main()
