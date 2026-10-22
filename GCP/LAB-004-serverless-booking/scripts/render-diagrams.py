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
    print('LAB004_ICON_SOURCE='+json.dumps({'name':name,'path':matches[0],'sha256':hashlib.sha256(data).hexdigest()}))
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
        raise ValueError('Official archive exceeds download bound')
    print('LAB004_ICON_ARCHIVE_SHA256='+hashlib.sha256(data).hexdigest())
    with ZipFile(BytesIO(data)) as archive:
        run=icon(archive,'cloud_run')
        sql=icon(archive,'cloud_sql')
    body=f'''
<text x="28" y="36" font-size="28" font-weight="700">Booking: HTTPS to a private PostgreSQL database</text>
<text x="28" y="64" class="s">Request and data path • baseline architecture, not a cloud test result</text>
<rect x="200" y="92" width="928" height="446" rx="6" fill="#fff" stroke="#475569" stroke-width="1.5"/>
<text x="220" y="122" class="h">Google Cloud • lab project resources</text>
<rect x="224" y="150" width="880" height="360" rx="5" fill="#f8fafc" stroke="#94a3b8" stroke-dasharray="7 5"/>
<text x="244" y="180" class="h">Region: asia-southeast1</text>
<rect x="252" y="214" width="252" height="256" rx="5" fill="#eff6ff" stroke="#2563eb"/>
<text x="272" y="244" class="h" fill="#2563eb">Application</text>
<image x="340" y="270" width="76" height="76" xlink:href="{run}"/>
<text x="378" y="376" text-anchor="middle" class="n">Cloud Run</text>
<text x="378" y="402" text-anchor="middle" class="s">lab004-booking</text>
<text x="378" y="432" text-anchor="middle" class="small">App session / CSRF / ownership</text>
<text x="378" y="454" text-anchor="middle" class="small">pool 4 • concurrency 8 → 16</text>
<rect x="548" y="214" width="252" height="256" rx="5" fill="#f0fdfa" stroke="#0f766e"/>
<text x="568" y="244" class="h">VPC: lab004-vpc</text>
<rect x="568" y="276" width="212" height="154" rx="4" fill="#fff" stroke="#0f766e" stroke-dasharray="5 4"/>
<text x="584" y="302" class="s">Regional subnet</text>
<text x="584" y="324" class="small">10.44.0.0/24</text>
<rect x="588" y="348" width="172" height="48" rx="4" fill="#ccfbf1" stroke="#0f766e"/>
<text x="674" y="378" text-anchor="middle" class="s">Direct VPC egress</text>
<text x="674" y="454" text-anchor="middle" class="small">private-ranges-only</text>
<rect x="856" y="214" width="224" height="256" rx="5" fill="#f5f3ff" stroke="#7c3aed"/>
<text x="872" y="244" class="h">Managed data service</text>
<image x="930" y="336" width="76" height="76" xlink:href="{sql}"/>
<text x="968" y="436" text-anchor="middle" class="n">Cloud SQL • lab004-sql</text>
<text x="968" y="460" text-anchor="middle" class="s">PostgreSQL 16 • ZONAL</text>
<text x="968" y="286" text-anchor="middle" class="small">Private IP only • TLS connector</text>
<text x="968" y="310" text-anchor="middle" class="small">Google-managed producer network</text>
<rect x="28" y="268" width="108" height="76" rx="5" fill="#fff7ed" stroke="#c2410c"/>
<rect x="42" y="282" width="80" height="44" rx="3" fill="#fff" stroke="#475569"/>
<path d="M42 292H122" stroke="#475569"/>
<text x="82" y="372" text-anchor="middle" class="n">Browser</text>
<text x="82" y="398" text-anchor="middle" class="small">HTTPS • run.app</text>
<path class="arrow" d="M136 310H340"/>

<path class="arrow" d="M416 310H526V372H588"/>
<path class="arrow" d="M760 372H930"/>
<rect x="802" y="337" width="112" height="24" fill="white"/><text x="858" y="354" text-anchor="middle" class="small">PSA route</text>
<text x="244" y="494" class="small">Cloud Run is regional managed compute, not a VM inside the subnet.</text>
<text x="28" y="574" class="s">PSA allocation: 10.84.0.0/16 • service-producer address space, not another workload subnet.</text>
<text x="28" y="600" class="s">Runtime SA reads pinned auth/DB secret versions; bootstrap uses a separate admin identity.</text>
<text x="28" y="626" class="small">Icons: Google Cloud official legacy library • Browser and interface boxes are labeled generic symbols.</text>
'''
    solution=base('Lab004 private booking architecture','Browser HTTPS to Cloud Run; Direct VPC egress through consumer VPC and PSA to Cloud SQL private IP. SQL producer network is not the workload subnet.',1152,650,body)
    flow='''
<text x="28" y="38" font-size="28" font-weight="700">Credential rotation: prepare, verify, switch, retire</text>
<text x="28" y="68" class="s">Two DB logins • same schema/data • old revisions remain usable only while their credentials are valid</text>
<rect x="32" y="112" width="312" height="152" rx="5" fill="#eff6ff" stroke="#2563eb"/>
<text x="52" y="144" class="h">1  Serve A + stage B</text><text x="52" y="176" class="s">Revision A uses login A</text><text x="52" y="204" class="s">Equal grants; distinct passwords</text><text x="52" y="232" class="s">Pin Secret versions per revision</text>
<rect x="420" y="112" width="312" height="152" rx="5" fill="#f5f3ff" stroke="#7c3aed"/>
<text x="440" y="144" class="h">2  Verify B candidate</text><text x="440" y="176" class="s">No main traffic; tag URL only</text><text x="440" y="204" class="s">Journey + old booking references</text><text x="440" y="232" class="s">DB invariants and connection budget</text>
<path class="arrow" d="M344 188H420"/>
<rect x="808" y="112" width="312" height="152" rx="5" fill="#f0fdfa" stroke="#0f766e"/>
<text x="828" y="144" class="h">3  Promote B / drain A</text><text x="828" y="176" class="s">Main traffic → valid revision B</text><text x="828" y="204" class="s">Remove A tags/revisions/jobs</text><text x="828" y="232" class="s">Wait for A connections = 0</text>
<path class="arrow" d="M732 188H808"/>
<rect x="808" y="340" width="312" height="160" rx="5" fill="#fff7ed" stroke="#c2410c"/>
<text x="828" y="374" class="h">4  Retire A; verify again</text><text x="828" y="408" class="s">Guarded ALTER ROLE A NOLOGIN</text><text x="828" y="436" class="s">Disable A Secret version</text><text x="828" y="464" class="s">B journey + invariants still valid</text>
<path class="arrow" d="M964 264V340"/>
<rect x="32" y="340" width="700" height="160" rx="5" fill="#fef2f2" stroke="#b91c1c"/>
<text x="52" y="374" class="h">Rollback boundary changes after retirement</text>
<text x="52" y="410" class="s">Before: traffic may return to A after checking its health.</text>
<text x="52" y="440" class="s">After: deploy previous compatible code with valid B credentials.</text>
<text x="52" y="472" class="s">NOLOGIN does not terminate existing sessions. Never assume it does.</text>
<path class="ops" d="M808 420H732"/>
<text x="28" y="548" class="small">Process diagram; no PASS, timing, performance or cloud execution claims are encoded.</text>
'''
    rotation=base('Booking credential rotation boundary','Four steps with explicit retirement and rollback boundary; A sessions must be drained before NOLOGIN.',1152,574,flow)
    output=ROOT/'assets'
    output.mkdir(exist_ok=True)
    for name,svg in [('solution',solution),('credential-rotation',rotation)]:
        (output/(name+'.svg')).write_text(svg)
        print('LAB004_SVG_'+name.upper().replace('-','_')+'='+json.dumps(svg))
if __name__=='__main__':
    main()
