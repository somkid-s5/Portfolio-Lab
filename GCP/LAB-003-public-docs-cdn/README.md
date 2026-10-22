---
lab: LAB-003
platform: GCP
guide_status: authoring
cloud_verification: not-run
last_verified: null
---
# Lab 03 — เอกสารสาธารณะผ่าน CDN และ HTTPS ที่อัปเดตและย้อนเวอร์ชันได้

ทีม Support ต้องเผยแพร่คู่มือผลิตภัณฑ์ให้ลูกค้าเปิดผ่าน HTTPS ได้ทั่วถึง ปัญหาไม่ได้จบที่อัปโหลด HTML: เมื่อเปลี่ยนเอกสารต้องไม่เห็นหน้าใหม่กับ CSS เก่าปนกัน และถ้าปล่อยเนื้อหาผิดต้องย้อนกลับได้โดยพิสูจน์จาก version/hash ไม่ใช่แค่กด refresh แล้วคิดว่าหาย

## Requirements และขอบเขต Solution

| ID | ความต้องการ | วิธีพิสูจน์ / หลักฐาน |
|---|---|---|
| R1 | เข้าคู่มือผ่าน HTTPS ด้วยชื่อที่ทีมควบคุม | DNS A ตรง frontend IP, managed certificate ACTIVE และ TLS validation ผ่านโดยไม่ใช้ -k; เก็บ hostname/certificate และ HTTP status |
| R2 | เผยแพร่เนื้อหา/asset ครบและอ้างอิงตรง release | หน้า /index.html แสดง release ID; CSS content-hash URL โหลด200 และ SHA256 ตรง manifest; ไม่ทิ้งไฟล์ให้ผู้เรียนคิดเอง |
| R3 | Cache ตามชนิดไฟล์ | index.html public,max-age=60; immutable hashed assets max-age=31536000; ดู metadata/headers และ CDN cache-hit logs หลัง warmup ไม่ใช้ latency อย่างเดียวพิสูจน์ hit |
| R4 | อัปเดตเป็น v2 โดยไม่เสีย asset consistency | อัปโหลด immutable assets ก่อน index, publish index ด้วย generation precondition; ตรวจ release ID/hash หลัง TTL หรือ targeted invalidation |
| R5 | วินิจฉัยและกู้ bad release | ปล่อย bad release ที่ควบคุมไว้ ตรวจอาการจาก HTTP/content/hash แล้ว publish index v1 กลับด้วย generation fence; invalidate เฉพาะ path ที่จำเป็นและตรวจผลใหม่ |
| R6 | สิทธิ์ Public content ชัดและไม่อ้าง origin isolation | เฉพาะ bucket Lab เป็น public read; ไม่มี secret/customer data; anonymous write ต้องไม่สำเร็จ; ตรวจ IAM และ organization Public Access Prevention ก่อนเริ่ม |
| R7 | Change request: HTML กับ asset TTL ต่างกัน | เปรียบเทียบ update ก่อน/หลังเลือก TTL และ fingerprinted URLs; บันทึก stale object behavior และข้อจำกัด browser cache |
| R8 | Cleanup/rebuild ครบ | ลบ frontend/proxy/URL map/backend bucket/cert/reserved IP/objects versions/bucket และ DNS record ของ Lab ตาม dependency; บันทึก commit/config/resources จริง |

## Architecture ที่จะยืนยันก่อนเขียน Tasks

Global external Application LB + Cloud CDN + Cloud Storage backend bucket + public DNS + Google-managed certificate ไม่มี VM/VPC/subnet ในเส้นทางนี้ ไม่ใส่กรอบ network ที่ไม่ได้สร้าง

เลือก **Global external Application Load Balancer รุ่น EXTERNAL_MANAGED** กับ backend bucket ตาม [คู่มือ setup รุ่น global](https://docs.cloud.google.com/load-balancing/docs/https/setup-global-ext-https-buckets) ใช้ HTTP proxy สำหรับ redirect และ HTTPS proxy สำหรับ content ไม่มีการปน EXTERNAL ของ classic ในชุดเดียวกัน

Cloud Storage origin baseline เป็น public-readable สำหรับเอกสารสาธารณะ จึงอาจอ่าน origin URL โดยตรงได้ ไม่อ้างว่าใครต้องผ่าน CDN เสมอ TLS termination ที่ LB ไม่ทำให้ origin private โดยอัตโนมัติ ไม่เปิด signed URL/private bucket complexity มาปะปนกับ baseline

## Domain, IAM และค่าใช้จ่ายที่เป็นเงื่อนไขเริ่ม

- ผู้เรียนต้องมี subdomain ที่ควบคุม DNS ได้จริง ไม่มีการซื้อ domain หรือเปลี่ยน DNS ของงานจริงโดยอัตโนมัติ ไม่มี domain ให้บันทึก BLOCKED ของ HTTPS; HTTP/IP-only test ไม่ถือว่าผ่าน R1
- หากองค์กรบังคับ Public Access Prevention ห้ามปิดนโยบายเพื่อทำ Lab ให้ใช้ sandbox ที่ได้รับอนุญาตหรือทบทวน solution ใหม่
- Bucket เก็บเฉพาะ demo docs ใช้ uniform bucket-level access และ public object viewer ตาม scope ไม่ให้ allUsers มีสิทธิ์เขียน
- ตรวจ Compute/LB, Storage, certificate และ DNS permissions ตามวิธีที่เลือก ไม่ขอ Owner เพื่อแก้ทุก error
- มีต้นทุน LB/static IP/storage/CDN egress/cache fill/requests/logs และ DNS ถ้าสร้าง zone แยก Budget ไม่ใช่ hard cap เปิดเวลาจำกัดแล้ว cleanup
- งานจัดทำคู่มือไม่สร้างทรัพยากร ไม่เปลี่ยน DNS และไม่ Deploy เว็บไซต์ใดจริง ผู้เรียนรันหลังตรวจงบ/สิทธิ์ของตนเอง

## Release materials ที่ต้องมี

สร้างตัวอย่างคู่มือผลิตภัณฑ์อย่างน้อยสอง release พร้อม release ID, immutable CSS/JS, local manifest ระบุ SHA256/size/MIME/cache metadata และ bad-release fixture ที่เปลี่ยนกลับได้ เครื่องมือ build/release ต้องไม่เขียนทับ output เดิมแบบเงียบ ไม่ใส่ timestamps แบบสุ่มจนตรวจ hash ซ้ำไม่ได้

เครื่องมือ publish ต้อง upload assets ก่อน root index, ตรวจ generation fence, ไม่ลบ asset เก่าทันที และไม่ใช้งาน cloud credentials ใน CI baseline มี bounded HTTP probe เก็บ status/headers/content hash โดยไม่อ้าง cache HIT จาก header ที่ origin ใส่เอง

## ขอบเขตหลักฐานและการออกแบบทดสอบ

แยก browser cache, edge cache และ origin metadata ให้ชัด การ invalidate CDN ไม่ล้าง browser cache และการใช้ URL query สุ่มอาจเปลี่ยน cache key จึงห้ามใส่ cache-buster ใน probe ที่ใช้พิสูจน์ cache hit การ warm จาก client เดียวไม่พิสูจน์ hit ทุก PoP

เก็บ request timestamp/URL/release/hash, cache logs ที่สัมพันธ์กับชุดทดสอบ, certificate/DNS และ before/after metadata ไม่แต่ง screenshot หรือค่า latency เปรียบเทียบที่ไม่ได้วัด

## ลำดับหลัง Brief

ยืนยัน stack/certificate/DNS/access model → สร้าง deterministic release materials/test contracts → Diagram ที่ไม่มี VPC ปลอม → คู่มือ Console/CLI พร้อม publish/fault/rollback/cache change → review/render/cleanup evidence

สถานะ Design / Materials: มี deterministic builder, manifest integrity validator, dry-run publisher และ bounded content probe พร้อม tests กำลังตรวจ cloud CI ยังไม่มีคู่มือเต็มหรือผล Deploy จริง

ไฟล์: [releases](content/releases.json), [build](scripts/build-release.py), [publish](scripts/publish-release.py), [probe](scripts/probe-release.py), [tests](tests/test_release.py)

URL map ใช้ [renderer](scripts/render-config.py) แยก content map (HTTPS; / redirect ไป /index.html) ออกจาก HTTP→HTTPS map ไม่ใส่ httpsRedirect บน map ที่ใช้กับ HTTPS proxy Backend bucket logging เปิดให้อัตโนมัติและไม่มีสวิตช์ sample-rate แบบ backend service ตาม [เอกสาร logging](https://docs.cloud.google.com/load-balancing/docs/https/https-logging-monitoring)

Publisher upload asset/archived index ด้วย generation=0 ก่อนเปลี่ยน root index ด้วย expected generation ที่ผู้ทำป้อน การ rollback ใช้ --index-only และ verify remote bytes ของ asset/archive ก่อนเปลี่ยน index ไม่ลบ asset เก่า ไม่ invalidate cache โดยอัตโนมัติ ไม่เรียก cloud ถ้าไม่ใส่ --apply

## แหล่งอ้างอิงขอบเขต

- [Cloud CDN setup overview](https://docs.cloud.google.com/cdn/docs/using-cdn)
- [Backend bucket setup](https://docs.cloud.google.com/load-balancing/docs/https/ext-load-balancer-backend-buckets)
- [Cloud Storage static website](https://docs.cloud.google.com/storage/docs/hosting-static-website)
- [Cloud CDN cache modes](https://docs.cloud.google.com/cdn/docs/caching)
- [Cache invalidation](https://docs.cloud.google.com/cdn/docs/cache-invalidation-overview)

## เตรียมลงมือทำ

| สิ่งที่ต้องเตรียม | รายละเอียด |
|---|---|
| บัญชี | Sandbox project ผูก Billing; มีสิทธิ์ Compute Network/LB Admin, Storage Admin เฉพาะ bucket Lab, Service Usage Admin, Logs Viewer และ DNS editor เฉพาะ record ที่ควบคุม |
| Domain | Subdomain ใหม่ที่ไม่ทับบริการจริง; แก้ public DNS A/AAAA ได้ ผู้ทำต้องมีสิทธิ์จากเจ้าของ domain |
| เวลา/งบ | เผื่อ 3–5 ชั่วโมง รวมรอ DNS/certificate; ค่า LB/static IPv4/CDN/cache fill/egress/storage/requests/logs อาจเกิดแม้ไม่มีผู้ใช้ |
| ข้อมูล | Demo docs เท่านั้น ไม่มี credentials/customer data ทุก object ใน bucket นี้ public read ได้ |
| ขอบเขต | Guide ไม่ซื้อ domain, เปลี่ยนนโยบายองค์กร หรือสร้าง GCP resources ให้โดยอัตโนมัติ คำสั่งด้านล่างผู้เรียนรันหลังยอมรับต้นทุนแล้ว |

### ค่าที่ใช้ตลอด Lab

| ค่า | กำหนด |
|---|---|
| PROJECT_ID | ต้องแทน YOUR_PROJECT_ID |
| HOST | ต้องแทนด้วย subdomain ที่ควบคุมจริง เช่น docs-lab.your-owned-domain.tld ไม่ใส่ https:// |
| BUCKET | lab003-PROJECT_ID-docs; ต้อง unique ทั้งระบบ ถ้าชื่อชนให้เลือกชื่อใหม่ขึ้นต้น lab003- |
| Bucket location/class | asia-southeast1 / STANDARD |
| Backend bucket | lab003-docs-backend |
| Global IP | lab003-lb-ip |
| URL maps | lab003-content-map / lab003-http-redirect |
| Proxies | lab003-https-proxy / lab003-http-proxy |
| Forwarding rules | lab003-https / lab003-http |
| SSL certificate / policy | lab003-cert / lab003-tls |

คำสั่งทั้งหมดรันใน **Cloud Shell** ของ Console เว้นแต่ระบุ Browser/Console ไม่มี VM ที่ต้อง SSH เข้า

## Task 0 — ตรวจ Project, Domain และเตรียม Code

**Console:** เลือก sandbox project, เปิด **Billing → Budgets & alerts** ตั้งวงเงินที่ยอมรับ ตรวจ **IAM & Admin → Quotas & System Limits** ว่ามี global external IP/forwarding rule/target proxy/certificates เพียงพอ ตรวจ organization Public Access Prevention กับผู้ดูแลก่อนสร้าง bucket ถ้าบังคับ public access prevention ให้หยุด baseline ไม่ปิด policy ขององค์กร

**Cloud Shell:** แทน PROJECT_ID และ HOST ด้วยค่าจริงของตนเอง:

```bash
export PROJECT_ID="YOUR_PROJECT_ID"
export HOST="docs-lab.YOUR_OWN_DOMAIN"
export BUCKET="lab003-${PROJECT_ID}-docs"
gcloud config set project "$PROJECT_ID"
gcloud config get-value project
gcloud auth list --filter=status:ACTIVE
gcloud services enable compute.googleapis.com storage.googleapis.com logging.googleapis.com
git clone --branch docs/gcp-solution-labs --single-branch https://github.com/somkid-s5/Portfolio-Lab.git ~/portfolio-lab-003-source
export LAB_DIR="$HOME/portfolio-lab-003-source/GCP/LAB-003-public-docs-cdn"
cd "$LAB_DIR"
git rev-parse HEAD
mkdir -p builds assets/evidence
python3 scripts/render-config.py --project "$PROJECT_ID" --host "$HOST" --out builds/config
```

หาก directory clone มีงานเก่าอยู่ อย่าลบหรือ reset ให้เลือก directory ใหม่และปรับ LAB_DIR Renderer จะปฏิเสธ HOST ที่ยังมี underscore จาก placeholder จึงต้องแทนทั้งค่าเป็น hostname จริงก่อน ไม่ใช้ example.com ที่คุณไม่ได้ควบคุมเพื่อให้คำสั่งดูผ่าน

**Expected:** project ตรง Console, ได้ builds/config/content-map.json และ http-redirect-map.json ไม่มี network call จาก renderer เปิดอ่านไฟล์ดู backend bucket project/ชื่อให้ตรง จด commit และใช้ code รุ่นเดียวตลอด Lab

**บันทึก T00:** Project alias [เติม] / hostname และสิทธิ์ควบคุม DNS [เติม] / commit/Python/gcloud versions [เติม] / IAM/quota/PAP/budget [เติม] / สถานะ PENDING

## Task 1 — Build เอกสารสาม Release แบบตรวจซ้ำได้

**Cloud Shell:**

```bash
cd "$LAB_DIR"
python3 scripts/build-release.py --release v1 --out builds/v1
python3 scripts/build-release.py --release v2 --out builds/v2
python3 scripts/build-release.py --release bad --out builds/bad
python3 -m json.tool builds/v1/manifest.json
python3 -m unittest discover -s tests -v
```

**Expected:** แต่ละ release มี index.html, CSS ชื่อ content hash ภายใต้ releases/RELEASE/assets และ manifest ที่ระบุ size/SHA256/MIME/Cache-Control ไม่มี timestamp สุ่มใน build output v1/v2 เป็นเอกสารดี ส่วน bad เป็น fixture ที่ขาด heading Support guide แต่ไฟล์/hash ถูกต้อง เพื่อฝึกแยก delivery สำเร็จออกจาก business content ผิด

Builder ไม่เขียนทับ output เดิม ถ้ารันซ้ำให้ใช้ directory ใหม่ เช่น builds/v1-check อย่าลบผลเก่าเพื่อกลบปัญหา การรัน tests นี้ใช้ local HTTP fixtures และ fake publisher runner ไม่สร้าง GCP resources หรือพิสูจน์ CDN/TLS

เปิด `python3 -m http.server 8080 --directory builds/v1` แล้วใช้ **Cloud Shell → Web preview → Preview on port 8080** ไป /index.html ตรวจหน้าเว็บ/CSS/Quick start และรายละเอียด Troubleshooting เมื่อจบกด Ctrl+C ที่ terminal ของ server ไม่ kill งานอื่นที่ใช้ port นี้

**บันทึก T01:** Release IDs/hash ใน manifest [เติม] / ภาพหน้า v1 ไม่ใช่ Cloud deployment [แนบ] / ผล tests [เติม] / สถานะ PENDING

## Task 2 — สร้าง Public-read Bucket เฉพาะ Demo

**Cloud Shell:** ตรวจ BUCKET ต้องขึ้นต้น lab003- และอยู่ใน project ทดลอง คำสั่งนี้สร้าง resource ที่คิดค่าใช้จ่าย:

```bash
printf 'Project=%s Bucket=%s Host=%s\n' "$PROJECT_ID" "$BUCKET" "$HOST"
gcloud storage buckets create "gs://$BUCKET" --project="$PROJECT_ID" \
  --location=asia-southeast1 --default-storage-class=STANDARD \
  --uniform-bucket-level-access --soft-delete-duration=0
gcloud storage buckets add-iam-policy-binding "gs://$BUCKET" \
  --member=allUsers --role=roles/storage.objectViewer
gcloud storage buckets describe "gs://$BUCKET"
gcloud storage buckets get-iam-policy "gs://$BUCKET"
```

**เหตุผล/ข้อจำกัด:** ใช้ uniform IAM และ allUsers เฉพาะ objectViewer ไม่ให้ write/admin Soft delete ปิดเฉพาะ bucket demo ใหม่นี้เพื่อไม่เหลือข้อมูลที่ถูกลบคิดค่าเก็บตาม default 7 วัน ใช้ STANDARD ไม่มี minimum retention ตาม storage class แบบ cold ไม่เปิด versioning เพราะ rollback ใช้ immutable archived releases ถ้า policy องค์กรบังคับ retention/soft delete ให้บันทึกเงื่อนไขและต้นทุนตามจริง ห้ามข้ามด้วยการเปลี่ยน policy ของทรัพยากรอื่น

**Console:** เปิด **Cloud Storage → Buckets → bucket นี้ → Permissions** ตรวจ public read เฉพาะ bucket Lab ดู **Protection** ว่า soft delete/versioning/retention ตรงสิ่งที่ตกลง อย่าคัดลอกข้อมูลลับใดเข้า bucket แม้ชั่วคราว

**บันทึก T02:** bucket/location/class [เติม] / IAM viewer-only [เติม] / retention/soft-delete/versioning ที่ตั้งจริง [เติม] / สถานะ PENDING

## Task 3 — Publish v1 โดยยังไม่สร้าง Frontend

**Cloud Shell:** ดู dry-run ก่อน ค่า expected-generation=0 ใช้เฉพาะตอน root index ยังไม่เคยมี:

```bash
cd "$LAB_DIR"
python3 scripts/publish-release.py --release-dir builds/v1 --bucket "$BUCKET" \
  --expected-generation 0
```

**Expected dry-run:** ลำดับ upload CSS → upload immutable releases/v1/index.html → publish root index.html สองคำสั่งแรก generation=0 และ root generation=0 ไม่มีการเรียก gcloud จาก script เมื่อไม่ใส่ --apply

เมื่ออ่านเป้าหมายและยืนยันว่าเป็น bucket demo ใหม่แล้วจึงรัน:

```bash
python3 scripts/publish-release.py --release-dir builds/v1 --bucket "$BUCKET" \
  --expected-generation 0 --apply
gcloud storage objects describe "gs://$BUCKET/index.html"
curl --max-time 10 -i "https://storage.googleapis.com/$BUCKET/index.html"
```

**Expected:** anonymous GET origin=200, HTML มี release v1 และ Support guide, metadata Cache-Control=public,max-age=60 ส่วน CSS เป็น public,max-age=31536000,immutable

หาก root หรือ archived path มีอยู่แล้ว publisher จะหยุด ไม่ใช้ force overwrite การรันซ้ำ release ที่อัปโหลดครบแล้วต้องเลือก --index-only พร้อม generation ของ root ปัจจุบัน และตรวจเหตุผลก่อนทำ ถ้าอัปโหลดค้างเพียงบางไฟล์ให้ตรวจ remote hashes/รายการให้ครบก่อนตัดสินใจ ไม่ลบทั้ง bucket เพื่อหนี precondition failure

**บันทึก T03:** ลำดับ publish [เติม] / root generation [เติม] / origin HTTP/release/hash/headers [เติม] / หลักฐาน dry-run ไม่ใช่ผล apply [แยกให้ชัด] / สถานะ PENDING

## Task 4 — ประกอบ Global HTTPS LB และ HTTP Redirect

**Cloud Shell:** ใช้ global EXTERNAL_MANAGED ตาม design ไม่สร้าง VPC/subnet/firewall:

```bash
gcloud compute addresses create lab003-lb-ip --global --ip-version=IPV4 --network-tier=PREMIUM
export LB_IP="$(gcloud compute addresses describe lab003-lb-ip --global --format='value(address)')"
gcloud compute backend-buckets create lab003-docs-backend \
  --gcs-bucket-name="$BUCKET" --enable-cdn
gcloud compute backend-buckets update lab003-docs-backend --cache-mode=USE_ORIGIN_HEADERS
gcloud compute url-maps import lab003-content-map --global --source=builds/config/content-map.json
gcloud compute url-maps import lab003-http-redirect --global --source=builds/config/http-redirect-map.json
gcloud compute ssl-certificates create lab003-cert --global --domains="$HOST"
gcloud compute ssl-policies create lab003-tls --profile=MODERN --min-tls-version=1.2
gcloud compute target-https-proxies create lab003-https-proxy \
  --url-map=lab003-content-map --ssl-certificates=lab003-cert --ssl-policy=lab003-tls
gcloud compute target-http-proxies create lab003-http-proxy --url-map=lab003-http-redirect
gcloud compute forwarding-rules create lab003-https --global \
  --load-balancing-scheme=EXTERNAL_MANAGED --network-tier=PREMIUM \
  --address=lab003-lb-ip --target-https-proxy=lab003-https-proxy --ports=443
gcloud compute forwarding-rules create lab003-http --global \
  --load-balancing-scheme=EXTERNAL_MANAGED --network-tier=PREMIUM \
  --address=lab003-lb-ip --target-http-proxy=lab003-http-proxy --ports=80
printf 'Set DNS A %s -> %s\n' "$HOST" "$LB_IP"
```

**Console:** เปิด **Network services → Load balancing** ตรวจ forwarding rules/target proxies/URL maps ที่สร้างไว้ Scheme ต้อง EXTERNAL_MANAGED, HTTPS443 ไป content map และ HTTP80 ไป redirect map Backend เป็น bucket ไม่ใช่ backend service ของ VM

Certificate ยังไม่ ACTIVE เป็นเรื่องที่คาดได้ก่อน DNS ชี้ถูก อย่าใช้ curl -k เพื่ออ้างว่า HTTPS ผ่าน และไม่สร้าง self-signed certificate แทน requirement ระหว่างรอ

Backend bucket logging เปิดอัตโนมัติและปิดไม่ได้ด้วย sample-rate flag ของ backend service หากไม่เห็น logs ภายหลังให้ตรวจช่วงเวลา/forwarding rule และ exclusions ไม่เพิ่มคำสั่ง --enable-logging ที่ไม่มีสำหรับ backend bucket

**บันทึก T04:** frontend IP/scheme [เติม] / proxy/maps/backend bucket [เติม] / cert initial state [เติม] / resource inventory [เติม] / สถานะ PENDING
