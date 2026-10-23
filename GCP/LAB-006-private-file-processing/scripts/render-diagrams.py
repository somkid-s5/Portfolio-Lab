"""Generate private-file topology and recovery diagrams for cloud CI rendering."""
import base64
import hashlib
from io import BytesIO
import json
from pathlib import Path
from urllib.request import urlopen
from zipfile import ZipFile

ROOT=Path(__file__).resolve().parents[1]
URL='https://services.google.com/fh/files/misc/google-cloud-legacy-icons.zip'
def icon(archive,name):
    matches=[p for p in archive.namelist() if p.endswith('/'+name+'/'+name+'.svg') or p==name+'/'+name+'.svg']
    if len(matches)!=1:
        raise ValueError('Expected exactly one official SVG for '+name+': '+repr(matches))
    data=archive.read(matches[0])
    print('LAB006_ICON_SOURCE='+json.dumps({'name':name,'path':matches[0],'sha256':hashlib.sha256(data).hexdigest()}))
    return 'data:image/svg+xml;base64,'+base64.b64encode(data).decode()

def base(title,desc,width,height,body):
    return f'''<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">
<title id="title">{title}</title><desc id="desc">{desc}</desc>
<style>text{{font-family:Arial,sans-serif;fill:#1f2937}} .h{{font-size:20px;font-weight:700}} .n{{font-size:18px;font-weight:700}} .s{{font-size:16px;fill:#526174}} .small{{font-size:15px;fill:#526174}} .arrow{{fill:none;stroke:#2563eb;stroke-width:2;marker-end:url(#tip)}} .ops{{fill:none;stroke:#7c3aed;stroke-width:2;stroke-dasharray:6 4;marker-end:url(#purple)}}</style>
<defs><marker id="tip" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M0 0L10 5L0 10Z" fill="#2563eb"/></marker><marker id="purple" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M0 0L10 5L0 10Z" fill="#7c3aed"/></marker></defs>
<rect width="100%" height="100%" fill="white"/>
{body}
</svg>'''



def main():
    with urlopen(URL, timeout=60) as response:
        data = response.read(30000001)
    if len(data) > 30000000:
        raise ValueError("official_archive_exceeds_bound")
    sources = []
    with ZipFile(BytesIO(data)) as archive:
        def verified(names, label):
            for name in names:
                matches = [p for p in archive.namelist()
                           if p.endswith("/"+name+"/"+name+".svg")
                           or p == name+"/"+name+".svg"]
                if len(matches) == 1:
                    raw = archive.read(matches[0])
                    sources.append({"service": label, "path": matches[0],
                                    "sha256": hashlib.sha256(raw).hexdigest()})
                    return icon(archive, name)
            sources.append({"service": label, "generic": True,
                            "reason": "No unambiguous glyph found in this official archive"})
            return None
        run = verified(["cloud_run"], "Cloud Run")
        storage = verified(["cloud_storage"], "Cloud Storage")
        firestore = verified(["cloud_firestore", "firestore"], "Firestore")
        eventarc = verified(["eventarc"], "Eventarc")
    def glyph(href, x, y, label):
        if href:
            return f'<image x="{x}" y="{y}" width="64" height="64" xlink:href="{href}"/>'
        return (f'<rect x="{x}" y="{y}" width="64" height="64" rx="4" fill="#f1f5f9" stroke="#64748b"/>'
                f'<text x="{x+32}" y="{y+37}" text-anchor="middle" font-size="12">generic</text>')
    def service(href, x, y, title, detail):
        return (glyph(href,x-32,y,title) +
                f'<text x="{x}" y="{y+86}" text-anchor="middle" class="n">{title}</text>'
                f'<text x="{x}" y="{y+110}" text-anchor="middle" class="small">{detail}</text>')
    topology = '''
<text x="24" y="36" font-size="27" font-weight="700">Sales File Desk — upload directly, process asynchronously</text>
<text x="24" y="65" class="s">Design topology • private data buckets • no VPC in this solution</text>
<rect x="178" y="92" width="918" height="692" rx="5" fill="white" stroke="#475569"/>
<text x="198" y="120" class="h">Google Cloud • dedicated lab project</text>
<rect x="198" y="140" width="878" height="620" rx="4" fill="#fafcff" stroke="#94a3b8" stroke-dasharray="7 5"/>
<text x="218" y="168" class="h">asia-southeast1 • regional services and bucket locations</text>
<rect x="218" y="190" width="838" height="200" rx="4" fill="#eff6ff" stroke="#2563eb"/>
<text x="238" y="218" class="h">Control plane • login, ownership and job state</text>
<rect x="218" y="454" width="838" height="256" rx="4" fill="#f5f3ff" stroke="#7c3aed"/>
<text x="238" y="482" class="h">Data plane • immutable input generation → one logical result</text>
<rect x="24" y="248" width="128" height="76" rx="5" fill="#fff7ed" stroke="#c2410c"/>
<text x="88" y="280" text-anchor="middle" class="n">Browser</text>
<text x="88" y="304" text-anchor="middle" class="small">Customer</text>
'''
    topology += service(run,330,240,"Cloud Run portal","lab006-portal • app login")
    topology += service(firestore,640,240,"Firestore","lab006-files • named DB")
    topology += service(storage,330,510,"Incoming bucket","Private • signed POST")
    topology += service(eventarc,540,510,"Eventarc","Finalized event")
    topology += service(run,750,510,"Cloud Run worker","lab006-worker • IAM required")
    topology += service(storage,960,510,"Results bucket","Private • create-only JSON")
    topology += '''
<path class="arrow" d="M152 280H298"/>
<text x="170" y="263" class="small">HTTPS</text>
<path class="arrow" d="M362 272H608"/>
<text x="436" y="256" class="small">Owner / quota / status</text>
<path class="arrow" d="M88 324V542H298"/>
<text x="40" y="422" class="small">Direct CSV</text>
<text x="40" y="444" class="small">signed POST</text>
<path class="arrow" d="M362 542H508"/>
<text x="410" y="524" class="small">Event</text>
<path class="arrow" d="M572 542H718"/>
<text x="616" y="524" class="small">HTTPS</text>
<path class="arrow" d="M782 542H928"/>
<text x="816" y="524" class="small">Write</text>
<path class="ops" d="M750 510V414H640V354"/>
<text x="768" y="416" class="small">Claim / fenced publish</text>
<text x="238" y="676" class="small">Worker reads the pinned incoming generation; event payload contains metadata, not CSV bytes.</text>
<text x="24" y="824" class="s">Blue solid: request / data / event direction. Purple dashed: transactional worker state.</text>
<text x="24" y="852" class="small">Download: portal checks owner, then browser uses a generation-pinned signed GET (≤60s).</text>
<text x="24" y="878" class="small">POST policy ≤300s. Bearer capabilities are secrets; IAM-protected worker is not a private VPC endpoint.</text>
'''
    recovery = '''
<text x="24" y="36" font-size="27" font-weight="700">Recovery — repeat delivery without overwriting the result</text>
<text x="24" y="65" class="s">Worker lifecycle detail • application state, not a second cloud topology</text>
<rect x="24" y="100" width="1016" height="300" rx="5" fill="#eff6ff" stroke="#2563eb"/>
<text x="44" y="132" class="h">One attempt • input generation is fixed on first claim</text>
'''
    steps = [
        (48, "1  Claim", ["Firestore transaction", "120s lease + token", "≤5 attempts / epoch"]),
        (302, "2  Validate", ["Read pinned generation", "Bounded CSV validation", "Deterministic summary"]),
        (556, "3  Store result", ["Create if absent", "Existing? Compare bytes", "Mismatch → fail closed"]),
        (810, "4  Publish", ["Check current lease token", "Bind result generation", "Mark job succeeded"]),
    ]
    for x, title, lines in steps:
        recovery += f'<rect x="{x}" y="160" width="206" height="196" rx="4" fill="white" stroke="#94a3b8"/><text x="{x+14}" y="194" class="h">{title}</text>'
        for i,line in enumerate(lines):
            recovery += f'<text x="{x+14}" y="{234+i*32}" class="small">{line}</text>'
    for x in [254,508,762]:
        recovery += f'<path class="arrow" d="M{x} 258H{x+48}"/>'
    recovery += '''
<rect x="556" y="446" width="460" height="142" rx="4" fill="#fef2f2" stroke="#b91c1c"/>
<text x="576" y="480" class="h">Deliberate output → metadata gap</text>
<text x="576" y="514" class="s">Output exists, status not yet succeeded; return 503.</text>
<text x="576" y="546" class="s">Redelivery reuses verified output, then publishes.</text>
<path class="ops" d="M660 356V446"/>
<rect x="48" y="446" width="460" height="142" rx="4" fill="#f0fdf4" stroke="#15803d"/>
<text x="68" y="480" class="h">Bounded recovery, not exactly-once delivery</text>
<text x="68" y="514" class="s">Transient errors → release / lease recovery.</text>
<text x="68" y="546" class="s">Budget exhausted → inspect, fix, operator retry.</text>
<text x="24" y="632" class="s">Operator: at most 2 additional epochs; same retry request key resolves the same epoch.</text>
<text x="24" y="660" class="small">Stale token cannot publish. Rejected input / integrity mismatch cannot be bypassed with manual retry.</text>
'''
    out=ROOT/"assets"
    out.mkdir(exist_ok=True)
    for name, svg in [
        ("solution",base("Sales File Desk topology",
            "Browser uploads directly to private Storage; Eventarc invokes an IAM-protected worker. Firestore holds ownership and fenced job state. No VPC.",1120,906,topology)),
        ("recovery",base("Sales File Desk recovery",
            "Claim, bounded validation, create-or-verify result, fenced publication; redelivery repairs the output metadata gap.",1064,692,recovery))]:
        (out/(name+".svg")).write_text(svg, encoding="utf-8")
        print("LAB006_SVG_"+name.upper()+"="+json.dumps(svg))
    provenance = {"archive_url":URL, "archive_sha256":hashlib.sha256(data).hexdigest(),
                  "entrypoint":"https://cloud.google.com/icons", "icons":sources,
                  "layout_decision":"Separate control/data rows shorten the direct upload and event chain; recovery is a separate detail.",
                  "verification":"Design only; PNG must be visually reviewed at 960px before publication."}
    (out/"diagram-provenance.json").write_text(json.dumps(provenance,indent=2)+"\n",encoding="utf-8")
    print("LAB006_DIAGRAM_PROVENANCE="+json.dumps(provenance))

if __name__ == "__main__":
    main()
