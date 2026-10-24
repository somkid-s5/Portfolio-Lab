---
lab: LAB-011
platform: GCP
phase: guide-ready
guide_status: guide-ready
cloud_verification: not-run
last_verified: null
---
# Lab 11 — ระบบคำนวณราคาเสนอค่าขนส่งบน GKE

**สถานะ:** Guide-ready — CI #315 ผ่านครบ 39/39 jobs รวม app/integration, Terraform fmt/init/validate, manifest contracts, task/evidence/link/shell syntax และ diagram/design checks. CI เป็นการตรวจ repository เท่านั้น. ยังไม่มีการสร้าง Cloud resources โดยผู้เขียน และ Lab นี้ยังไม่ Cloud-verified; Cloud verification: Not run.

## สถานการณ์

ทีม Logistics มี API สำหรับคำนวณราคาเสนอค่าขนส่ง คำขอที่มีจำนวนน้อยทำงานได้ แต่ช่วงแคมเปญมี traffic เพิ่ม ระบบต้องคงความพร้อมให้บริการ ขยายเฉพาะ worker ได้ และไม่เปิด worker หรือกติกาการคิดราคาออกสู่อินเทอร์เน็ต ทีมยังต้อง deploy รุ่นใหม่โดยพิสูจน์ readiness, rollback และการฟื้นตัวเมื่อ Pod หายไป

ผู้เรียนจะสร้าง Quote Engine แบบ stateless ด้วย GKE Autopilot: regional HTTPS Gateway รับคำขอที่ยืนยันตัวตน, API ตรวจ input และเรียก worker ภายใน ClusterIP, worker คำนวณราคาจากกติกา versioned ใน Secret Manager, และ HPA ปรับจำนวน worker ตาม CPU. ข้อมูลทั้งหมดเป็น synthetic; ไม่มี database, customer PII หรือข้อมูลธุรกรรมจริง

## ผู้ใช้และผลลัพธ์

- Client ส่ง quote request ที่มี `weight_kg`, `distance_km` และ `service_level` ผ่าน HTTPS พร้อม bearer token
- `quote-api` ตรวจ authentication/validation และส่งต่อไปยัง `quote-worker` ภายใน cluster
- `quote-worker` โหลด pricing rules จาก Secret Manager ผ่าน Workload Identity Federation for GKE และคืนผลพร้อม `rules_version`
- Operator deploy image ด้วย digest, ตรวจ rollout/HPA/logs, ทดสอบ network boundaries, เปลี่ยน pricing secret และ cleanup ได้

## Requirements และเกณฑ์ยอมรับ

| ID | Requirement | หลักฐานที่ต้องพิสูจน์ |
|---|---|---|
| R1 | HTTPS regional GKE Gateway เปิดเฉพาะ API ที่ต้องใช้ พร้อม bearer-token validation | `Gateway`/`HTTPRoute` พร้อม `curl` success; no/invalid token ถูกปฏิเสธ; worker ไม่มี public route |
| R2 | API แยกจาก worker; worker ใช้ ClusterIP และรับ ingress จาก API เท่านั้น | `Service`/`NetworkPolicy`, `kubectl describe`, และ positive API→worker กับ negative probe→worker |
| R3 | Cluster ใช้ GKE Autopilot regional, VPC-native private nodes, DNS-based control-plane endpoint และ Workload Identity Federation | Terraform plan/config, endpoint config, cluster details และ KSA principal bindings |
| R4 | API กับ worker ใช้ KSA และสิทธิ์ Secret Manager คนละชุด; ไม่มี service-account key file | API อ่านได้เฉพาะ `api-bearer-token`; worker อ่านได้เฉพาะ `quote-rules`; negative IAM probes ถูกปฏิเสธ |
| R5 | Readiness/liveness, startup, resource requests/limits และ rolling-update policy มีค่าชัดเจน | Pod conditions/probes, Deployment rollout และ app health endpoints |
| R6 | Worker มี CPU HPA แบบมีขอบเขตและ CPU requests ที่ใช้คำนวณ utilization ได้ | `kubectl get hpa` แสดง current/desired replicas และเหตุผลจาก `describe`; บันทึกจริง ไม่กำหนดผล scale ไว้ล่วงหน้า |
| R7 | ทดสอบ broken readiness rollout และ Pod failure แล้ว rollback/recover ด้วย runbook | revision/events ก่อน-หลัง, สัดส่วน request ที่สำเร็จ/ผิดพลาด และ recovery evidence |
| R8 | Logs/metrics ใช้ตรวจ error, readiness, CPU และ HPA behavior | Cloud Logging query และ Cloud Monitoring/GKE metrics ที่บันทึกเวลาและช่วงทดสอบ |
| R9 | Change Request ปรับ pricing-rule version และ worker resource profile โดยไม่เสีย readiness | ก่อน/หลัง rule version, rollout/HPA, HTTP errors และค่าใช้จ่ายที่ประมาณใหม่ |
| R10 | Workload/test/cleanup มีเพดานและเริ่มใหม่ได้โดยไม่ลบ resource นอก Lab | task records, state inventory, clean rebuild และ evidence handoff ที่ sanitized |

**Expected เป็นเกณฑ์ตรวจ ไม่ใช่ผล Cloud จริง.** ค่า replica, latency, error rate, scale-up time และค่าใช้จ่ายจริงต้องบันทึกจากการรันของผู้เรียน; ไม่มีตัวเลข performance ที่รับรองล่วงหน้า

## Solution design

![Solution architecture: GKE Quote Engine](assets/solution.svg)

[เปิด diagram แบบ standalone HTML](assets/solution.html) · [ดู SVG source](assets/solution.svg)

### Decisions

- **GKE Autopilot regional:** เน้น lifecycle ของ workload, probes, HPA และ rollout โดยไม่เพิ่ม node-pool management เป็นโจทย์หลัก; การปรับ/ดูแล node OS และ Standard node pools อยู่นอก Lab นี้. ใช้ DNS-based control-plane endpoint และปิด IP-based endpoints; ใน Cloud Shell ใช้ `gcloud container clusters get-credentials --dns-endpoint` แล้วให้ IAM เป็นตัวควบคุมผู้เข้าถึง ไม่ผูกกับ egress IP ที่เปลี่ยนได้. คู่มือจะทดสอบ `kubectl` access ก่อน deploy; หาก endpoint/สิทธิ์องค์กรไม่รองรับ ให้หยุดก่อน apply แทนการเปิด public endpoint หรือ allowlist `0.0.0.0/0`.
- **External regional Gateway:** ใช้ `gke-l7-regional-external-managed`, HTTPRoute และ regional proxy-only subnet; TLS ใน Lab ใช้ self-signed cert อายุสั้นกับ test hostname ผ่าน `curl --resolve --cacert` เพราะไม่มี DNS domain ของผู้เรียน. Production ต้องแทนด้วย certificate ที่เชื่อถือได้และ domain/TLS lifecycle จริง
- **Private worker:** Gateway route ชี้เฉพาะ API; worker รับเฉพาะ API service ผ่าน NetworkPolicy. Ingress policy ต้องอนุญาต health-check/proxy source ranges ที่ Gateway ใช้จริงและ KSA/pod selector ของ API; ให้พิสูจน์ด้วย positive/negative probes
- **Per-workload identity:** ใช้ Workload Identity Federation for GKE และ IAM principal ของแต่ละ KSA โดยตรง ไม่มี key file. API/worker อ่านคนละ Secret Manager secret และโหลดค่าตอนเริ่ม process; การเพิ่ม secret version ต้องมี rollout เพื่อใช้ version ใหม่
- **Bounded horizontal scaling:** worker ใช้ HPA CPU target 60%, min 1/max 4; API เริ่ม 2 replicas เพื่อให้ rollout มี backend พร้อม. ทุก container ระบุ CPU/memory requests และ limits; load tool จะจำกัดจำนวน/concurrency/เวลาตาม design ก่อนเขียน Task
- **Image promotion:** Cloud Build ใช้ dedicated build service account ที่เขียนได้เฉพาะ repository และส่ง log ไป Cloud Logging; build สร้าง image, push ไป Artifact Registry และคู่มือ deploy ด้วย image digest ไม่พึ่ง mutable `latest`. GKE node service account แยกต่างหาก มี role สำหรับ node system tasks และสิทธิ์อ่าน image repository; app KSA ไม่มีสิทธิ์ pull/push image.
- **Observability:** ใช้ structured logs จาก app และ GKE system metrics/Events ใน Cloud Logging/Monitoring; ไม่สร้าง dashboard หรือ alert ที่มีค่าใช้จ่ายเพิ่ม เว้นแต่จะจำเป็นต่อหลักฐาน

### Component และ identity inventory

| Component | หน้าที่ | Identity / trust boundary |
|---|---|---|
| Regional external GKE Gateway + HTTPRoute | TLS termination และ route ไป API เท่านั้น | Public edge; ephemeral lab cert; test ด้วย HTTPS |
| `quote-api` Deployment + Service | bearer auth, validation, quote request handoff | KSA `quote-api`; อ่าน `api-bearer-token`; ไม่มี worker pricing secret |
| `quote-worker` Deployment + ClusterIP | คำนวณราคาและคืน `rules_version` | KSA `quote-worker`; อ่าน `quote-rules`; ไม่มี public Gateway route |
| GKE Autopilot cluster | รัน workload, probes, rollout และ HPA | Private nodes, VPC-native subnet, Dataplane V2; dedicated node service account สำหรับ system tasks/image pull |
| Secret Manager | เก็บ token และ pricing rules แยก secret/version | IAM binding ราย KSA; secret values ไม่อยู่ใน Terraform state |
| Cloud Build + Artifact Registry | build และเก็บ image | Dedicated build service account; Artifact Registry Writer เฉพาะ repository และ Logging Writer; deploy ใช้ immutable digest |
| Cloud Logging + Cloud Monitoring | app/system telemetry | ใช้ managed GKE collection; query ด้วยช่วงเวลาทดลอง |

### Request และ control flow

1. Client ส่ง HTTPS bearer-authenticated request ไป Gateway; Gateway terminate TLS และส่ง HTTP ภายในไป API port 8080.
2. API ตรวจ token/input แล้วเรียก `quote-worker` ผ่าน ClusterIP port 8081; NetworkPolicy ปฏิเสธ ingress จาก Pod อื่นที่ไม่ใช่ API.
3. Worker โหลด pricing rules ผ่าน WIF, คำนวณ quote แบบ bounded และส่งผลพร้อม rules version กลับ API.
4. API ส่งผล quote กลับ Client; structured logs ติด `request_id`, `rules_version`, outcome และ duration แต่ไม่บันทึก token หรือ secret.
5. Cloud Build push image digest ไป Artifact Registry; GKE node identity pull image. Workload identity ของ app ใช้เฉพาะเรียก Secret Manager.
6. GKE ส่ง logs/metrics/events ไป Cloud Operations สำหรับตรวจ rollout, probe, CPU, HPA และ errors.

## Application contract and runtime identity

แอปตัวอย่างอยู่ใน `app/`; เป็น Python HTTP API กับ worker แยก Deployment แต่ใช้ image digest เดียวกัน.

- `GET /` และ `GET /healthz` ใช้ตรวจ health; `POST /v1/quotes` เป็น public API ที่ Gateway route เข้าเท่านั้น.
- Request JSON ต้องมี `weight_kg` ตั้งแต่ 0.1–1,000, `distance_km` ตั้งแต่ 1–5,000 และ `service_level` เป็น `standard` หรือ `express`; body จำกัด 4 KiB.
- API ตรวจ bearer token แบบ constant-time, สร้าง quote ID แล้วเรียก worker ผ่าน ClusterIP. Worker รับ path `/internal/quote`; ไม่มี route จาก Gateway.
- Pricing rules โหลดครั้งเดียวตอน process start จาก Secret Manager; API อ่านเฉพาะ token และ worker อ่านเฉพาะ rules. Worker คืน `rules_version` เพื่อเปรียบเทียบ Change Request. Worker มี synthetic CPU work ต่อคำขอที่ปรับได้ผ่าน `QUOTE_CPU_WORK_MS` (0–100 ms) เพื่อทำให้ HPA scale ได้สังเกตง่าย; ค่านี้เป็น test fixture ไม่ใช่ workload benchmark หรือ capacity claim.
- App logs เป็น JSON มี request ID, outcome, duration และ rule version; ห้ามบันทึก authorization header, token, body หรือ pricing secret. Health endpoints ไม่คืนค่าความลับ.
- `app/sample/quote-rules-v1.json` เป็นข้อมูลสังเคราะห์สำหรับสร้าง Secret Manager version; ไม่มี credential หรือข้อมูลผู้ใช้.

ตัวอย่างคำนวณตาม seed v1 สำหรับ 2 kg, 100 km, standard มี Expected amount 96.00 THB (35 + 2×8 + 100×0.45). นี่เป็นตัวอย่างสูตร ไม่ใช่ผลจากการ deploy บน GCP.

## Operations scenarios ที่จะลงใน Guide

- Baseline quote success, invalid input, invalid token และการทดสอบ worker route ว่าเข้าได้เฉพาะ API
- Sustained bounded load เพื่อสังเกต worker HPA scale-up/down โดยไม่รับประกันว่าทุก run ต้องถึง max replicas
- Broken-readiness rollout: ให้ revision ใหม่ไม่ผ่าน readiness, ยืนยัน ready revision เดิมยังรับ traffic ตาม maxUnavailable policy แล้ว rollback
- ลบ worker Pod ระหว่างโหลดแบบจำกัด: ดู Deployment replacement, request failures/recovery และเหตุการณ์จริง; ไม่อ้าง zero downtime หากไม่ได้วัด
- Secret Manager negative probes ด้วย KSA ที่ไม่มี binding และ positive runtime read ผ่าน worker
- Change Request: publish rules version ใหม่, rollout worker, เปรียบเทียบ `rules_version`, quote output, HPA, resource requests/limits และ readiness
- Cleanup ทุก GCP/Kubernetes resource ที่สร้าง รวม Gateway/IP/proxy subnet/cluster/repository/secrets/temporary certificate และผล load test

## Cost, access และข้อจำกัด

GKE Autopilot regional cluster, regional external Application Load Balancer/Gateway, proxy-only subnet, Cloud Build, Artifact Registry และ secret/API usage มีค่าใช้จ่าย. ก่อน Task ที่สร้าง cluster ต้องใช้ Pricing Calculator กับ region/เวลาที่จะเปิดจริง, ใช้ dedicated project ที่มี billing, ยืนยันสิทธิ์และเวลา cleanup, ตั้ง budget alert (ไม่ใช่ hard spending cap), กำหนด HPA max 4 และจำกัด load tool. ถ้าไม่มี budget หรือสิทธิ์ ให้หยุดก่อน provision; ไม่มีการสร้าง Cloud resources ในขั้น authoring นี้.

Control plane ใช้ DNS-based endpoint และ IAM-authenticated access จาก Cloud Shell; ปิด IP-based endpoint เพื่อลดการพึ่งพา source IP. ผู้เรียนต้องตรวจว่า `container.clusters.get`/`get-credentials` และ Kubernetes RBAC ตรงกับบัญชีที่ใช้ก่อน deploy. Nodes เป็น private; ใช้ Private Google Access สำหรับ Google APIs และไม่เปิด Cloud NAT หาก service dependency ยืนยันว่าไม่ต้องออก public internet. หากตรวจพบ dependency ที่ต้องใช้อินเทอร์เน็ต ให้หยุดและปรับ design/cost review ก่อน.

TLS certificate ที่ self-signed ใช้เฉพาะ lab endpoint และไม่เป็นหลักฐาน production certificate management. bearer token เป็น credential สำหรับ demo ใน dedicated project ไม่ใช่ระบบ customer identity จริง. ระบบไม่มี database, PII, persistent customer state, Cloud Armor, multi-region DR หรือ SLA.

## Evidence handoff ที่จะบันทึกใน Tasks

| หลักฐาน | สิ่งที่ต้องเก็บ |
|---|---|
| Deployment | commit, build ID, image digest, cluster/region (ปกปิด project number ได้) |
| Functional/security | success/invalid-input/invalid-token, worker path denial, secret allow/deny |
| Operations | rollout revisions, pod failure/replacement, logs/events และเวลาที่วัด |
| Scaling/change | HPA current/desired, CPU request/limit, rules version ก่อน/หลัง, errors และ p50/p95 ถ้าวัด |
| Cleanup | Terraform state inventory ก่อน/หลัง, GCP resource inventory, certificate/secret version dispositions |

ทุก Task ด้านล่างมี Expected แยกจากช่องที่ผู้เรียนจะบันทึก Actual, เวลา และ Evidence หลังรันจริง. ห้ามกรอก PASS ล่วงหน้า; CI ที่ตรวจ source/config ไม่ใช่ผล Cloud.


## Tasks

ทำตามลำดับใน Cloud Shell ของโปรเจกต์เฉพาะสำหรับ Lab นี้ ห้ามใช้ production project หรือ project ที่มีข้อมูลจริง. งานตั้งแต่ Task 03 เป็นต้นไปสร้างทรัพยากรที่มีค่าใช้จ่าย. หยุดทันทีหาก project, billing, quota, IAM หรือ estimate ไม่ตรงกับที่ตรวจไว้. สถานะ Expected เป็นเกณฑ์ตรวจ; ช่องผลจริงให้กรอกหลังรันเท่านั้น.

### Task 00 — ยืนยัน project, billing, budget และขอบเขตค่าใช้จ่าย

1. เปิด Google Cloud Console แล้วเลือก project เฉพาะที่ไม่มี workload อื่น.
2. ไปที่ Billing → My projects และตรวจว่า project นี้ linked กับ billing account ที่อนุมัติแล้ว.
3. ไปที่ Billing → Budgets & alerts → Create budget; กำหนดขอบเขตเป็น project นี้และตั้ง email alerts ตามระดับที่ทีมรับได้. Budget alert แจ้งเตือน ไม่ใช่ spending cap.
4. เปิด Google Cloud Pricing Calculator และประเมิน GKE Autopilot แบบ regional, regional external Application Load Balancer/Gateway, Cloud Build, Artifact Registry และ Secret Manager ใน asia-southeast1 ตามเวลาที่จะเปิดจริง. เก็บ estimate ไว้ก่อน Apply; อย่าใช้ตัวเลขคงที่จากคู่มือนี้แทนราคา ณ วันทำ.
5. ตรวจ quota/organization policy และยืนยันว่ามีเวลาเฝ้าดูและ Cleanup ได้ใน session นี้.

**สิ่งที่คาดว่าจะเห็น (Expected):** project ID และ billing account ชัดเจน, budget alert ส่งถึงผู้ดูแล, estimate ครอบคลุมทรัพยากรหลัก และผู้เรียนยอมรับขอบเขตค่าใช้จ่ายแล้ว.

**ผลจริงที่ฉันบันทึก:** project / billing link / estimate วันที่ / budget alert / decision: [กรอกหลังตรวจ]

**หลักฐานที่เก็บ:** estimate URL หรือภาพที่ปกปิดข้อมูลบัญชี, project ID ที่ปกปิดได้, UTC และผู้อนุมัติ. ห้ามแนบข้อมูล billing ที่ไม่ต้องการเปิดเผย.

### Task 01 — เปิด Cloud Shell และเตรียม working copy

ใน Console คลิก Activate Cloud Shell ที่แถบด้านบน. ใช้ Cloud Shell เป็นเครื่องมือทำงานตลอด Lab; ไม่ต้องเปิด laptop. ตรวจตัวตนและ project ก่อน clone branch ที่มี Lab นี้:

**คำสั่ง Bash:**

    set -euo pipefail
    gcloud auth list --filter=status:ACTIVE --format='table(account,status)'
    PROJECT_ID="ใส่-project-id-เฉพาะของ-lab"
    REGION="asia-southeast1"
    gcloud config set project "$PROJECT_ID"
    gcloud projects describe "$PROJECT_ID" --format='value(projectId,projectNumber)'
    git clone --branch docs/gcp-solution-labs https://github.com/somkid-s5/Portfolio-Lab.git
    cd Portfolio-Lab/GCP/LAB-011-gke-quote-engine
    terraform version
    gcloud version
    kubectl version --client
    openssl version
    git status --short

เปิด Cloud Shell Editor จาก Cloud Shell menu แล้วคัดลอกไฟล์ infra/terraform.tfvars.example เป็น infra/terraform.tfvars. แก้ project_id, region และ operator_member ให้ตรงกับบัญชี Google ที่ใช้ทำ Lab. operator_member ใช้รูปแบบ user:email@example.com หรือ serviceAccount:...; ใช้ identity เดียวกับที่รัน Terraform, Cloud Build และ kubectl. ผู้รัน Terraform ต้องมีสิทธิ์จัดการ API, VPC, IAM service accounts, Artifact Registry และ GKE ใน dedicated project; หากใช้นโยบายองค์กรที่จำกัด ให้ผู้ดูแลเป็นผู้ตรวจ/อนุมัติ IAM ก่อนเดินต่อ.

**คำสั่ง Bash:**

    cp infra/terraform.tfvars.example infra/terraform.tfvars
    chmod 600 infra/terraform.tfvars

อย่า commit terraform.tfvars, state, plan, API token หรือ private key.

**สิ่งที่คาดว่าจะเห็น (Expected):** gcloud ชี้ไป project ที่ตั้งใจ, branch เป็น docs/gcp-solution-labs, tools พร้อมใช้ และ terraform.tfvars มีเพียง project ID, region, IAM member กับ allow_destroy=false.

**ผลจริงที่ฉันบันทึก:** project alias ที่ปกปิดได้ / active account type / tool versions / UTC: [กรอกหลังตรวจ]

**หลักฐานที่เก็บ:** output ของ project ID/number ที่ปกปิดได้, git status และ tool versions; ไม่เก็บ access token.

### Task 02 — ตรวจ Terraform และอ่านแผนก่อนสร้าง

Terraform root นี้ใช้ local state ใน Cloud Shell และ Google provider ที่ pin ไว้. คำสั่ง init/validate/plan ยังไม่สร้าง GCP resources. อ่านแผนทั้งหมดก่อน Apply; ถ้ามี resource นอก Lab, plan แสดง destroy/replace ที่ไม่คาดไว้ หรือ project ไม่ตรง ให้หยุด.

**คำสั่ง Bash:**

    set -euo pipefail
    terraform -chdir=infra fmt -check -recursive
    terraform -chdir=infra init -backend=false -input=false
    terraform -chdir=infra validate
    terraform -chdir=infra plan -out=lab11-foundation.tfplan
    terraform -chdir=infra show -no-color lab11-foundation.tfplan

ตรวจว่า plan เปิด API ที่ระบุ, สร้าง dedicated VPC/subnets/secondary ranges/proxy-only subnet, custom node/build service accounts, Artifact Registry, Secret Manager metadata, IAM bindings, regional IP และ GKE Autopilot private cluster. Plan ไม่ควรมี secret payload; ในขั้นนี้ยังไม่มี secret versions.

**สิ่งที่คาดว่าจะเห็น (Expected):** fmt และ validate ผ่าน; plan แสดง create เฉพาะ foundation ของ Lab 11, ไม่มี destroy/replace และไม่มี secret payload. จำนวน resource จริงขึ้นกับ provider/API state จึงไม่กำหนดเลขล่วงหน้า.

**ผลจริงที่ฉันบันทึก:** fmt / init / validate / plan status, planned resource count, warnings และ UTC: [กรอกผลจริง]

**หลักฐานที่เก็บ:** สรุป terraform show ที่ลบ account/project identifiers ตามต้องการ; ห้ามแนบ state file หรือ plan โดยไม่ตรวจข้อมูลภายใน.

### Task 03 — สร้าง Cloud foundation ด้วย Terraform

นี่คือจุดเริ่มมีค่าใช้จ่าย. ใช้เฉพาะ plan ที่อ่านและยืนยันแล้วจาก Task 02. หาก plan เก่าหรือมีการเปลี่ยนตัวแปร ให้สร้างและ review plan ใหม่ก่อน apply.

**คำสั่ง Bash:**

    terraform -chdir=infra apply lab11-foundation.tfplan
    terraform -chdir=infra output
    gcloud compute networks subnets list --project "$PROJECT_ID" --filter='network:lab011-vpc' --format='table(name,region,ipCidrRange,purpose,role)'
    gcloud artifacts repositories describe lab011-images --location "$REGION" --project "$PROJECT_ID" --format='yaml(name,format,location)'
    gcloud container clusters describe lab011-quote-engine --region "$REGION" --project "$PROJECT_ID" --format='yaml(name,autopilot,networkingMode,privateClusterConfig,controlPlaneEndpointsConfig,workloadIdentityConfig,releaseChannel)'

ตรวจ IAM bindings ของ node identity, Artifact Registry Reader, build identity/repository writer และ operator. DNS-based control-plane endpoint เปิดให้เข้าผ่าน Google API; IP-based endpoint ปิด. Node ไม่มี external IP; subnet เปิด Private Google Access เพื่อเรียก Google APIs โดยไม่เพิ่ม Cloud NAT.

**สิ่งที่คาดว่าจะเห็น (Expected):** VPC-native regional Autopilot cluster, private nodes, DNS endpoint, workload identity pool ของ project, regional proxy subnet, repository lab011-images และ regional external IP. การสร้าง cluster อาจใช้เวลาหลายนาที.

**ผลจริงที่ฉันบันทึก:** Terraform apply status / duration / cluster endpoint mode / subnet purpose / repository / gateway IP / UTC: [กรอกผลจริง]

**หลักฐานที่เก็บ:** Terraform output เฉพาะ metadata และผล describe ที่ลบ project number/account details ได้; ห้ามเก็บ terraform.tfstate ใน Git.

### Task 04 — เพิ่ม secret versions โดยไม่ใส่ค่าใน Terraform

Secret objects และ IAM เปล่าถูกสร้างแล้ว แต่ payload ถูกเพิ่มด้วย Secret Manager CLI เพื่อไม่ให้ค่าเข้า Terraform state. สร้าง bearer token แบบสุ่มและเก็บสำเนาไว้ใน home directory ของ Cloud Shell ซึ่งจำกัดสิทธิ์อ่าน. ห้าม echo token หรือวางใน README/issue/log.

**คำสั่ง Bash:**

    set -euo pipefail
    umask 077
    mkdir -p "$HOME/.lab11-tmp"
    chmod 700 "$HOME/.lab11-tmp"
    API_TOKEN=$(openssl rand -hex 32)
    printf '%s' "$API_TOKEN" | gcloud secrets versions add api-bearer-token --project "$PROJECT_ID" --data-file=-
    printf '%s' "$API_TOKEN" > "$HOME/.lab11-api-token"
    chmod 600 "$HOME/.lab11-api-token"
    unset API_TOKEN
    gcloud secrets versions add quote-rules --project "$PROJECT_ID" --data-file=app/sample/quote-rules-v1.json
    gcloud secrets versions list api-bearer-token --project "$PROJECT_ID" --format='table(name,state,createTime)'
    gcloud secrets versions list quote-rules --project "$PROJECT_ID" --format='table(name,state,createTime)'

ตรวจว่าแต่ละ secret มี enabled version. แสดงเฉพาะชื่อ version/state/time; ห้ามใช้คำสั่งอ่าน payload ใน terminal ที่จะบันทึกหรือแชร์ output.

**สิ่งที่คาดว่าจะเห็น (Expected):** API token อยู่ใน Secret Manager และไฟล์ private ของ Cloud Shell เท่านั้น; quote-rules version มี rules_version v1; payload ไม่ปรากฏใน command output.

**ผลจริงที่ฉันบันทึก:** secret version IDs/state และ UTC โดยไม่บันทึกค่า: [กรอกผลจริง]

**หลักฐานที่เก็บ:** ตาราง version metadata และรายการไฟล์ private ที่สร้าง; ไม่แนบ token หรือ JSON payload ที่มี secret.

### Task 05 — Build และยืนยัน image digest ด้วย Cloud Build

Build ใช้ service account quote-build; สิทธิ์เขียน Artifact Registry จำกัดระดับ repository และส่ง log ไป Cloud Logging. ผู้ใช้ที่ส่ง build ต้องมี Cloud Build permission และ Service Account User บน build identity. Build นี้ push image ไปยัง repository ของ Lab 11 จึงมีค่าเก็บ image; ไม่ใช้ tag เปลี่ยนแปลงได้ใน deployment.

**คำสั่ง Bash:**

    set -euo pipefail
    IMAGE_REPOSITORY=$(terraform -chdir=infra output -raw image_repository)
    REVISION=$(git rev-parse --short HEAD)
    BUILD_ID=$(gcloud builds submit . --config=cloudbuild.yaml --region="$REGION" --project="$PROJECT_ID" --substitutions="_IMAGE=$IMAGE_REPOSITORY,_REVISION=$REVISION" --async --format='value(id)')
    test -n "$BUILD_ID"
    printf 'BUILD_ID=%s\n' "$BUILD_ID"
    gcloud builds log "$BUILD_ID" --region="$REGION" --project="$PROJECT_ID" --stream
    gcloud builds describe "$BUILD_ID" --region="$REGION" --project="$PROJECT_ID" --format='yaml(status,results.images)'

หลัง Build เสร็จ สร้าง immutable image URI จากผลจริง:

**คำสั่ง Bash:**

    set -euo pipefail
    IMAGE_URI=$(gcloud builds describe "$BUILD_ID" --region="$REGION" --project="$PROJECT_ID" --format=json | jq -r '"\(.results.images[0].name)@\(.results.images[0].digest)"')
    [[ "$IMAGE_URI" =~ @sha256:[a-f0-9]{64}$ ]]
    printf 'IMAGE_URI=%s\n' "$IMAGE_URI"

ถ้าใช้คนละ Cloud Shell session ให้กำหนด BUILD_ID จาก build ที่บันทึกไว้ก่อนรันคำสั่งดึง digest. หาก build เป็น FAILURE ให้เปิด Cloud Build → History → เลือก build ID → Logs; ตรวจ service account, API permission, Docker context และ Artifact Registry role ก่อน retry.

**สิ่งที่คาดว่าจะเห็น (Expected):** build status SUCCESS และผล image มี sha256 digest ที่ตรงกับ repository นี้; GitHub CI ไม่ได้ push image.

**ผลจริงที่ฉันบันทึก:** build ID / status / image digest / duration / UTC: [กรอกผลจริง]

**หลักฐานที่เก็บ:** build URL, commit ที่ใช้ build และ image URI แบบ digest; ไม่แนบ build logs ที่เผลอมี credential.

### Task 06 — เชื่อม Cloud Shell เข้าคลัสเตอร์ด้วย DNS endpoint

ตรวจ active account อีกครั้ง. ใช้ DNS endpoint ตามที่ตั้งใจ; ห้ามเปิด IP endpoint หรือเพิ่ม authorized network เป็น 0.0.0.0/0 เพื่อแก้ปัญหา.

**คำสั่ง Bash:**

    set -euo pipefail
    gcloud container clusters get-credentials lab011-quote-engine --region "$REGION" --project "$PROJECT_ID" --dns-endpoint
    kubectl config current-context
    kubectl get namespaces
    kubectl get gatewayclass gke-l7-regional-external-managed
    kubectl auth can-i create deployments --namespace=default

ถ้า get-credentials แจ้ง IAM denied ให้ตรวจ roles/container.developer, container.clusters.connect, container.clusters.get และให้เวลา IAM propagation. ถ้าองค์กรบล็อก DNS endpoint ให้หยุดและขอผู้ดูแลปรับ access policy; อย่า fallback ไปเปิด endpoint ที่ปิดไว้.

**สิ่งที่คาดว่าจะเห็น (Expected):** context เป็น cluster lab011-quote-engine และ Kubernetes API ตอบ namespace/GatewayClass ได้. คลัสเตอร์อาจยังไม่มี application nodes จนกว่าจะมี workload.

**ผลจริงที่ฉันบันทึก:** context alias / get-credentials / kubectl read / authorization check / UTC: [กรอกผลจริง]

**หลักฐานที่เก็บ:** output ที่ปกปิด project number และ context server hostname ได้; อย่าเก็บ kubeconfig credential.

### Task 07 — สร้าง TLS certificate ชั่วคราวและ Kubernetes Secret

Lab ใช้ hostname ทดสอบ quote.lab.test และ self-signed certificate อายุ 3 วัน. ใบรับรองนี้ใช้ทดสอบ TLS เท่านั้น ไม่ใช่ production certificate. สร้างไฟล์ใน home directory ที่ permission 700 ไม่ใช่ใน repository.

**คำสั่ง Bash:**

    set -euo pipefail
    openssl req -x509 -newkey rsa:2048 -sha256 -nodes -days 3 \
      -keyout "$HOME/.lab11-tmp/tls.key" \
      -out "$HOME/.lab11-tmp/tls.crt" \
      -subj "/CN=quote.lab.test" \
      -addext "subjectAltName=DNS:quote.lab.test"
    chmod 600 "$HOME/.lab11-tmp/tls.key" "$HOME/.lab11-tmp/tls.crt"
    kubectl create namespace quote-platform --dry-run=client -o yaml | kubectl apply -f -
    kubectl create secret tls quote-gateway-tls --namespace=quote-platform \
      --cert="$HOME/.lab11-tmp/tls.crt" --key="$HOME/.lab11-tmp/tls.key" \
      --dry-run=client -o yaml | kubectl apply -f -

ตรวจ cert metadata โดยไม่แสดง private key:

**คำสั่ง Bash:**

    openssl x509 -in "$HOME/.lab11-tmp/tls.crt" -noout -subject -dates -ext subjectAltName
    kubectl get secret quote-gateway-tls -n quote-platform -o jsonpath='{.type}{"\n"}'

**สิ่งที่คาดว่าจะเห็น (Expected):** certificate SAN มี DNS:quote.lab.test, TLS secret type เป็น kubernetes.io/tls, และ key/cert อยู่ใน private home directory เท่านั้น.

**ผลจริงที่ฉันบันทึก:** cert expiry / SAN / secret type / UTC: [กรอกผลจริง]

**หลักฐานที่เก็บ:** certificate public metadata และชื่อ secret; ห้ามแนบ tls.key หรือ Secret YAML data.

### Task 08 — Deploy API, private worker และ Gateway

ดึง digest จาก build ID และ render manifest โดยแทนเฉพาะ image/project placeholders. ตรวจว่า image string มี digest ก่อน apply; manifest ที่เก็บใน Git ยังคงเป็น template และไม่มี credential.

**คำสั่ง Bash:**

    set -euo pipefail
    IMAGE_URI=$(gcloud builds describe "$BUILD_ID" --region="$REGION" --project="$PROJECT_ID" --format=json | jq -r '"\(.results.images[0].name)@\(.results.images[0].digest)"')
    [[ "$IMAGE_URI" =~ @sha256:[a-f0-9]{64}$ ]]
    sed -e "s|__QUOTE_ENGINE_IMAGE__|$IMAGE_URI|g" \
        -e "s|__PROJECT_ID__|$PROJECT_ID|g" \
        manifests/quote-platform.yaml | kubectl apply -f -

ตรวจว่า apply สร้าง API/worker KSA, Deployments, ClusterIP Services, HPA, NetworkPolicies, PDB, Gateway และ HTTPRoute. อย่าใช้คำสั่งอ่าน Kubernetes Secret แบบเต็มหรือ commit rendered manifest ที่อาจมี secret เพิ่มภายหลัง.

**สิ่งที่คาดว่าจะเห็น (Expected):** ทุก resource ถูกสร้าง/คงอยู่; worker service เป็น ClusterIP; ทั้งสอง Deployment อ้าง image @sha256; Gateway อ้าง secret quote-gateway-tls และชื่อ static address lab011-gateway-ip.

**ผลจริงที่ฉันบันทึก:** apply output / image digest / จำนวน resource / UTC: [กรอกผลจริง]

**หลักฐานที่เก็บ:** rendered manifest ที่ตรวจแล้วและลบ project ID ได้, รายการ deploy/service/HPA/network policy/Gateway/route; ห้ามเก็บ Secret data.

### Task 09 — รอ rollout และ regional HTTPS Gateway พร้อม

การสร้าง Gateway สร้าง regional external load balancer และมีค่าใช้จ่ายเพิ่ม. รอ condition แทนการสมมติว่า resource พร้อมทันที.

**คำสั่ง Bash:**

    set -euo pipefail
    kubectl rollout status deployment/quote-api -n quote-platform --timeout=10m
    kubectl rollout status deployment/quote-worker -n quote-platform --timeout=10m
    kubectl wait --for=condition=Ready gateway/quote-gateway -n quote-platform --timeout=15m
    kubectl wait --for=condition=Accepted httproute/quote-route -n quote-platform --timeout=10m
    kubectl get pods,svc,hpa,networkpolicy,pdb -n quote-platform -o wide
    kubectl get gateway,httproute -n quote-platform
    GATEWAY_IP=$(kubectl get gateway quote-gateway -n quote-platform -o=jsonpath='{.status.addresses[0].value}')
    test -n "$GATEWAY_IP"
    printf 'GATEWAY_IP=%s\n' "$GATEWAY_IP"

Gateway Ready/HTTPRoute Accepted ต้องเป็น True และ Gateway มี address. ถ้าไม่พร้อม ให้ใช้ describe gateway/route และดู Kubernetes events; ตรวจ proxy-only subnet purpose/region, certificate reference, route parent, image digest, API readiness และ firewall events. อย่าลบ finalizer ด้วยมือ.

**สิ่งที่คาดว่าจะเห็น (Expected):** API 2/2 พร้อม, worker อย่างน้อย 1/1 พร้อม, HPA มี target CPU, Gateway Ready และ route Accepted; IP เป็น regional external address.

**ผลจริงที่ฉันบันทึก:** rollout durations / pod readiness / HPA current / Gateway condition / IP alias / UTC: [กรอกผลจริง]

**หลักฐานที่เก็บ:** status/describe ของ gateway และ route, pod/deployment summary, events ที่ลบ project identifiers; ไม่ใช้ภาพ console ที่ไม่ได้ถ่ายจาก run จริง.

### Task 10 — พิสูจน์ API contract, authentication และผลคำนวณ

ใช้ hostname ที่อยู่ใน certificate แต่ชี้ไปยัง regional Gateway IP โดยตรง. คำขอหนึ่งครั้งต้องผ่าน HTTPS → API → worker และตอบ rules_version จาก Secret Manager.

**คำสั่ง Bash:**

    set -euo pipefail
    set +x
    GATEWAY_IP=$(kubectl get gateway quote-gateway -n quote-platform -o=jsonpath='{.status.addresses[0].value}')
    API_TOKEN=$(<"$HOME/.lab11-api-token")
    test -n "$API_TOKEN"
    RESPONSE=$(curl --silent --show-error --fail-with-body --resolve "quote.lab.test:443:$GATEWAY_IP" --cacert "$HOME/.lab11-tmp/tls.crt" --header "Authorization: Bearer $API_TOKEN" --header 'Content-Type: application/json' --data '{"weight_kg":2,"distance_km":100,"service_level":"standard"}' https://quote.lab.test/v1/quotes)
    printf '%s\n' "$RESPONSE" | jq .
    printf '%s\n' "$RESPONSE" | jq -e '.amount_thb == 96 and .currency == "THB" and .estimated_days == 3 and .rules_version == "v1" and (.quote_id | length > 0)'
    UNAUTH_CODE=$(curl --silent --show-error --output /dev/null --write-out '%{http_code}' --resolve "quote.lab.test:443:$GATEWAY_IP" --cacert "$HOME/.lab11-tmp/tls.crt" --header 'Authorization: Bearer deliberately-invalid' --header 'Content-Type: application/json' --data '{"weight_kg":2,"distance_km":100,"service_level":"standard"}' https://quote.lab.test/v1/quotes)
    INVALID_CODE=$(curl --silent --show-error --output /dev/null --write-out '%{http_code}' --resolve "quote.lab.test:443:$GATEWAY_IP" --cacert "$HOME/.lab11-tmp/tls.crt" --header "Authorization: Bearer $API_TOKEN" --header 'Content-Type: application/json' --data '{}' https://quote.lab.test/v1/quotes)
    unset API_TOKEN
    test "$UNAUTH_CODE" = 401
    test "$INVALID_CODE" = 400
    printf 'invalid-token=%s invalid-payload=%s\n' "$UNAUTH_CODE" "$INVALID_CODE"

ถ้าคำขอสำเร็จ ค่าตัวอย่างจาก rules v1 คำนวณเป็น 35 + (2 × 8) + (100 × 0.45) = 96 THB. หาก TLS ล้มเหลว ให้ตรวจ SAN, วันหมดอายุ, CA file, IP และ hostname; หากได้ 503 ให้ตรวจ API log, worker endpoints, NetworkPolicy และ Secret access. ห้ามเปิด `curl -v` เพราะอาจแสดง Authorization header.

**สิ่งที่คาดว่าจะเห็น (Expected):** success เป็น HTTP 200 พร้อม quote_id, 96 THB และ v1; token ผิดเป็น 401; JSON ที่ไม่ผ่าน validation เป็น 400. ค่านี้เป็นผลคำนวณจาก sample rules ไม่ใช่ผล Cloud ที่ผู้เขียนทดสอบ.

**ผลจริงที่ฉันบันทึก:** status codes / amount / currency / rules version / request timestamp UTC / observed error: [กรอกผลจริง]

**หลักฐานที่เก็บ:** response success ที่ไม่มี token, status codes ของ negative tests และ request ID ที่ sanitize แล้ว; ห้ามบันทึก Authorization header.

### Task 11 — ตรวจขอบเขต NetworkPolicy ของ worker

Task 10 เป็น positive path จาก API ไป worker. ตอนนี้ใช้ Pod ที่ไม่มี label/API identity เพื่อพิสูจน์ว่า workload อื่นใน namespace ไม่สามารถเรียก worker ได้. Probe ตรวจ DNS ก่อน แล้วรายงาน timeout ว่า denied; DNS failure จะเป็น inconclusive ไม่ใช่ PASS.

**คำสั่ง Bash:**

    set -euo pipefail
    sed "s|__QUOTE_ENGINE_IMAGE__|$IMAGE_URI|g" manifests/worker-boundary-probe.yaml | kubectl apply -f -
    kubectl wait --for=jsonpath='{.status.phase}'=Succeeded pod/worker-boundary-probe -n quote-platform --timeout=60s
    PROBE_OUTPUT=$(kubectl logs pod/worker-boundary-probe -n quote-platform)
    printf '%s\n' "$PROBE_OUTPUT"
    grep -q '^NETWORK_DENIED ' <<<"$PROBE_OUTPUT"
    kubectl delete pod worker-boundary-probe -n quote-platform --wait=true
    kubectl describe networkpolicy quote-worker-ingress -n quote-platform

หาก Pod จบด้วย exit 3 ให้ตรวจ DNS/service endpoint และสถานะ policy ก่อนรันใหม่. หาก exit 4 หรือเห็น NETWORK_ALLOWED ให้หยุด: ตรวจ selector ของ policy, labels ของ probe/API/worker และ CNI enforcement; อย่าบันทึกผลเป็นผ่าน. การทดสอบนี้เป็น probe จำกัดเวลา ไม่ใช่การสแกนเครือข่าย.

**สิ่งที่คาดว่าจะเห็น (Expected):** probe resolve ชื่อ service ได้แต่เชื่อมต่อ worker ไม่สำเร็จภายใน timeout และแสดง NETWORK_DENIED; API ที่เลือก label ถูกต้องยังคำนวณราคาได้.

**ผลจริงที่ฉันบันทึก:** probe exit / output class / API positive request status / policy selector / UTC: [กรอกผลจริง]

**หลักฐานที่เก็บ:** probe log ที่ไม่มี credentials, describe policy และ result ของ positive path จาก Task 10.

### Task 12 — พิสูจน์ Workload Identity และสิทธิ์ Secret แบบแยก workload

ทดสอบผ่าน process ใน Pod เพื่อใช้ identity จริงของแต่ละ Kubernetes ServiceAccount. คำสั่ง check-secret แสดงเพียง allowed/denied และไม่พิมพ์ payload.

**คำสั่ง Bash:**

    set -euo pipefail
    kubectl exec deployment/quote-api -n quote-platform -- python -m quote_engine check-secret --secret-id api-bearer-token
    kubectl exec deployment/quote-worker -n quote-platform -- python -m quote_engine check-secret --secret-id quote-rules
    set +e
    API_DENIED=$(kubectl exec deployment/quote-api -n quote-platform -- python -m quote_engine check-secret --secret-id quote-rules 2>&1)
    API_DENIED_STATUS=$?
    set -e
    printf '%s\n' "$API_DENIED"
    test "$API_DENIED_STATUS" -eq 3
    grep -q '^ACCESS_DENIED ' <<<"$API_DENIED"
    set +e
    WORKER_DENIED=$(kubectl exec deployment/quote-worker -n quote-platform -- python -m quote_engine check-secret --secret-id api-bearer-token 2>&1)
    WORKER_DENIED_STATUS=$?
    set -e
    printf '%s\n' "$WORKER_DENIED"
    test "$WORKER_DENIED_STATUS" -eq 3
    grep -q '^ACCESS_DENIED ' <<<"$WORKER_DENIED"

ถ้าคำสั่งล้มด้วย permission error ที่ไม่ใช่ AccessDenied ให้ตรวจ Workload Identity pool, principal URI, KSA name/namespace, IAM binding และการเปิด IAM Credentials/STS APIs. ห้ามเพิ่มสิทธิ์ระดับ project เพื่อให้ test ผ่าน; grant ต้องจำกัดที่ Secret ของ workload นั้น.

**สิ่งที่คาดว่าจะเห็น (Expected):** API อ่านเฉพาะ api-bearer-token; worker อ่านเฉพาะ quote-rules; การอ่าน secret ข้ามหน้าที่ถูกปฏิเสธโดย Secret Manager.

**ผลจริงที่ฉันบันทึก:** API allow/deny / worker allow/deny / error class / UTC: [กรอกผลจริง]

**หลักฐานที่เก็บ:** บรรทัด ACCESS_ALLOWED payload=not-printed และ ACCESS_DENIED error_type=..., KSA names และ sanitized IAM binding; ไม่เก็บ secret payload หรือ access token.

### Task 13 — ตรวจ logs, HPA metrics และเหตุการณ์ของระบบ

ส่งคำขอ quote สำเร็จจาก Task 10 แล้วใช้ request window เดียวกันตรวจ application logs, resource metrics และ events. อย่าสรุป latency หรือความพร้อมใช้งานจากตัวอย่างไม่กี่คำขอ.

**คำสั่ง Bash:**

    set -euo pipefail
    kubectl top pods -n quote-platform
    kubectl get hpa quote-worker -n quote-platform -o wide
    kubectl describe hpa quote-worker -n quote-platform
    kubectl get events -n quote-platform --sort-by=.lastTimestamp | tail -n 30
    gcloud logging read 'resource.type="k8s_container" AND resource.labels.namespace_name="quote-platform" AND jsonPayload.event="quote_completed"' --project "$PROJECT_ID" --freshness=1h --limit=20 --format='table(timestamp,jsonPayload.request_id,jsonPayload.rules_version,jsonPayload.duration_ms,jsonPayload.outcome)'
    gcloud logging read 'resource.type="k8s_container" AND resource.labels.namespace_name="quote-platform" AND jsonPayload.event="worker_quote_computed"' --project "$PROJECT_ID" --freshness=1h --limit=20 --format='table(timestamp,jsonPayload.request_id,jsonPayload.rules_version,jsonPayload.duration_ms,jsonPayload.outcome)'

เทียบ API request_id กับ worker log เพื่อยืนยัน flow; เก็บ HPA current/desired และ CPU ณ เวลาที่วัด. หาก kubectl top แจ้ง metrics unavailable ให้รอ pipeline, ตรวจ Pod readiness และ Events แล้วลองอีกครั้ง; ห้ามตีความค่าว่างเป็น CPU 0. หาก Logging query ไม่คืนผล ให้ตรวจ namespace/resource labels และรูปแบบ parsed JSON ใน Logs Explorer.

**สิ่งที่คาดว่าจะเห็น (Expected):** structured events แยก API/worker, `rules_version=v1`, HPA target CPU 60% และข้อมูล current utilization เมื่อ metrics pipeline พร้อม. ไม่มีการกำหนดค่าการใช้ CPU หรือ HPA scale ล่วงหน้า.

**ผลจริงที่ฉันบันทึก:** request IDs ที่ปกปิดแล้ว / log count / HPA target-current-desired / CPU / event ที่เกี่ยวข้อง / UTC: [กรอกผลจริง]

**หลักฐานที่เก็บ:** query/filter, log rows ที่ sanitize แล้ว, HPA describe และ Events; ตัด project/account identifiers ที่ไม่ต้องเปิดเผย.

### Task 14 — ทำ bounded load observation โดยไม่สร้าง benchmark claim

รัน load tool ที่จำกัดไม่เกิน 60 วินาที, 4 concurrent requests และ 1,200 requests. เริ่มจาก default เหล่านี้; อย่าขยายเพดานเพื่อไล่ตัวเลข throughput. ค่า latency ที่ได้เป็น observation ของ run นี้เท่านั้น ไม่ใช่ SLA หรือผล benchmark ทั่วไป.

**คำสั่ง Bash:**

    set -euo pipefail
    set +x
    export API_TOKEN="$(<"$HOME/.lab11-api-token")"
    python3 scripts/load_test.py --url https://quote.lab.test/v1/quotes --resolve-ip "$GATEWAY_IP" --ca-file "$HOME/.lab11-tmp/tls.crt" --duration-seconds 60 --concurrency 4 --max-requests 1200 --timeout-seconds 4
    unset API_TOKEN
    kubectl get hpa quote-worker -n quote-platform -o wide
    kubectl get deployment quote-worker -n quote-platform

บันทึกจำนวน submitted/completed, status codes, network failures, p50/p95 และช่วงเวลา. ถ้ามี 5xx หรือ failures ให้หยุด load, ตรวจ Gateway/API/worker logs, HPA, CPU และ readiness ก่อน retry; ห้าม retry อัตโนมัติแบบไม่จำกัด. ถ้า tool จบก่อนครบ duration เพราะถึง max_requests ให้บันทึกจำนวนจริง.

**สิ่งที่คาดว่าจะเห็น (Expected):** JSON summary ของจำนวนคำขอ/status/latency และข้อมูล HPA; อาจไม่มีการ scale หาก CPU ต่ำกว่า target หรือ run สั้นเกิน. ความสำเร็จคือเก็บ observation พร้อมบริบท ไม่ใช่ต้องมี replica เพิ่ม.

**ผลจริงที่ฉันบันทึก:** duration / submitted / completed / status counts / failures / p50 / p95 / HPA before-after / UTC: [กรอกค่าที่ tool คืนจริง]

**หลักฐานที่เก็บ:** summary output, HPA snapshots และ log/event window; ไม่บันทึก token. อย่าเรียกผลนี้ว่า production load test.
### Task 15 — จำลอง readiness regression และ rollback รุ่น API

จำลอง change ที่ทำให้ readiness endpoint ผิด โดยแก้เฉพาะ Pod template ชั่วคราว. RollingUpdate ตั้ง maxUnavailable=0 จึงควรรักษา API รุ่นเดิมไว้ระหว่าง Pod ใหม่ไม่ Ready. Task นี้ตั้งใจทำให้ rollout ไม่สำเร็จ แล้ว rollback ทันที.

**คำสั่ง Bash:**

    set -euo pipefail
    kubectl rollout history deployment/quote-api -n quote-platform
    kubectl patch deployment quote-api -n quote-platform --type='json' -p='[{"op":"replace","path":"/spec/template/spec/containers/0/readinessProbe/httpGet/path","value":"/lab-intentional-failure"}]'
    set +e
    kubectl rollout status deployment/quote-api -n quote-platform --timeout=180s
    ROLLOUT_STATUS=$?
    set -e
    test "$ROLLOUT_STATUS" -ne 0
    kubectl get deployment,replicaset,pods -n quote-platform -l app=quote-api -o wide
    READY_REPLICAS=$(kubectl get deployment quote-api -n quote-platform -o=jsonpath='{.status.readyReplicas}')
    test "$READY_REPLICAS" = 2
    kubectl get events -n quote-platform --sort-by=.lastTimestamp | tail -n 30
    kubectl rollout undo deployment/quote-api -n quote-platform
    kubectl rollout status deployment/quote-api -n quote-platform --timeout=10m
    kubectl get deployment quote-api -n quote-platform -o wide

Expected failure ต้องมาจาก Pod readiness probe ของ revision ใหม่ ไม่ใช่ permission/quota/scheduling error. ถ้า Pod ใหม่ไม่ถูกสร้างหรือ rollout error เป็นชนิดอื่น ให้เก็บเหตุผลและหยุด ไม่สรุปว่าได้พิสูจน์ readiness regression. หลัง undo ให้ตรวจว่า probe path กลับเป็น /readyz และ API ตอบ 200 อีกครั้งก่อนทำต่อ.

**สิ่งที่คาดว่าจะเห็น (Expected):** revision ใหม่มี Pod ที่ readiness ไม่ผ่าน ขณะที่ API รุ่นก่อนยัง Ready 2 replicas; `rollout status` timeout/nonzero; `rollout undo` คืน deployment ให้ Ready.

**ผลจริงที่ฉันบันทึก:** revision ก่อน/ผิดพลาด/หลัง rollback / ready replicas / probe event / rollback duration / UTC: [กรอกผลจริง]

**หลักฐานที่เก็บ:** rollout history, pod readiness/events ก่อน rollback และ deployment status หลัง rollback; ปกปิด project identifiers.

### Task 16 — จำลอง Pod หายและตรวจการสร้างทดแทน

จำลอง worker process/Pod หายหนึ่งตัวโดยลบ Pod ที่เลือกเพียงตัวเดียว. Deployment/ReplicaSet ควรสร้าง Pod ทดแทน; ถ้า HPA ขยายอยู่ ให้คงจำนวน replica ตาม HPA และอย่าลบ Pod หลายตัวพร้อมกัน.

**คำสั่ง Bash:**

    set -euo pipefail
    BEFORE_PODS=$(kubectl get pods -n quote-platform -l app=quote-worker -o jsonpath='{range .items[*]}{.metadata.name}{" "}{end}')
    WORKER_POD=$(kubectl get pods -n quote-platform -l app=quote-worker -o jsonpath='{.items[0].metadata.name}')
    test -n "$WORKER_POD"
    printf 'ก่อนทดสอบ worker pods: %s\nเลือก Pod: %s\n' "$BEFORE_PODS" "$WORKER_POD"
    kubectl delete pod "$WORKER_POD" -n quote-platform --wait=false
    kubectl rollout status deployment/quote-worker -n quote-platform --timeout=10m
    kubectl get pods -n quote-platform -l app=quote-worker -o wide
    kubectl get deployment quote-worker -n quote-platform -o wide
    API_TOKEN=$(<"$HOME/.lab11-api-token")
    curl --silent --show-error --fail --resolve "quote.lab.test:443:$GATEWAY_IP" --cacert "$HOME/.lab11-tmp/tls.crt" --header "Authorization: Bearer $API_TOKEN" --header 'Content-Type: application/json' --data '{"weight_kg":2,"distance_km":100,"service_level":"standard"}' https://quote.lab.test/v1/quotes | jq -e '.amount_thb == 96'
    unset API_TOKEN

หาก replacement Pod ไม่ Ready ให้ตรวจ ReplicaSet events, image pull, Secret access, resource requests และ HPA. การลบ Pod โดยตรงเป็นการจำลอง process loss; อย่าสรุปว่า PDB กันการลบด้วย kubectl delete ได้ เพราะ PDB ใช้กับ eviction API และไม่ใช่ตัวป้องกันการลบทุกแบบ.

**สิ่งที่คาดว่าจะเห็น (Expected):** มี Pod ชื่อใหม่เข้ามาแทนจำนวน desired replica และ API กลับตอบ quote v1 ได้; บันทึก downtime หรือ error ที่สังเกตได้จริง.

**ผลจริงที่ฉันบันทึก:** Pod ที่ลบ / Pod replacement / ready time / API status / errors / UTC: [กรอกผลจริง]

**หลักฐานที่เก็บ:** Pod/deployment snapshots ก่อน-หลัง, events และ API response ที่ไม่รวม token.

### Task 17 — รับ Change Request: ปรับราคาและ worker profile

คำขอจากทีมธุรกิจคือปรับราคาเป็น rules v2 และเพิ่ม CPU budget ของ worker เพื่อรองรับการคำนวณช่วง campaign. เพิ่ม secret version จาก sample file แล้ว restart worker เพื่ออ่าน `latest`; ปรับ CPU request เป็น 150m และ deterministic CPU work เป็น 30 ms. ทั้งหมดเป็น change ของ Lab นี้ ไม่ใช่ราคาให้บริการจริง.

**คำสั่ง Bash:**

    set -euo pipefail
    gcloud secrets versions add quote-rules --project "$PROJECT_ID" --data-file=app/sample/quote-rules-v2.json
    gcloud secrets versions list quote-rules --project "$PROJECT_ID" --format='table(name,state,createTime)'
    kubectl set env deployment/quote-worker -n quote-platform QUOTE_CPU_WORK_MS=30
    kubectl patch deployment quote-worker -n quote-platform --type='strategic' -p='{"spec":{"template":{"spec":{"containers":[{"name":"worker","resources":{"requests":{"cpu":"150m","memory":"128Mi"},"limits":{"cpu":"500m","memory":"256Mi"}}}]}}}}'
    kubectl rollout status deployment/quote-worker -n quote-platform --timeout=10m
    kubectl get deployment,pods -n quote-platform -l app=quote-worker -o wide
    API_TOKEN=$(<"$HOME/.lab11-api-token")
    RESPONSE=$(curl --silent --show-error --fail --resolve "quote.lab.test:443:$GATEWAY_IP" --cacert "$HOME/.lab11-tmp/tls.crt" --header "Authorization: Bearer $API_TOKEN" --header 'Content-Type: application/json' --data '{"weight_kg":2,"distance_km":100,"service_level":"standard"}' https://quote.lab.test/v1/quotes)
    unset API_TOKEN
    printf '%s\n' "$RESPONSE" | jq -e '.amount_thb == 108 and .rules_version == "v2"'
    kubectl get hpa quote-worker -n quote-platform -o wide
    kubectl describe hpa quote-worker -n quote-platform

ถ้าผลยังเป็น v1 ให้ยืนยันว่า secret version v2 เป็น ENABLED, worker rollout เสร็จ และ Pod ใหม่ใช้ identity/Secret Manager ได้; อย่า restart API เพราะ API ไม่ได้โหลด pricing rules. HPA utilization เปลี่ยนตาม CPU request ใหม่ จึงต้องบันทึก target/current/desired และสังเกตจากข้อมูลจริง.

**สิ่งที่คาดว่าจะเห็น (Expected):** quote request เดิมคำนวณเป็น 108 THB และตอบ rules_version=v2; worker rollout ใช้ request 150m/limit 500m และ CPU work 30 ms; HPA อาจ scale หรือไม่ scale ตาม workload.

**ผลจริงที่ฉันบันทึก:** secret version ID / rules version / amount / CPU request-limit / CPU work / HPA before-after / rollout duration / UTC: [กรอกผลจริง]

**หลักฐานที่เก็บ:** sanitized response, secret version metadata, rollout/HPA snapshots และ change note ที่ระบุเหตุผล/ผู้อนุมัติ; ไม่แนบ payload ที่เป็น secret.

### Task 18 — หมุน API token และยกเลิก version เก่า

สร้าง token ใหม่โดยไม่พิมพ์ค่า เพิ่มเป็น Secret Manager version ล่าสุด แล้ว restart API ให้ทั้งสอง replica อ่านค่าใหม่. ทดสอบ token ใหม่ผ่านและ token เดิมถูกปฏิเสธก่อน disable secret version เก่า.

**คำสั่ง Bash:**

    set -euo pipefail
    set +x
    OLD_VERSION=$(gcloud secrets versions list api-bearer-token --project "$PROJECT_ID" --filter='state=ENABLED' --sort-by='~createTime' --format='value(name)' | head -n 1 | sed 's|.*/||')
    test -n "$OLD_VERSION"
    NEW_TOKEN=$(openssl rand -hex 32)
    printf '%s' "$NEW_TOKEN" | gcloud secrets versions add api-bearer-token --project "$PROJECT_ID" --data-file=-
    printf '%s' "$NEW_TOKEN" > "$HOME/.lab11-api-token-v2"
    chmod 600 "$HOME/.lab11-api-token-v2"
    unset NEW_TOKEN
    kubectl rollout restart deployment/quote-api -n quote-platform
    kubectl rollout status deployment/quote-api -n quote-platform --timeout=10m
    OLD_TOKEN=$(<"$HOME/.lab11-api-token")
    NEW_TOKEN=$(<"$HOME/.lab11-api-token-v2")
    OLD_CODE=$(curl --silent --show-error --output /dev/null --write-out '%{http_code}' --resolve "quote.lab.test:443:$GATEWAY_IP" --cacert "$HOME/.lab11-tmp/tls.crt" --header "Authorization: Bearer $OLD_TOKEN" --header 'Content-Type: application/json' --data '{"weight_kg":2,"distance_km":100,"service_level":"standard"}' https://quote.lab.test/v1/quotes)
    NEW_CODE=$(curl --silent --show-error --output /dev/null --write-out '%{http_code}' --resolve "quote.lab.test:443:$GATEWAY_IP" --cacert "$HOME/.lab11-tmp/tls.crt" --header "Authorization: Bearer $NEW_TOKEN" --header 'Content-Type: application/json' --data '{"weight_kg":2,"distance_km":100,"service_level":"standard"}' https://quote.lab.test/v1/quotes)
    unset OLD_TOKEN NEW_TOKEN
    printf 'old-token=%s new-token=%s\n' "$OLD_CODE" "$NEW_CODE"
    test "$OLD_CODE" = 401
    test "$NEW_CODE" = 200
    gcloud secrets versions disable "$OLD_VERSION" --secret=api-bearer-token --project "$PROJECT_ID"
    gcloud secrets versions list api-bearer-token --project "$PROJECT_ID" --format='table(name,state,createTime)'
    rm -f "$HOME/.lab11-api-token"

หาก token ใหม่ได้ 401 ให้ตรวจว่า API rollout สร้าง Pod ใหม่ครบและ token ถูกสร้างจาก shell เดียวกัน; ห้ามปิด version เดิมก่อนผ่าน test. คำสั่งแสดงเฉพาะ HTTP code และ version state ไม่เผย payload.

**สิ่งที่คาดว่าจะเห็น (Expected):** API rollout Ready, token เดิมตอบ 401, token ใหม่ตอบ 200 และ secret version เก่าถูก disable หลังยืนยันการเปลี่ยนผ่าน.

**ผลจริงที่ฉันบันทึก:** old/new version IDs/state / old-new status / rollout duration / UTC: [กรอกผลจริง]

**หลักฐานที่เก็บ:** version metadata, HTTP status codes, API Deployment revision; ลบ token จากหลักฐานทุกชนิด.

### Task 19 — Cleanup แบบตรวจขอบเขตก่อนลบ

Task นี้ลบเฉพาะ resources ใน dedicated Lab 11 project. ห้ามลบ project, billing account, VPC หรือ repository ที่อยู่นอก prefix lab011. เริ่มจากลบ namespace เพื่อให้ Gateway controller เก็บ external load balancer ก่อน; หาก Gateway finalizer ค้าง ให้ตรวจ events/controller และรอ ไม่ถอด finalizer เอง.

**คำสั่ง Bash:**

    set -euo pipefail
    kubectl delete namespace quote-platform --wait=true --timeout=15m
    set +e
    NAMESPACE_OUTPUT=$(kubectl get namespace quote-platform 2>&1)
    NAMESPACE_STATUS=$?
    set -e
    printf '%s\n' "$NAMESPACE_OUTPUT"
    test "$NAMESPACE_STATUS" -ne 0
    grep -q "NotFound" <<<"$NAMESPACE_OUTPUT"

คำสั่งบรรทัดสุดท้ายควรได้ NotFound หลัง namespace ถูกลบ. ต่อไปลบเฉพาะ image family ที่สร้างโดย Lab แล้วตรวจ repository contents ก่อน destroy:

**คำสั่ง Bash:**

    set -euo pipefail
    IMAGE_REPOSITORY=$(terraform -chdir=infra output -raw image_repository)
    REPOSITORY_PATH=${IMAGE_REPOSITORY%/quote-engine}
    gcloud artifacts docker images list "$REPOSITORY_PATH" --include-tags --project "$PROJECT_ID" --format='table(package,version,tags)'
    gcloud artifacts docker images list "$IMAGE_REPOSITORY" --include-tags --project "$PROJECT_ID" --format='table(package,version,tags)'

ตรวจว่ารายการมีเฉพาะ package quote-engine ที่ build ใน Lab นี้. ถ้ามี image/package อื่น ให้หยุดและขอเจ้าของยืนยันก่อนลบ. เมื่อยืนยันแล้ว ใช้คำสั่งลบ image family เฉพาะของ Lab:

**คำสั่ง Bash:**

    gcloud artifacts docker images delete "$IMAGE_REPOSITORY" --delete-tags --quiet --project "$PROJECT_ID"
    gcloud artifacts docker images list "$REPOSITORY_PATH" --include-tags --project "$PROJECT_ID" --format='table(package,version,tags)'

ลบไฟล์ credential/certificate เฉพาะที่คู่มือนี้สร้างใน Cloud Shell; อย่าลบโฟลเดอร์ home หรือไฟล์อื่น:

**คำสั่ง Bash:**

    rm -f "$HOME/.lab11-api-token" "$HOME/.lab11-api-token-v2" "$HOME/.lab11-tmp/tls.key" "$HOME/.lab11-tmp/tls.crt"

ปิด deletion protection แล้วสร้างแผน destroy ที่อ่านได้ก่อน apply. ไฟล์ plan/state อยู่ใน local infra directory และไม่ควร commit.

**คำสั่ง Bash:**

    terraform -chdir=infra plan -var='allow_destroy=true' -out=lab11-unprotect.tfplan
    terraform -chdir=infra show -no-color lab11-unprotect.tfplan

ยืนยันว่าการเปลี่ยนแปลงมีเพียงการปิด deletion protection ของ cluster Lab นี้ แล้วจึง apply; หาก plan เปลี่ยน resource อื่นโดยไม่คาดหมาย ให้หยุด.

**คำสั่ง Bash:**

    terraform -chdir=infra apply lab11-unprotect.tfplan
    terraform -chdir=infra plan -destroy -var='allow_destroy=true' -out=lab11-destroy.tfplan
    terraform -chdir=infra show -no-color lab11-destroy.tfplan

ตรวจรายการ destroy ทีละรายการ: ต้องเป็น resources ที่ตั้งชื่อ lab011 หรือ IAM binding/service accounts ที่สร้างโดย Terraform ใน project เฉพาะนี้เท่านั้น. Terraform นี้ไม่ลบ project หรือ billing. หากรายการไม่ตรง, state หาย, หรือ project ID ไม่ตรง ให้หยุดก่อน apply.

**คำสั่ง Bash:**

    terraform -chdir=infra apply lab11-destroy.tfplan
    terraform -chdir=infra state list
    gcloud compute addresses list --project "$PROJECT_ID" --filter='name=lab011-gateway-ip' --format='table(name,address,status,region)'
    gcloud artifacts repositories list --project "$PROJECT_ID" --location "$REGION" --filter='name:lab011-images' --format='table(name,format,location)'
    gcloud container clusters list --project "$PROJECT_ID" --region "$REGION" --filter='name=lab011-quote-engine' --format='table(name,location,status)'

หลังตรวจผลแล้วลบไฟล์ plan/state ในโฟลเดอร์ infra ด้วยตัวจัดการไฟล์ของ Cloud Shell เฉพาะ lab11-foundation.tfplan, lab11-unprotect.tfplan, lab11-destroy.tfplan และ terraform.tfstate/terraform.tfstate.backup. เก็บ evidence ที่ sanitize แล้วก่อนลบ; ไม่ต้องลบ project. ตรวจซ้ำว่าไม่มี IP/cluster/repository ของ Lab ค้าง และบันทึก service APIs ที่ยัง enabled หากองค์กรต้องการปิดเอง.

**สิ่งที่คาดว่าจะเห็น (Expected):** namespace/Gateway/load balancer, image family, regional IP, GKE cluster, Artifact Registry repo, Secret Manager objects, IAM identities/network ของ Lab ถูกลบ; Terraform state ไม่มี resources. Project และ billing account ยังคงอยู่.

**ผลจริงที่ฉันบันทึก:** namespace deletion / gateway cleanup / image count before-after / destroy plan summary / state count / remaining Lab resources / UTC: [กรอกผลจริง]

**หลักฐานที่เก็บ:** sanitized destroy plan summary, state list หลัง destroy, รายการ resource checks ที่ไม่พบ resource และ cleanup time. Cloud verification จะเปลี่ยนเป็น Verified only เมื่อผู้เรียนแนบผลจริงที่ตรวจย้อนกลับได้.
## References

เอกสารบริการที่ใช้ตรวจรูปแบบและข้อจำกัดของ design (ทบทวน ณ รอบ authoring นี้):

- [GKE Autopilot clusters](https://cloud.google.com/kubernetes-engine/docs/concepts/autopilot-overview)
- [GKE network isolation และ DNS-based control-plane access](https://cloud.google.com/kubernetes-engine/docs/how-to/latest/network-isolation)
- [Deploying Gateways on GKE](https://cloud.google.com/kubernetes-engine/docs/how-to/deploying-gateways)
- [Regional proxy-only subnets](https://cloud.google.com/load-balancing/docs/proxy-only-subnets)
- [GKE NetworkPolicy](https://cloud.google.com/kubernetes-engine/docs/how-to/network-policy)
- [Workload Identity Federation for GKE](https://cloud.google.com/kubernetes-engine/docs/concepts/workload-identity)
- [Cloud Build: configure a user-specified service account](https://cloud.google.com/build/docs/securing-builds/configure-user-specified-service-accounts)
- [Cloud Build results and image digests](https://cloud.google.com/build/docs/view-build-results)
- [GKE horizontal Pod autoscaling](https://cloud.google.com/kubernetes-engine/docs/how-to/horizontal-pod-autoscaling)
- [Artifact Registry: manage container images](https://cloud.google.com/artifact-registry/docs/docker/manage-images)
- [Terraform Google provider: google_container_cluster 7.29.0](https://registry.terraform.io/providers/hashicorp/google/7.29.0/docs/resources/container_cluster)

เอกสารอ้างอิงไม่ใช่ผลทดสอบ Cloud ของ Lab นี้; ก่อนลงมือให้ตรวจราคา, quota, organization policy และเอกสารบริการฉบับปัจจุบันอีกครั้ง.