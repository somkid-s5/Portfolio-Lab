---
lab: LAB-002
platform: GCP
guide_status: authoring
cloud_verification: not-run
last_verified: null
---
# Lab 02 — Inventory ภายในองค์กรที่ไม่เปิด App และ Database สู่อินเทอร์เน็ต

ทีมคลังสินค้าต้องค้นหาสินค้า ดูยอดคงเหลือ และบันทึกรับเข้า/เบิกออกจากเครือข่ายภายใน ผู้ดูแลต้องแยกให้ได้ว่าการเข้าไม่ได้เกิดจาก DNS, network, App auth หรือฐานข้อมูล โดยไม่เปิด public ingress เพื่อแก้ปัญหา

## ขอบเขตที่เลือก

- Singapore region; custom VPC `lab002-vpc` มี app subnet `10.22.10.0/24`, data subnet `10.22.20.0/24`, client subnet `10.22.30.0/24` ทุก subnet เป็น regional ไม่ใช่ zonal
- App VM สอง Zone b/c ไม่มี external IP, unmanaged instance groups และ **regional internal passthrough Network Load Balancer TCP:8080**; App เป็น HTTP UI/API บน TCP นี้ ไม่ใช่ internal Application LB จึงไม่สร้าง proxy-only subnet
- PostgreSQL 15 บน data VM ไม่มี external IP ใช้ private IP คงที่ ให้ application DB user เฉพาะ database Inventory และ firewall 5432 เฉพาะ app target/source tags; client ห้ามต่อ DB โดยตรง
- Client VM ไม่มี external IP เข้า App ผ่าน private DNS `inventory.lab.internal` ซึ่งชี้ internal LB VIP; Cloud Shell ใช้ IAP SSH เข้า client แล้วรัน requests จาก client ไม่ทดสอบ internal VIP จาก Cloud Shell โดยตรง
- Cloud Router + Public NAT สำหรับ outbound package installation ของ private VMs เท่านั้น ไม่ใช่ทางเข้า App
- IAP SSH ใช้ source range/roles ตามข้อกำหนด; VM ไม่มี runtime service account เพราะไม่เรียก Cloud API จาก workload

## Business flow และข้อมูลที่จะเตรียม

UI ค้นหา SKU และดู stock; API ตรวจ role แบบ reader/operator ด้วย bearer token สำหรับ demo เก็บ token hash ใน App config ไม่ใส่ credential ใช้งานจริงใน Repo สร้าง token บน sandbox และส่งผ่าน SSH/file ที่ permission จำกัด ไม่ผ่าน query string หรือ screenshot แบบเปิดเผย App ต้องไม่ log token/password

ฐานข้อมูลมี products, stock และ movements; seed อย่างน้อย 5 สินค้า การเบิกใช้ transaction/row lock และห้าม stock ติดลบ movement มี idempotency key เพื่อไม่หักซ้ำเมื่อ retry สอง App ใช้ข้อมูลชุดเดียว ต้องมี schema/seed และตัวตรวจ invariant ให้ครบใน Lab นี้ ไม่พึ่ง Lab 01

## Requirements และหลักฐาน

| ID | ผลที่ต้องได้ | วิธีพิสูจน์ | หลักฐาน |
|---|---|---|---|
| R1 | Private client resolve และเข้า UI/API ได้ | DNS ตอบ VIP และ HTTP 200 จาก client; ตรวจ VM ทุกตัวไม่มี external IP | DNS output, VM inventory, response |
| R2 | สอง App ใช้ Inventory เดียวกัน | Read stock, operator สร้าง movement แล้วอ่านกลับจาก sample ที่เห็นทั้ง backend | request IDs, backend IDs, stock/movement |
| R3 | จำกัดสิทธิ์ผู้ใช้ App | ไม่มี token ได้ 401, reader write ได้ 403, operator ทำได้ | redacted HTTP results; ไม่เก็บ token |
| R4 | ไม่หัก stock ซ้ำ/ติดลบ | retry key เดิมไม่เพิ่ม movement; concurrent withdrawal เกิน stock ถูก reject อย่างมีเหตุผล; sum movements reconcile | bounded business test JSON, SQL invariant |
| R5 | Network boundary ถูกต้อง | client→DB5432 denied, app→DB allowed, IAP→SSH allowed; public ingress ไม่มีและไม่มี external IP | effective rules, timed tests, resource inventory |
| R6 | แยกและกู้ dependency outage | หยุด PostgreSQL ชั่วคราว ดู App 503/readiness/logs แล้ว start และทดสอบ business flow ซ้ำ | incident timeline, health, redacted logs |
| R7 | เพิ่มเครือข่าย client อย่างควบคุม | เพิ่ม subnet2 10.22.40.0/24/client2; ก่อนอนุญาต App ใช้ไม่ได้ หลังเพิ่มเฉพาะ App rule ใช้ได้ แต่ DB ยังเข้าไม่ได้ | before/after flow matrix |
| R8 | Cleanup/rebuild ครบ | ลบ private DNS/LB/groups/VM/disks/NAT/router/rules/subnets/VPC ที่สร้าง; ต้นทางอยู่ใน commit | inventory และคำสั่งตรวจของเหลือ |

Fault injection ต้องทำใน sandbox หลังบันทึกยอดตั้งต้นและสำรองข้อมูล ไม่อ้าง zero downtime เพราะ DB baseline เป็นเครื่องเดียว ไม่มี managed HA; ภายหลังอธิบาย trade-off ไป Cloud SQL แต่ไม่บังคับสร้างอีก Solution ในเรื่องนี้

## ทางเลือกและขอบเขตความปลอดภัย

เลือก internal passthrough LB เพื่อทดสอบ source-preserving private network path; firewall backend จึงต้องยอมรับ client CIDRs ที่ตั้งใจอนุญาตพร้อม Google health-check ranges ไม่ใช้กฎ proxy-only ของ Application LB มาปะปน LB private ไม่ใช่ระบบยืนยันตัวตนแทน App

Bearer token demo ใช้ฝึกแยก 401/403 จาก network deny ไม่อ้างว่าเป็น enterprise SSO ไม่ใช้ข้อมูลจริง เนื่องจาก baseline HTTP และ PostgreSQL private traffic ยังไม่เข้ารหัส end-to-end ระบุ TLS/องค์กร identity เป็นข้อจำกัด ไม่อ้าง private network เท่ากับป้องกันทุก threat

NAT/LB/VM/disk/IPv4/router traffic มีต้นทุน ต้องกำหนดวงเงินและเวลาปิดก่อนรัน ไม่สร้าง GCP resources ในขั้นจัดทำเอกสาร ตรวจ API, IAM, region/quota, image/แพ็กเกจและ organization constraints ก่อน Guide-ready

## ลำดับงานหลัง Brief

1. ยืนยัน port/source/destination access matrix, subnet/VIP/static addresses และ data/identity flow
2. สร้าง App, schema/seed, token management และ bounded tests พร้อมทดสอบกับ PostgreSQL ใน cloud CI
3. ทำ Diagram ที่ตรง private network และชนิด LB จริง
4. เขียน Console/CLI walkthrough ตั้งแต่ clean project พร้อม DNS/NAT/IAP, deploy และบันทึกข้างแต่ละ Task
5. ตรวจ normal/access/data/fault/change/recovery/cleanup ทุก requirement แล้วจึงเลื่อนเป็น Guide-ready

สถานะ: Authoring — App/schema และส่วนติดตั้งอยู่ระหว่างตรวจ คู่มือยังไม่ครบทุก Tasks และยังไม่ใช่ Guide-ready ผล GCP จริงยัง Not run

## Access matrix ที่ใช้เขียน Tasks

| Source | Destination | Port / policy |
|---|---|---|
| client subnet 10.22.30.0/24 | App tag lab002-app | TCP 8080 allow |
| client2 subnet 10.22.40.0/24 | App tag lab002-app | deny ก่อน change; allow8080 หลัง change |
| Google health check ranges | App tag lab002-app | TCP 8080 allow |
| App tag lab002-app | DB tag lab002-db | TCP 5432 allow |
| client/client2 | DB | deny5432 |
| IAP 35.235.240.0/20 | VMs tag lab002-admin | TCP22 allow |
| Private VMs | Internet package mirrors | outbound via Public NAT; ไม่มี unsolicited inbound |

App เปิด /livez สำหรับ process และ /healthz ตรวจ DB/schema; reader อ่าน /api/products และ /api/movements ได้ ส่วน operator POST /api/movements โดยมี Idempotency-Key แต่ละ request เปิด DB connection ใหม่และจำกัด active DB operations 8 ต่อ process, connect/statement/lock timeouts แบบจำกัด ขอบเขตนี้ไม่ใช่ production pool design

ไฟล์ประกอบ: [App](app/server.py), [UI](app/index.html), [schema](db/schema.sql), [seed](db/seed.sql), [reconciliation](db/check-invariants.sql), [tests](tests/test_inventory.py) — ขั้นติดตั้งและ secret generation จะเพิ่มในคู่มือหลัง materials ผ่านการตรวจ

## เตรียมลงมือทำ

คู่มือใช้ Console เลือก project/ตรวจทรัพยากร และ Cloud Shell สำหรับสร้างชุดที่ต้องใช้ชื่อ/IP ตรงกันทุกจุด คำสั่งสร้างทรัพยากรมีค่าใช้จ่าย ผู้เรียนต้องตรวจงบและสิทธิ์ก่อนรัน ไม่ใช้ project production

| สิ่งที่ต้องเตรียม | รายละเอียด |
|---|---|
| เวลาและต้นทุน | เผื่อ 4–6 ชั่วโมง; baseline มี App 2, DB 1, client 1 และ client2 เพิ่มภายหลัง พร้อม disk/NAT/public NAT IP/internal LB/DNS/logs; Budget ไม่ใช่ hard cap |
| สิทธิ์ | Compute Instance Admin v1, Network Admin, Security Admin, DNS Admin, Service Usage Admin สำหรับ enable APIs, IAP-secured Tunnel User; OS Admin Login ถ้าใช้ OS Login; ผู้ดูแลอาจให้ custom role ที่แคบกว่า |
| Quota/policy | E2 CPU และ disk พอสำหรับ VM สูงสุด 5 ตัว, internal addresses/LB, router/NAT; องค์กรอนุญาต Public NAT/IAP แต่ VM ทุกตัวไม่มี external IP |
| Runtime | Debian 12, PostgreSQL 15, distro python3-psycopg2; ใช้ e2-small สำหรับ App/client และ e2-medium สำหรับ DB ไม่ใช่ sizing production |
| ข้อมูล | Synthetic seed เท่านั้น; App HTTP/private DB connection ยังไม่ใช่ end-to-end TLS; reader/operator token เป็น demo ไม่ใช่ SSO |

### ค่าคงที่และจุดที่ต้องแทน

| Resource | ค่า |
|---|---|
| Project | ต้องแทน YOUR_PROJECT_ID |
| Region | asia-southeast1 |
| App A / B | lab002-app-a / b; Zone b / c; IP 10.22.10.10 / .11 |
| DB | lab002-db; Zone b; IP 10.22.20.10 |
| Client | lab002-client; Zone b; IP 10.22.30.10 |
| Client2 | lab002-client2; Zone c; IP 10.22.40.10 (Task Change) |
| Internal VIP | 10.22.10.50:8080 |
| DNS | inventory.lab.internal. → VIP, private zone lab002-private |
| Database / runtime user | inventory / inventory_app |
| App service | lab002-inventory; files /opt/lab002; config /etc/lab002 |

ทุกคำสั่งที่ระบุ **Cloud Shell** รันบน terminal ของ Console ไม่ใช่ใน VM เมื่อ SSH เข้า VM ให้ดู hostname ก่อนทำ และใช้ exit กลับ Cloud Shell ไม่ตั้ง PROJECT_ID บนเครื่องส่วนตัวเพื่อใช้แทนโดยไม่ระบุ

## Task 0 — ตั้ง Project และเตรียมไฟล์

**Console:** เลือก sandbox project ที่ผูก Billing เปิด **Billing → Budgets & alerts** ตั้งวงเงินแจ้งเตือนที่ยอมรับได้ ตรวจ **IAM & Admin → Quotas & System Limits** ให้เหลือ resource ตามตารางก่อนสร้าง ถ้าไม่มีสิทธิ์ให้บันทึก BLOCKED และขอผู้ดูแล ไม่เปิด public SSH แทน IAP

**Cloud Shell:** เปิด terminal ด้านบน Console แทน YOUR_PROJECT_ID แล้วรัน:

```bash
export PROJECT_ID="YOUR_PROJECT_ID"
export REGION="asia-southeast1"
gcloud config set project "$PROJECT_ID"
gcloud config get-value project
gcloud auth list --filter=status:ACTIVE
gcloud services enable compute.googleapis.com iap.googleapis.com dns.googleapis.com
git clone --branch docs/gcp-solution-labs --single-branch https://github.com/somkid-s5/Portfolio-Lab.git ~/portfolio-lab-002-source
export LAB_DIR="$HOME/portfolio-lab-002-source/GCP/LAB-002-private-inventory"
git -C ~/portfolio-lab-002-source rev-parse HEAD
cd "$LAB_DIR"
python3 scripts/create-secrets.py --out secrets
mkdir -p assets/evidence
```

ชื่อ directory clone ต้องยังไม่มี หากมีงานเก่าอย่าลบหรือ reset ทับ ให้ใช้ชื่อใหม่และแก้ LAB_DIR ให้ตรง บันทึก commit SHA แล้วใช้ code ชุดเดียวตลอด Lab Secrets generator สร้าง reader/operator token, hashes และ DB password โดยไม่แสดงค่า ไม่รันซ้ำที่ directory เดิมและไม่ใส่ไฟล์เหล่านี้ใน Git

**Expected:** project ตรง Console, API เปิด, secret bundle สร้างสำเร็จ ตรวจชื่อไฟล์ด้วย `ls -l secrets` เท่านั้น ไม่พิมพ์ password/token ลงหลักฐาน บน Cloud Shell directory เป็น 700 และไฟล์ 600

**บันทึก T00:** Project alias [เติม] / commit [เติม] / API/IAM/quota [เติม] / งบและเวลาปิด [เติม] / สถานะ PENDING

## Task 1 — สร้าง Private Network และ NAT

**Cloud Shell:** คำสั่งต่อไปนี้สร้างทรัพยากรใน project ที่ตั้งไว้ ตรวจค่าก่อนรัน ไม่ใช้ชื่อซ้ำกับของที่มีอยู่:

```bash
gcloud compute networks create lab002-vpc --subnet-mode=custom
gcloud compute networks subnets create lab002-app-subnet \
  --network=lab002-vpc --region="$REGION" --range=10.22.10.0/24
gcloud compute networks subnets create lab002-data-subnet \
  --network=lab002-vpc --region="$REGION" --range=10.22.20.0/24
gcloud compute networks subnets create lab002-client-subnet \
  --network=lab002-vpc --region="$REGION" --range=10.22.30.0/24
gcloud compute routers create lab002-router --network=lab002-vpc --region="$REGION"
gcloud compute routers nats create lab002-nat --router=lab002-router \
  --region="$REGION" --nat-all-subnet-ip-ranges --auto-allocate-nat-external-ips
```

**Console:** ค้น **VPC networks** เปิด lab002-vpc ตรวจสาม subnet ใน Singapore จากนั้นค้น **Cloud NAT** เปิด lab002-nat ตรวจ router/region และ source subnets ใช้ทุก subnet ใน region ของ VPC นี้ จึงครอบคลุม client2 ที่เพิ่มภายหลัง แต่ไม่ได้เปิด inbound ให้ VM

ถ้า apt ติดตั้งไม่ได้ภายหลัง ตรวจ NAT coverage, default route และ egress policy ก่อนเพิ่ม external IP การเรียก Google APIs ใช้เส้นทาง Private Google Access ตาม configuration ของบริการ ไม่สรุปจาก NAT ว่าทุก packet วิ่งเส้นเดียวกัน

**บันทึก T01:** network/subnets [เติม] / router/NAT [เติม] / ภาพ subnet และ NAT config [แนบ assets/evidence/t01-network.png] / สถานะ PENDING

## Task 2 — เปิดเฉพาะเส้นทางที่ใช้

**Cloud Shell:**

```bash
gcloud compute firewall-rules create lab002-iap-ssh --network=lab002-vpc \
  --direction=INGRESS --action=ALLOW --rules=tcp:22 \
  --source-ranges=35.235.240.0/20 --target-tags=lab002-admin
gcloud compute firewall-rules create lab002-client-app --network=lab002-vpc \
  --direction=INGRESS --action=ALLOW --rules=tcp:8080 \
  --source-ranges=10.22.30.0/24 --target-tags=lab002-app
gcloud compute firewall-rules create lab002-health --network=lab002-vpc \
  --direction=INGRESS --action=ALLOW --rules=tcp:8080 \
  --source-ranges=35.191.0.0/16,130.211.0.0/22 --target-tags=lab002-app
gcloud compute firewall-rules create lab002-app-db --network=lab002-vpc \
  --direction=INGRESS --action=ALLOW --rules=tcp:5432 \
  --source-tags=lab002-app --target-tags=lab002-db
gcloud compute firewall-rules list --filter='network:lab002-vpc'
```

**Expected:** มีสี่ allow rules ตาม matrix และไม่มี default allow-internal/all-source SSH แบบกว้าง ไม่ต้องสร้าง explicit deny เพราะ custom VPC มี implied deny ingress แต่ต้องตรวจ hierarchical/network firewall policies ที่ใช้จริงด้วย

Internal passthrough LB รักษา client source IP จึง allow client subnet ที่ App ไม่ใช่เปิดเฉพาะ proxy subnet แบบ Application LB Client ที่ได้รับอนุญาตอาจเข้า private App IP:8080 โดยตรงได้ในแบบนี้ ไม่อ้างว่า LB เป็น security boundary หรือยืนยันตัวตนแทน App

**บันทึก T02:** rule/source/target/port จริง [เติม] / inherited policy ที่พบ [เติม] / assets/evidence/t02-firewall.txt [แนบ] / สถานะ PENDING

## Task 3 — สร้าง VM ที่ไม่มี External IP

**Cloud Shell:** ทุกเครื่องใช้ No service account เพราะ workload ไม่เรียก Cloud API การสร้าง/SSH เป็นสิทธิ์ผู้ดูแลคนละส่วน:

```bash
gcloud compute instances create lab002-db --zone=asia-southeast1-b \
  --machine-type=e2-medium --subnet=lab002-data-subnet --private-network-ip=10.22.20.10 \
  --no-address --no-service-account --no-scopes --tags=lab002-db,lab002-admin \
  --image-family=debian-12 --image-project=debian-cloud --boot-disk-size=10GB
gcloud compute instances create lab002-app-a --zone=asia-southeast1-b \
  --machine-type=e2-small --subnet=lab002-app-subnet --private-network-ip=10.22.10.10 \
  --no-address --no-service-account --no-scopes --tags=lab002-app,lab002-admin \
  --image-family=debian-12 --image-project=debian-cloud --boot-disk-size=10GB
gcloud compute instances create lab002-app-b --zone=asia-southeast1-c \
  --machine-type=e2-small --subnet=lab002-app-subnet --private-network-ip=10.22.10.11 \
  --no-address --no-service-account --no-scopes --tags=lab002-app,lab002-admin \
  --image-family=debian-12 --image-project=debian-cloud --boot-disk-size=10GB
gcloud compute instances create lab002-client --zone=asia-southeast1-b \
  --machine-type=e2-small --subnet=lab002-client-subnet --private-network-ip=10.22.30.10 \
  --no-address --no-service-account --no-scopes --tags=lab002-client,lab002-admin \
  --image-family=debian-12 --image-project=debian-cloud --boot-disk-size=10GB
gcloud compute instances list --filter='name~^lab002-' \
  --format='table(name,zone,networkInterfaces[0].networkIP,networkInterfaces[0].accessConfigs[0].natIP)'
```

**Expected:** สี่เครื่อง Running, internal IP ตามตาราง, NAT_IP ของ VM ว่างทั้งหมด NAT gateway มี public IP ไม่ใช่การผูก external IP กับ VM

จาก Cloud Shell ทดสอบ IAP:

```bash
gcloud compute ssh lab002-client --zone=asia-southeast1-b --tunnel-through-iap
```

**ใน client VM:** รัน `hostname` ต้องเป็น lab002-client แล้ว `sudo apt-get update` เพื่อตรวจ outbound ผ่าน NAT จากนั้น `exit` กลับ Cloud Shell หาก SSH ไม่ได้แยก IAP role/firewall/OS Login ก่อน ไม่เพิ่ม external IP

**บันทึก T03:** VM/Zone/IP/image version ที่ใช้ [เติม] / IAP และ apt ผลจริง [เติม] / assets/evidence/t03-private-vms.txt [แนบ] / สถานะ PENDING

## Task 4 — ติดตั้ง PostgreSQL และตั้งสิทธิ์

**Cloud Shell:** เตรียม archive เฉพาะ code ไม่มี secrets ใน archive:

```bash
cd "$LAB_DIR"
export TASK_TMP="$(mktemp -d)"
tar -czf "$TASK_TMP/lab002-code.tgz" app db scripts
gcloud compute scp "$TASK_TMP/lab002-code.tgz" secrets/db-password.txt \
  lab002-db:~/ --zone=asia-southeast1-b --tunnel-through-iap
gcloud compute ssh lab002-db --zone=asia-southeast1-b --tunnel-through-iap
```

**ใน DB VM:** ห้ามใช้ชุดนี้บนฐานข้อมูลที่มีงานอื่น ใช้ cluster PostgreSQL 15/main เฉพาะ Lab:

```bash
hostname
mkdir -p ~/lab002
tar -xzf ~/lab002-code.tgz -C ~/lab002
chmod 600 ~/db-password.txt
sudo apt-get update
sudo apt-get install -y postgresql-15 python3
sudo python3 ~/lab002/scripts/configure-db.py --password-file ~/db-password.txt
sudo -u postgres psql -d inventory -c 'SELECT sku,quantity FROM stock ORDER BY sku;'
sudo -u postgres psql -d inventory < ~/lab002/db/check-invariants.sql
sudo ss -lntp | grep 5432
rm -- ~/db-password.txt
exit
```

หมายเหตุ: ถ้า postgres อ่านไฟล์ check-invariants ใน home ไม่ได้เพราะ home permissions ให้ใช้ `sudo -u postgres psql -d inventory < ~/lab002/db/check-invariants.sql` แทน การ redirect อ่านโดย shell ของผู้ดูแล ไม่เปิด permission home ทั้ง directory

**Expected:** สินค้า 5 รายการ, PEN-01=20, reconciliation ไม่มีแถวผิดปกติ, PostgreSQL ฟัง localhost และ 10.22.20.10:5432 เครื่องมือตั้งค่าไม่พิมพ์ password; App role ไม่มี superuser/createdb/createrole และไม่มีสิทธิ์ลบ movement หรือแก้ชื่อสินค้า

Script เพิ่ม host authentication เฉพาะ inventory/inventory_app จาก app subnet โดยใช้ scram-sha-256 ไม่ใช่ trust และ restart cluster หลังเปลี่ยน listener การรันซ้ำไม่ reset stock แต่จะตั้ง password ให้ตรง bundle ที่ป้อน จึงอย่าสลับ bundle กลาง Lab

**บันทึก T04:** version/listener/5 seed rows [เติม] / role privileges [เติม] / invariant result [เติม] / ปัญหาและ retest [เติม] / สถานะ PENDING

## Task 5 — Deploy App A/B

**Cloud Shell:** ส่ง code พร้อม DB password และ token hashes เท่านั้น ไม่ส่ง plaintext reader/operator tokens ไป App:

```bash
cd "$LAB_DIR"
gcloud compute scp "$TASK_TMP/lab002-code.tgz" secrets/db-password.txt secrets/token-hashes.json \
  lab002-app-a:~/ --zone=asia-southeast1-b --tunnel-through-iap
gcloud compute scp "$TASK_TMP/lab002-code.tgz" secrets/db-password.txt secrets/token-hashes.json \
  lab002-app-b:~/ --zone=asia-southeast1-c --tunnel-through-iap
gcloud compute ssh lab002-app-a --zone=asia-southeast1-b --tunnel-through-iap
```

**ใน App A:**

```bash
hostname
mkdir -p ~/lab002
tar -xzf ~/lab002-code.tgz -C ~/lab002
chmod 600 ~/db-password.txt ~/token-hashes.json
sudo python3 ~/lab002/scripts/configure-app.py \
  --password-file ~/db-password.txt --hash-file ~/token-hashes.json
sudo bash ~/lab002/scripts/install-app.sh
sudo systemctl status lab002-inventory --no-pager
curl --max-time 8 -i http://127.0.0.1:8080/livez
curl --max-time 8 -i http://127.0.0.1:8080/healthz
sudo journalctl -u lab002-inventory -n 30 --no-pager
rm -- ~/db-password.txt ~/token-hashes.json
exit
```

ทำชุด **ใน App A** ซ้ำบน App B หลังเข้า `gcloud compute ssh lab002-app-b --zone=asia-southeast1-c --tunnel-through-iap` ตรวจ hostname ให้ถูกก่อนตั้งค่า

**Expected:** active, /livez=200 และ /healthz=200 ทั้งคู่; DB ไม่พร้อมจะได้ /healthz=503 แต่ /livez ยัง 200 ตรวจ connection source IP/firewall/pg_hba/password/SQL grants ตามลำดับ อย่าพิมพ์ /etc/lab002/app.env ลง log หรือ screenshot

**บันทึก T05:** A service/health [เติม] / B service/health [เติม] / sanitized request IDs และ logs [แนบ] / สถานะ PENDING
