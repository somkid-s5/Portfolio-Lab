"""Build offline SVGs using verified official legacy Cloud Run/Cloud SQL glyphs."""
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
    print('LAB005_ICON_SOURCE='+json.dumps({'name':name,'path':matches[0],'sha256':hashlib.sha256(data).hexdigest()}))
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
    with urlopen(URL,timeout=60) as response:
        data=response.read(30000001)
    if len(data)>30000000:
        raise ValueError('Official archive exceeds bound')
    provenance={'archive_url':URL,'archive_sha256':hashlib.sha256(data).hexdigest(),
                'entrypoint':'https://cloud.google.com/icons',
                'note':'Official legacy Google Cloud service glyphs; generic browser and support annotations are labeled.'}
    with ZipFile(BytesIO(data)) as archive:
        vm=icon(archive,'compute_engine')
        lb=icon(archive,'cloud_load_balancing')
        sql=icon(archive,'cloud_sql')
    def image(href,x,y):
        return f'<image x="{x}" y="{y}" width="72" height="72" xlink:href="{href}"/>'
    body=f'''
<text x="24" y="36" font-size="28" font-weight="700">Orders: private three-tier service across two zones</text>
<text x="24" y="66" class="s">Baseline topology • architecture only, not a GCP verification result</text>
<rect x="160" y="92" width="1096" height="810" rx="6" fill="white" stroke="#475569" stroke-width="1.5"/>
<text x="180" y="122" class="h">Google Cloud • dedicated lab project</text>
<rect x="364" y="144" width="872" height="596" rx="5" fill="#f8fafc" stroke="#94a3b8" stroke-dasharray="7 5"/>
<text x="384" y="174" class="h">Region: asia-southeast1</text>
<rect x="384" y="196" width="584" height="508" rx="5" fill="#f0fdfa" stroke="#0f766e"/>
<text x="404" y="224" class="h">VPC: lab005-vpc</text>
<rect x="404" y="244" width="188" height="420" rx="4" fill="#eff6ff" stroke="#2563eb"/>
<text x="420" y="272" class="n">Web subnet</text><text x="420" y="294" class="small">10.55.10.0/24 • regional</text>
<rect x="616" y="244" width="328" height="420" rx="4" fill="#eff6ff" stroke="#2563eb"/>
<text x="632" y="272" class="n">API subnet</text><text x="632" y="294" class="small">10.55.20.0/24 • regional</text>
{image(vm,460,316)}{image(vm,460,500)}
<text x="496" y="412" text-anchor="middle" class="n">Web VM • zone a</text>
<text x="496" y="436" text-anchor="middle" class="small">Nginx • web SA</text>
<text x="496" y="596" text-anchor="middle" class="n">Web VM • zone b</text>
<text x="496" y="620" text-anchor="middle" class="small">MIG baseline: 2</text>
{image(vm,832,316)}{image(vm,832,500)}
<text x="868" y="412" text-anchor="middle" class="n">API VM • zone a</text>
<text x="868" y="436" text-anchor="middle" class="small">Gunicorn • API SA</text>
<text x="868" y="596" text-anchor="middle" class="n">API VM • zone b</text>
<text x="868" y="620" text-anchor="middle" class="small">MIG: 2 → change 4</text>
{image(lb,640,408)}
<text x="676" y="504" text-anchor="middle" class="n">Internal LB</text>
<text x="676" y="526" text-anchor="middle" class="small">10.55.20.10:8080</text>
<text x="676" y="548" text-anchor="middle" class="small">TCP passthrough</text>
<rect x="996" y="244" width="216" height="420" rx="4" fill="#f5f3ff" stroke="#7c3aed"/>
<text x="1104" y="272" text-anchor="middle" class="n">Managed producer</text>
<text x="1104" y="294" text-anchor="middle" class="small">PSA 10.85.0.0/16</text>
{image(sql,1068,408)}
<text x="1104" y="504" text-anchor="middle" class="n">Cloud SQL</text>
<text x="1104" y="528" text-anchor="middle" class="small">PostgreSQL 16</text>
<text x="1104" y="552" text-anchor="middle" class="small">Enterprise • REGIONAL HA</text>
<text x="1104" y="592" text-anchor="middle" class="small">Primary + standby</text>
<text x="1104" y="614" text-anchor="middle" class="small">zone a / zone b</text>
<text x="1104" y="640" text-anchor="middle" class="small">One private DB endpoint</text>
{image(lb,232,408)}
<text x="268" y="504" text-anchor="middle" class="n">HTTPS LB</text>
<text x="268" y="528" text-anchor="middle" class="small">Global external</text>
<text x="268" y="550" text-anchor="middle" class="small">EXTERNAL_MANAGED</text>
<text x="268" y="574" text-anchor="middle" class="small">DNS + managed TLS</text>
<rect x="24" y="412" width="104" height="64" rx="4" fill="#fff7ed" stroke="#c2410c"/>
<rect x="38" y="426" width="76" height="34" fill="white" stroke="#475569"/>
<path d="M38 434H114" stroke="#475569"/>
<text x="76" y="504" text-anchor="middle" class="n">Browser</text>
<path class="arrow" d="M128 444H232"/>
<text x="180" y="426" text-anchor="middle" class="small">443</text>
<path d="M304 444H348V352H460 M348 444V536H460" fill="none" stroke="#2563eb" stroke-width="2" marker-end="url(#tip)"/>
<circle cx="348" cy="444" r="3" fill="#2563eb"/>
<text x="348" y="326" text-anchor="middle" class="small">HTTP 80</text>
<path d="M532 352H604V444H640 M532 536H604V444" fill="none" stroke="#2563eb" stroke-width="2"/>
<path class="arrow" d="M604 444H640"/>
<circle cx="604" cy="444" r="3" fill="#2563eb"/>
<path d="M712 444H784V352H832 M784 444V536H832" fill="none" stroke="#2563eb" stroke-width="2" marker-end="url(#tip)"/>
<circle cx="784" cy="444" r="3" fill="#2563eb"/>
<text x="782" y="326" text-anchor="middle" class="small">TCP 8080</text>
<path d="M904 352H984V444 M904 536H984V444" fill="none" stroke="#7c3aed" stroke-width="2"/>
<path class="ops" d="M984 444H1068"/>
<circle cx="984" cy="444" r="3" fill="#7c3aed"/>
<text x="1104" y="344" text-anchor="middle" class="small">Private TLS</text>
<text x="1104" y="368" text-anchor="middle" class="small">connector 3307</text>
<text x="404" y="688" class="small">Regional subnets span both zones • no public VM IPs • no default allow-internal</text>
<text x="384" y="730" class="small">SQL is outside workload subnets; PSA is producer address space, not a third VM subnet.</text>
<rect x="184" y="764" width="1048" height="112" rx="4" fill="#f1f5f9" stroke="#94a3b8"/>
<text x="204" y="792" class="n">Supporting paths and controls (not additional application tiers)</text>
<text x="204" y="820" class="s">NAT / Router: private outbound • IAP / OS Login: administration • HTTPS 443: Google APIs</text>
<text x="204" y="846" class="s">Private GCS releases + SHA256 • numeric Secret versions • separate one-time bootstrap identity</text>
<text x="24" y="932" class="s">Web → API uses private HTTP + SA firewall + App auth, not mTLS. SQL connector uses TLS.</text>
<text x="24" y="960" class="small">Official Google Cloud legacy icons; Browser/support panel are generic. Resource names map to the guide.</text>
'''
    solution=base('Lab005 Orders private three-tier topology',
      'Browser HTTPS global load balancer to two vertically stacked Web VMs, internal TCP load balancer and two API VMs; private connector to Cloud SQL regional HA in producer network.',1280,984,body)
    flow=f'''
<text x="24" y="36" font-size="28" font-weight="700">Release and recovery: separate code, credentials and data</text>
<text x="24" y="66" class="s">Operational design • no cloud PASS or recovery-time guarantee</text>
<rect x="32" y="116" width="264" height="218" rx="4" fill="#fff7ed" stroke="#c2410c"/>
<text x="52" y="148" class="h">1  Prepare</text>
<text x="52" y="184" class="s">Pinned commit + Web/API hashes</text>
<text x="52" y="214" class="s">Private versioned GCS</text>
<text x="52" y="244" class="s">Numeric auth / DB secrets</text>
<text x="52" y="274" class="s">Bootstrap SA ≠ API SA</text>
<text x="52" y="306" class="small">No secret payload in state/metadata</text>
<rect x="372" y="116" width="264" height="218" rx="4" fill="#f5f3ff" stroke="#7c3aed"/>
<text x="392" y="148" class="h">2  Initialize once</text>
{image(sql,468,166)}
<text x="504" y="268" text-anchor="middle" class="s">Atomic schema / seed / grants</text>
<text x="504" y="298" text-anchor="middle" class="small">Refuse password reset on rerun</text>
<rect x="712" y="116" width="264" height="218" rx="4" fill="#eff6ff" stroke="#2563eb"/>
<text x="732" y="148" class="h">3  Serve / roll API</text>
{image(vm,808,166)}
<text x="844" y="268" text-anchor="middle" class="s">Two-zone MIG; surge 2</text>
<text x="844" y="298" text-anchor="middle" class="small">Unavailable 0; ready 30s</text>
<path class="arrow" d="M296 224H372"/><path class="arrow" d="M636 224H712"/>
<rect x="712" y="414" width="264" height="196" rx="4" fill="#fef2f2" stroke="#b91c1c"/>
<text x="732" y="448" class="h">4  Observe / back out</text>
<text x="732" y="486" class="s">Bad-startup flag → false</text>
<text x="732" y="516" class="s">Prior compatible API hash</text>
<text x="732" y="546" class="s">Keep DB data / valid secrets</text>
<text x="732" y="580" class="small">Keep maxUnavailable = 0</text>
<path class="arrow" d="M844 334V414"/>
<rect x="32" y="414" width="604" height="196" rx="4" fill="#f0fdfa" stroke="#0f766e"/>
<text x="52" y="448" class="h">5  Verify recovery, not only operation completion</text>
<text x="52" y="486" class="s">Same journal/key → resolve order → read-only ledger snapshot</text>
<text x="52" y="516" class="s">App fault: one Web or API VM at a time; record survivor IDs</text>
<text x="52" y="546" class="s">SQL failover: same private endpoint; reconnect; no mass repair</text>
<text x="52" y="580" class="small">API /livez is process-only; /healthz queries DB; public /livez is Web health</text>
<path class="ops" d="M712 510H636"/>
<text x="24" y="656" class="s">Capacity change: API 2 → 4; pool 4 each; rollout peak plan 6 × 4 = 24 + headroom.</text>
<text x="24" y="684" class="small">Rebuild from seed is not data restore. Capture evidence before cleanup; check retained storage/backups.</text>
'''
    operations=base('Lab005 release and recovery boundaries','Prepare immutable artifacts and secrets, bootstrap once, roll API MIG, back out code without deleting data, verify journals and ledger.',1008,712,flow)
    out=ROOT/'assets'
    out.mkdir(exist_ok=True)
    for name,svg in [('solution',solution),('operations',operations)]:
        (out/(name+'.svg')).write_text(svg)
        print('LAB005_SVG_'+name.upper()+'='+json.dumps(svg))
    (out/'diagram-provenance.json').write_text(json.dumps(provenance,indent=2)+'\n')
    print('LAB005_DIAGRAM_PROVENANCE='+json.dumps(provenance))
if __name__=='__main__':
    main()
