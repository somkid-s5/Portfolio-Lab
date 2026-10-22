---
lab: LAB-005
platform: GCP
guide_status: design
cloud_verification: not-run
last_verified: null
---
# Lab 05 — ระบบสั่งซื้อสามชั้นบน VM ที่รับมือ App failure และ Database failover ได้

ทีมขายมีเว็บสั่งซื้อที่ต้องแยก Web, API และฐานข้อมูลออกจากกัน ต้องปล่อย App รุ่นใหม่โดยไม่หยุดทุกเครื่องพร้อมกัน และต้องรู้ว่าระหว่างฐานข้อมูลสลับ primary คำสั่งซื้อใดสำเร็จ คำสั่งใดควร retry โดยไม่ตัดสต็อกซ้ำ

## ผู้ใช้และเส้นทางธุรกิจ

ลูกค้าสองบัญชีและ operator ใช้ข้อมูลสังเคราะห์ ผู้ใช้ login → ดูสินค้า/สต็อก → ส่งคำสั่งซื้อ → ดูรายการของตน → ยกเลิกและคืนสต็อกหนึ่งครั้ง Operator ดูรายการรวมเพื่อเทียบกับ ledger แต่ไม่ใช้สิทธิ์ Cloud IAM มาแทน App role

ชุด App ต้องมี UI ที่ใช้งานได้, PostgreSQL schema/seed, health endpoints, structured logs และ bounded HTTP probes ครบ ไม่ให้ผู้เรียนสร้าง App เองก่อนทำระบบ

## Requirements และวิธีพิสูจน์

| ID | Must-have | Acceptance / หลักฐานที่ต้องเก็บ |
|---|---|---|
| R1 | HTTPS user journey ผ่าน Web → private API → SQL | login/list/create/read/cancel ทำงานจริง เก็บ order reference, request IDs และผลจาก DB โดยไม่เปิด API/DB สาธารณะ |
| R2 | แยก tier และ runtime identity | Web/API VMs ไม่มี external IP; Web SA อ่าน DB secret ไม่ได้; client ที่ไม่ใช่ Web tier เข้า API VIP/backend ไม่ได้ตาม firewall matrix; anonymous/other-owner/operator negative tests |
| R3 | ธุรกรรมถูกต้องแม้คำขอพร้อมกันหรือซ้ำ | หลาย API process ใช้ DB เดียว ไม่ขายเกิน stock; retry key เดิมได้ order เดิม; key เดิมเปลี่ยน payload ได้ 409; cancel ซ้ำไม่คืน stock ซ้ำ; stock/ledger reconciliation ไม่มีส่วนต่าง |
| R4 | Web/API แต่ละ tier อยู่สอง zone และรับมือ App เครื่องเดียวเสีย | กำหนด fault กับหนึ่ง VM/หนึ่ง process ตรวจ LB health, MIG action, surviving requests และ recovery instance ID; ไม่อ้าง zone outage จริงจากการหยุด process เดียว |
| R5 | Rolling update ที่ตรวจและถอยได้ | ทดสอบ compatible v2 และ bad startup template; บันทึก current actions/healthy replicas/errors; backout template ที่ยังอ่าน schema เดิมได้ ไม่อ้างว่า update policy รับประกัน zero errors |
| R6 | Cloud SQL HA และ reconnect หลัง planned failover | ใช้ Enterprise REGIONAL private SQL; ตรวจ primary/standby configuration และ operation จริงก่อน-หลัง failover; วัดช่วง error/recovery จาก probe; retry key เดิมและตรวจ order/stock ไม่ซ้ำ |
| R7 | รับ Change Request เพิ่ม API replicas/connection capacity อย่างมีเหตุผล | API2→4 replicas, pool4 คงเดิม; คำนวณ surge/old/new/admin headroom ก่อนเปลี่ยน เทียบ bounded load/latency/error/DB connections/invariants และทดสอบ backout |
| R8 | มี runbook, evidence, cleanup และ rebuild | ผู้เรียนแยก LB/MIG/process/network/SQL สาเหตุได้ เก็บ timeline/decision/case study และลบ DNS/TLS/LB/MIG/templates/SQL/secrets/NAT/artifacts/VPC ตาม inventory ของ Lab |

Optional extensions ที่ไม่ใช้แทน baseline: mTLS ระหว่าง Web/API, managed login/SSO, autoscaling policy, Cloud Armor, cross-region recovery และ destructive schema migration ต้องออกแบบ/ทดสอบแยก ไม่อ้างว่ามีแล้ว

## Architecture ที่เลือก

- Region asia-southeast1; Web และ API เป็น regional managed instance groups คนละกลุ่ม กลุ่มละ 2VM กระจายสอง zone ไม่ใช่ unmanaged groups จาก Lab01
- Public global external Application Load Balancer รับ HTTPS ด้วย domain ที่ผู้เรียนควบคุม DNS ได้ ส่งไป Web Nginx บน private VMs
- Web ให้ static UI และ reverse proxy /api ไป **regional internal passthrough Network Load Balancer TCP8080** ซึ่งกระจายไป API VMs ใช้ L4 เพื่อรักษา client source และกำหนด ingress API ให้มาจาก Web tier ตาม matrix ไม่วาดเป็น regional L7proxy หรือเพิ่ม proxy-only subnet โดยไม่มีบริการนั้น
- API ใช้ PostgreSQL transactions/locks/idempotency ledger ผ่าน Cloud SQL Python Connector private IP/TLS ไป Cloud SQL PostgreSQL16 Enterprise REGIONAL (HA) ใน region เดียวกัน
- Custom VPC; แยก regional Web/API subnets; PSA allocation เป็น managed service producer address space ไม่ใช่ subnet ของฐานข้อมูล VM
- Cloud Router/NAT สำหรับ private VM outbound ตามจำเป็น; IAP TCP forwarding + OS Login สำหรับดูแล ไม่เปิด SSH0.0.0.0/0
- Web SA ไม่มี SQLClient/DBSecretAccessor; API SA มีสิทธิ์เฉพาะ SQLClient, App/DBsecret, อ่าน release artifact ที่ต้องใช้ และส่ง logs ตามจำเป็น Bootstrap/admin เป็น identity คนละชุด
- Release artifact ตรึง source commit/hash; instance template ใหม่สำหรับแต่ละ release ไม่มี password อยู่ใน template/startupmetadata/image/repository
- Public TLS จบที่ externalLB ส่วน Web→API baseline เป็น HTTP ใน private VPC พร้อม firewall/Appauth **ไม่ใช่ end-to-end mTLS** ต้องระบุ trade-off นี้ชัดเจน SQL connector ใช้ TLS แยกต่างหาก

เลือก Terraform สร้างระบบซ้ำได้ และใช้ Console/CLI สำรวจ ตรวจ health/metrics ทำ rollout/failover และวิเคราะห์เหตุ แทนการสร้าง manual ชุดหนึ่งแล้วให้ Terraform สร้างชื่อซ้ำทับ หากต้องนำของที่สร้าง manual เข้า state ต้องมีขั้น import/reconcile เฉพาะ ไม่ให้ผู้เรียนเดาเอง

## Data และ App contract

products มี SKU/ชื่อ/stock ตั้งต้น; orders มี UUID/owner/status/idempotency key/request fingerprint; order_items มี quantity และ snapshot ราคาหน่วยเป็นจำนวนเต็ม; stock_events มี order/SKU/effect/event และ unique business constraints

Create order ต้องล็อกสินค้าในลำดับแน่นอนและทำ stock/order/event ใน transaction เดียว; การ cancel คืนเฉพาะ order ที่ confirmed ครั้งแรก ไม่ลบ ledger สอง API เครื่องต้องพิสูจน์จาก DB เดียวกัน ไม่ใช้ in-memorycounter แทนผลจริง

API มี /livez สำหรับ process และ /healthz ตรวจ schema/DB แยกบทบาทจากกัน LB/autohealing ที่ใช้ processhealth ต้องไม่ recreate ทุก VM เพียงเพราะ SQL failover ชั่วคราว จะยืนยัน startup grace/readiness/health thresholds ใน Design ก่อนเขียน Task

App user ใช้ hashed demo passwords, secure session/CSRF/ownership/role มีข้อจำกัด production ระบุชัด ชุดทดสอบต้องไม่พิมพ์ cookie/secret และอ่านรหัสจาก privatefile ไม่รับ plaintextpassword ใน command line

## Operation scenarios ที่ต้องเตรียม

1. Normal journey + unauthorized/cross-owner/role/network checks
2. Concurrent orders บน API สอง process, duplicate delivery/key conflict, cancel replay และ reconciliation
3. Stop หนึ่ง API process แบบควบคุม ตรวจ healthybackend ที่เหลือ/MIG recovery ไม่ขยาย fault เป็นลบทั้งกลุ่ม
4. Compatible rolling release และ bad-template rollout พร้อม backout/evidence
5. Planned Cloud SQL HA failover ระหว่าง bounded writes/readiness checks จด operation ID, errors, reconnect time และ data integrity ไม่สัญญาว่าไม่มี connectionreset
6. Change API2→4 พร้อม surge/headroom calculation และ retest
7. Cleanup จาก inventory ของ Lab นี้และ rebuild จาก source/infra version เดิม โดยไม่พึ่ง resource จาก Lab ก่อน

## Connection และ resource assumptions ก่อนทำ Guide

ค่าตั้งต้นที่จะตรวจอีกครั้ง: App หนึ่ง worker/VM, pool4/max_overflow0, Web2VM/API2VM, APIchange4VM, regional rollout เผื่อ surge สำหรับสอง zone ต้องคำนวณ instance สูงสุดช่วง rollout ก่อนเลือก SQL max_connections และขนาดเครื่อง ไม่ใช้จำนวน replicas steady state เป็น connection hard cap

ต้องมี Sandbox ที่เปิด Billing, compute/SQL/NAT/LB quotas, สิทธิ์ IAM/OSLogin/IAP/DNS ที่จำเป็น และ domain/subdomain ของผู้เรียนเอง หากไม่มี domain/สิทธิ์ DNS จะยังไม่ผ่าน R1 แบบ HTTPS ห้ามเปลี่ยนเป็น publicHTTP แล้วอ้างว่าครบ baseline

SQL HA, VMs หลายเครื่อง, NAT, LB, disks/backups/logs และ IP มีค่าใช้จ่ายระหว่างฝึก ต้องประมาณงบและเวลาปิดก่อน provision Budget เป็น alert ไม่ใช่ hard cap Cloud verification ยังเป็น Not run

## แหล่งอ้างอิงที่ใช้ปิดขอบเขต

- [Cloud SQL PostgreSQL high availability](https://docs.cloud.google.com/sql/docs/postgres/high-availability)
- [Internal passthrough Network Load Balancer](https://docs.cloud.google.com/load-balancing/docs/internal)
- [Managed instance group rolling updates](https://docs.cloud.google.com/compute/docs/instance-groups/rolling-out-updates-to-managed-instance-groups)
- [External Application Load Balancer](https://docs.cloud.google.com/load-balancing/docs/https)

ขั้นถัดไป: ยืนยัน ports/source identities/routes/health policy, tier placement, SQL sizing/connection budget และ data invariants → working App/installer/tests/IaC → Diagram → Tasks พาทำ → Review/Guide-ready ยังไม่ถือว่า Brief นี้เป็น Lab ที่ทำเสร็จ


## Design — ขอบเขตที่ใช้ทำ Materials

### Resource map และ placement

| ส่วน | Baseline |
|---|---|
| Region / zones | asia-southeast1; เลือก zone a/b ให้ทั้งสอง MIG อย่างชัดเจน ไม่ปล่อย regional MIG ใช้สาม zone โดยไม่คำนวณ surge |
| VPC | lab005-vpc แบบ custom; Web subnet10.55.10.0/24 และ API subnet10.55.20.0/24 เป็น regional subnets ไม่แยก subnet ซ้ำตาม zone |
| Public edge | global EXTERNAL_MANAGED HTTPS LB, managed certificate, reserved public IP และ DNS record ของผู้เรียน; Web backend port80 |
| Web | regional MIG2 replicas; Nginx static UI/reverse proxy, e2-small เบื้องต้น, private IP เท่านั้น, Web SA เฉพาะ |
| Private API VIP | regional INTERNAL passthrough TCP8080 ใน API subnet, allow_global_access=false; backend เป็น API MIG ไม่มี proxy-only subnet |
| API | regional MIG2 replicas → change4; private IP, Gunicorn1worker/8threads, pool4/overflow0, API SA เฉพาะ |
| SQL | orders database, PostgreSQL16 Enterprise REGIONAL, private services access10.85.0.0/16, ไม่มี publicIP; baseline tier db-custom-1-3840 ต้องตรวจ quota/ราคา/region ก่อน provision |
| SQL HA | primary/secondary คนละ zone ภายใน region เดียวกัน ไม่วาดเป็นสอง database ที่ App ต้องเลือกเองหรือ read replica ที่ใช้กระจายอ่าน |
| Outbound / admin | regional NAT และ Router, OS Login/IAP; diagnostic/init VM ชั่วคราวคนละ SA และไม่มี externalIP ใช้เท่าที่ต้องตรวจ/initialize แล้วลบ |
| Release | private versioned GCS artifact bucket, Web/API archives แยกและตรึง SHA256, Secret containers แยก auth/runtimeDB/admin ไม่ใส่ payload ใน Terraformstate |

PublicLB เป็น global, MIG/subnets/internalLB เป็น regional, VM เป็น zonal และ SQLHA เป็น regional managed resource เส้นทาง SQL ไป service-producer network ไม่ใช่ VM ใน API subnet

### Network / identity matrix

| Source → destination | Port / path | เกณฑ์ |
|---|---|---|
| Browser → publicLB | HTTPS443 | เปิด login/UI แต่ business endpoints ต้อง Appsession/CSRF/owner/role |
| GFE/health → WebSA VMs | TCP80; ranges35.191.0.0/16,130.211.0.0/22 | แยก rule จาก API sourceidentity; ยืนยันชนิด LB ก่อนใช้ ranges |
| WebSA primary NIC → API SA VMs ผ่าน privateVIP | TCP8080 | source_service_accounts=WebSA,target_service_accounts=APISA ใน VPC เดียวกัน ไม่ผสม networktags กับ SA |
| Health probers → API SA VMs | TCP8080 จาก health ranges เท่านั้น | เป็น exception สำหรับ health ไม่ใช่การยืนยัน Appidentity จาก IP |
| Diagnostic SA VM → API VIP/backend | TCP8080 | ต้องถูกปฏิเสธโดย ingresspolicy; อ่าน default/organization rules ก่อนสรุป |
| API → SQLprivateIP | TCP3307 สำหรับ connectorTLS + HTTPS443 สำหรับ Admin API/certificate | native5432 ใช้เฉพาะกรณีที่เลือก driverdirect แยก ไม่วาด connector เป็น 5432; SQLClient ไม่แทน DBlogin/grants |
| Web → SQL PSA range | egress deny ทั้ง range สำหรับ WebSA | กัน Web ข้าม API tier; ยังต้องทดสอบ Web อ่าน DBsecret ไม่ได้แยกอีกชั้น |
| IAP → Web/API/diagnostic/init | SSH22 จาก 35.235.240.0/20 | OSLogin/IAPIAM และ actAs ต้องถูกต้อง ไม่ใช่มี firewall แล้วใครก็ SSH ได้ |
| VMs → metadata/DNS/GoogleAPI/package sources | ตาม startup/runtime จำเป็น | ไม่มี default allow-internal; baselineegress ส่วนอื่นไม่ได้อ้างเป็น allowlist สมบูรณ์หรือ NAT เป็น firewall |

ใช้ sourceSA และ sourceCIDR ใน rule เดียวกันจะเป็น union ไม่ใช่ AND จึงแยก Web-client rule กับ health-check rule และ target ด้วย SA สอดคล้องกัน ทั้งนี้ SA ใน firewall คือ identity ของ VM primaryNIC ไม่ใช่ signed JWT ของผู้ใช้

### Health, startup และการดูแล

- Web /livez ตอบเฉพาะ Nginx/staticrelease พร้อมใช้ ไม่เรียก DB ผ่าน API; API /livez ตรวจ process และ releaseconfig ส่วน /healthz query schema/DB
- LB/autohealing ใช้ processhealth ไม่ทำให้ SQLfailover กลายเป็น massVMreplacement ตรวจ DBhealth ผ่าน probe/log/metrics แยก
- Baselinehealth interval10s/timeout3s/threshold2; autohealing initial delay300s, rolling minReady30s เป็นค่าฝึกที่จะตรวจใน materials ไม่อ้างว่าเก็บ error ได้ทันทีหรือไม่มี connection ขาด
- App poolwait3s, SQLstatement5s/lock3s, connectorconnectiontimeout5s, Gunicornrequesttimeout30s; dependencyerror ตอบ sanitized503 และ requestID ไม่ส่ง rawDBerror ถึง Browser
- Installer ต้องดาวน์โหลด archive ตาม hash, ปฏิเสธ path traversal/symlink ที่ไม่คาดหมาย, ติดตั้ง release แบบ immutable, ดึง numericsecretversions ด้วย attachedSA และเขียน privatefile ให้ daemon เท่านั้น Startupmetadata มี references ไม่ใช่ password
- Bootstrap ใช้ init VM/identity ชั่วคราวกับ adminsecret เท่านั้น API MIG เปิดหลัง schema/seed/runtimegrants ตรวจแล้ว Web ไม่มี admin/DBsecret ไม่เอา initcredential ไปใช้ใน APIservice

### Data invariants และ request contract

POST /api/orders รับ items1–10SKU, quantity เป็น integer1–20 (ไม่รับ bool), SKU ซ้ำใน cart ถูกปฏิเสธ, Idempotency-Key8–80 ตัวอักษร; normalizeSKU order ก่อน hashpayload และ lockproducts ตาม SKU order เพื่อลด deadlock

Transaction: advisory lock ตาม owner+key → ตรวจ replay/fingerprint → SELECTproductsFORUPDATE ตามลำดับ → ตรวจ stock และ snapshotprice → INSERTorder/items/events + UPDATEavailable → commit ถ้าขั้นใดล้มทุก mutation ต้อง rollback

Cancellation: lockorder ของ owner → lockproducts ตาม SKU order → เปลี่ยน status/cancelled_at+คืน stock+event ครั้งเดียวใน transaction Operator อ่านภาพรวมได้แต่ไม่เป็น owner แทนลูกค้า

ต้องตรวจอย่างน้อย:
- available = initial + sum(stock_events.delta) และไม่ติดลบ/เกิน initial
- order.total_satang = sum(item.quantity × price_snapshot_satang)
- ทุก item มี reserved event หนึ่งรายการ; confirmed ไม่มี cancelled event; cancelled มี cancelled หนึ่งรายการเท่าจำนวนเดิม
- ไม่มี order ว่าง, key หนึ่งชุดของ owner เดียวไม่มี order ซ้ำ และ replaypayload ต่างต้อง 409

ราคาหน่วยเป็นจำนวนเต็มสตางค์ ไม่ใช้ float และไม่อ้างว่านี่คือระบบรับชำระเงินจริง เปลี่ยนราคาภายหลังไม่แก้ snapshot ของ order ที่สร้างแล้ว

### Connection / rollout budget และ change

| สถานะ | API VMs ตามแผน | pool สูงสุดเชิงคำนวณ |
|---|---:|---:|
| Baseline | 2 | 8 |
| Baseline rolling: surge2 / unavailable0 | 4 | 16 |
| Change steady state | 4 | 16 |
| Change rolling: surge2 / unavailable0 | 6 | 24 |

เลือก SQL max_connections64 เบื้องต้นและจอง headroom สำหรับ admin/health/connection ที่กำลังปิด ต้องตรวจ pg_stat_activity และ metrics จริง ไม่อ้างตัวเลขในตารางเป็น hard cap ระหว่าง recreate/failover หรือใช้ worker หลายตัวต้องคำนวณใหม่ เผื่อ computequota รวม Web/API surges ด้วย ไม่ rollout สอง tier พร้อมกันระหว่างทดลอง

ใช้ regional rolling policyfixed maxSurge2,maxUnavailable0 เพราะมีสอง zone พร้อม healthcheck/minReady ไม่ใช้ maxSurge1 ซึ่งไม่เข้ากับ regionalconstraint หาก healthyreplicas ไม่เพิ่มจาก badtemplate ให้หยุด/กลับ template เดิม ไม่เพิ่ม maxUnavailable เพื่อบังคับให้ผ่าน

Failoverprobe ต้องมี boundeddeadline/requests และ idempotencykey คงเดิมสำหรับ logicalorder หนึ่งรายการ ถ้า response หายหลัง commit การ retry ต้องคืน reference เดิม ไม่สร้าง key ใหม่เพื่อให้ request สำเร็จ แยกเวลาตรวจพบ error, operationstart/end และเวลาที่ App กลับมาทำ journey ได้ จึงไม่ใช้ HA label แทนหลักฐาน applicationrecovery

### ลำดับส่งมอบ

1. Domainservice/schema/seed/grants/invariants + PostgreSQL16 tests (หลาย pool, races, replay, cancel, rollback, privilege)
2. HTTPS-facing UI/session API/health/logs และ HTTPprobes แยก Webstatic จาก API
3. Immutable artifacts + installer/systemd + secret/bootstrap/inspection tooling
4. Terraformfoundation → seed/init → workloads/LBs/TLS และ syntax/config checks ใน cloudCI
5. Diagram ตาม scope จริง + READMETasks/Expected/record/fault/change/cleanup
6. Review/read-back/render/Guide-ready; GCPverification ยัง Not run จนผู้เรียนรันจริง

อ้างอิง Design เพิ่มเติม: [VPC firewall source/target service accounts](https://docs.cloud.google.com/firewall/docs/firewalls#service-accounts), [LB firewall ranges](https://docs.cloud.google.com/load-balancing/docs/firewall-rules), [connector v1.18.5 implementation](https://github.com/GoogleCloudPlatform/cloud-sql-python-connector/blob/v1.18.5/google/cloud/sql/connector/connector.py)


## Materials ที่กำลังตรวจ

[Order domain](app/orders.py), [schema](db/schema.sql), [seed](db/seed.sql), [runtime grants](db/grants.sql), [invariants](db/check-invariants.sql) และ [PostgreSQL transaction tests](tests/test_orders.py) เป็นแกนธุรกรรมที่ใช้ร่วมกับ API ยังไม่ใช่คู่มือ Deploy หรือผล Cloud SQL HA จริง


[Orders API](app/main.py), [private DB pool](app/database.py), [Web UI](web/index.html), [browser script](web/app.js), [Nginx template](web/nginx.conf.template) และ [config renderer](scripts/render-web-config.py) แยก Web static tier ออกจาก API โดยใช้ session/CSRF/owner/role และแชร์ข้อมูลผ่าน PostgreSQL ไม่ใช้ in-memory stock

UI เก็บเฉพาะ pending cart + idempotency key ใน sessionStorage ของแท็บนั้นเพื่อใช้คำขอเดิมหลัง response หาย ไม่เก็บรหัสผ่าน/cookie/CSRF ใน storage การทดสอบเบราว์เซอร์จำลอง response หายหลัง DB commit แล้ว reload/retry และตรวจ order/stock จาก DB จริง เป็นการทดสอบใน CI ไม่ใช่ผล Deploy GCP หรือ SQL HA failover
