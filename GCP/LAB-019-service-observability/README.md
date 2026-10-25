# Lab 19 — ระบบเฝ้าระวังและรับ Incident สำหรับทีมบริการ

> **สถานะ:** Guide-ready — GitHub CI [#422](https://github.com/somkid-s5/Portfolio-Lab/actions/runs/40167519527) ผ่าน 76/76 repository jobs และ Lab 19 ผ่าน 5/5 checks
> **Cloud verification:** Not run — ไม่มีการสร้าง GCP resources หรือผลทดสอบจริง  
> **Diagram:** ใช้แนวทาง Diagram Design Personal Custom จาก ZIP ตาม [docs/diagram-style.md](../../docs/diagram-style.md)

## ภาพรวม Solution

ทีม Commerce รับคำสั่งงานผ่าน API แล้วให้ Worker ประมวลผลแบบ asynchronous ทีม On-call ต้องแยกให้ออกว่าคำขอล้มเหลวที่ขอบ API, งานค้างใน Queue, Worker ช้า หรือฐานข้อมูลเริ่มอิ่มตัว ต้องเห็นสัญญาณที่สัมพันธ์กับผลกระทบผู้ใช้ รับ Incident ที่มีเงื่อนไขชัด และบันทึกการตรวจพบ การบรรเทา และการกู้คืนได้

Solution ใช้ Cloud Run Task API, Pub/Sub push subscription, Cloud Run Worker และ Cloud SQL for PostgreSQL ใน `asia-southeast1`; Cloud Logging เก็บ structured logs, Cloud Monitoring คำนวณ SLO และส่ง burn-rate alerts, Cloud Trace ใช้ดู sampled request traces. API และ Worker ต้องยืนยันตัวตนด้วย IAM; Worker push ใช้ OIDC; Cloud SQL รับ private IP ผ่าน Direct VPC egress และ Private Services Access (PSA).

![Architecture ของ Lab 19](assets/solution.svg)

[เปิด HTML preview](assets/solution.html) · [ดู provenance และที่มาของ icons](assets/diagram-provenance.json)

## ขอบเขตของโจทย์

- **ผู้ใช้ระบบ:** Client ที่สร้าง/ตรวจ task และทีม SRE/On-call ที่รับผิดชอบ API, Queue, Worker และฐานข้อมูล
- **ข้อมูลตัวอย่าง:** Task ID, idempotency key, สถานะงาน, เวลาที่รับ/เริ่ม/จบ, attempt และผลสำเร็จ/ล้มเหลว ใช้ข้อมูลสังเคราะห์เท่านั้น
- **จุดเริ่มของ flow:** Client ส่ง `POST /tasks`; API ตรวจ input และ idempotency key แล้วตอบรับหลัง Pub/Sub รับ message จากนั้น Client ใช้ `GET /tasks/{task_id}` ตรวจสถานะ
- **การทำงานเบื้องหลัง:** Pub/Sub ส่ง message ไป Worker ด้วย push + OIDC; Worker เขียนผลลง Cloud SQL และต้องทำซ้ำได้อย่างปลอดภัยเมื่อได้รับ message ซ้ำ
- **ขอบเขตข้อมูล:** API และ Worker เป็น Cloud Run services แบบ IAM-authenticated; Cloud SQL ไม่มี public IP; VPC scope แสดงเฉพาะ subnet/egress path ส่วน Cloud SQL เป็น managed service ที่เข้าผ่าน PSA
- **ขอบเขตความพร้อมใช้งาน:** Cloud SQL แบบ single-zone สำหรับ Lab นี้; ไม่อ้าง HA, cross-region DR หรือ production readiness
- **ขอบเขต tracing:** Cloud Run สร้าง request traces แบบ sampled; ผู้เรียนใช้ task ID/request ID เชื่อม log เพื่อหาข้ามช่วง API/Workerได้ แต่ห้ามสรุปว่าเป็น distributed trace ครบทุก message
- **ขอบเขต Cloud:** คู่มือด้านล่างรวม Terraform, app, schema, bounded test tools, fault controls, checkpoints และ cleanup; README/CI ไม่ได้ยืนยันการทำงานบน GCP จริง

## Requirements

| ID | Requirement | วิธีพิสูจน์ที่ต้องมีใน Guide |
|---|---|---|
| R01 | API รับ task ที่ถูกต้องและปฏิเสธ input ผิดรูปแบบ พร้อม idempotency key | ส่ง input ปกติ, ซ้ำ key เดิม และ input ไม่ถูกต้อง; บันทึก HTTP status และ task ID |
| R02 | API แสดงสถานะ task ที่ยังรอ กำลังทำ เสร็จ และล้มเหลว | เรียก `GET /tasks/{task_id}` ตามแต่ละสถานะและยืนยันข้อมูลที่อ่านได้ |
| R03 | Pub/Sub push เรียก Worker ที่ไม่เปิด anonymous access และตรวจ OIDC token | ตรวจ IAM binding, service account, audience และการปฏิเสธ request ที่ไม่มี token |
| R04 | API/Worker เข้าถึง Cloud SQL ผ่าน private IP และ PSA | ตรวจ IP/connection path จาก Cloud Run และยืนยันว่า instance ไม่มี public IP |
| R05 | API, Worker และ push identity แยกกันและใช้สิทธิ์เท่าที่ต้องใช้ | บันทึก service account ต่อ service และ role/resource scope ที่ให้จริง |
| R06 | ทุก business request log มี request/task identifier, route, status/outcome และ duration | ตรวจ JSON log ของ API/Worker และบันทึก Logs Explorer filter ที่ใช้ |
| R07 | Availability SLI นับเฉพาะ business request ที่เข้าเกณฑ์; `/healthz` และ expected 4xx ไม่กิน error budget | ยิง health check, valid request, invalid 4xx และ injected 5xx; เปรียบเทียบ counter |
| R08 | Availability SLO เป้าหมาย 99.5% บน rolling 7 วัน | ตรวจ SLO service, SLI filter, goal และ compliance window ใน Monitoring |
| R09 | Latency SLO เป้าหมายอย่างน้อย 95% ของ request ต่ำกว่า 1,000 ms บน rolling 7 วัน | ตรวจ distribution metric, threshold, goal และผลใน SLO view |
| R10 | Fast burn alert ตั้งที่ 10× ใน 1 ชั่วโมง และ slow burn ตั้งที่ 2× ใน 24 ชั่วโมง | ทำ fault scenario ตามปริมาณจำกัดและเก็บ condition, incident และเวลาที่เกิด |
| R11 | Dashboard แสดง API traffic/error/latency, Pub/Sub backlog/อายุ message, Worker failure/DLQ และ Cloud SQL CPU/connection | บันทึก dashboard panels, time range และค่าที่เห็นระหว่าง baseline กับ fault |
| R12 | Uptime check เรียก API ด้วย OIDC จาก Monitoring service agent; API ไม่เปิด `allUsers` | ตรวจ check configuration, service-agent binding, successful authenticated check และ IAM policy |
| R13 | Runbook เริ่มจากผลกระทบผู้ใช้และแยก API, Queue, Worker, Database ก่อน mitigation | ทำ incident drill และกรอกเวลา/หลักฐานของแต่ละ checkpoint |
| R14 | Change Request ลด noise จาก expected 4xx/เหตุการณ์โดดเดี่ยว โดยยังตรวจพบ sustained 5xx, SLO burn และ Queue ค้าง | เปรียบเทียบ baseline/candidate alerts ด้วย test scenarios; แสดง alert ที่ต้องเงียบและที่ต้องเกิด |

**Acceptance criteria**

1. Request ที่ API ตอบรับแล้วมี task ID ตรวจสถานะต่อได้; duplicate delivery ไม่ทำให้เกิด side effect ซ้ำ
2. API และ Worker ติดต่อ Cloud SQL ผ่าน private path; Pub/Sub ส่งถึง Worker ด้วย OIDC; request anonymous ถูกปฏิเสธ
3. SLI filters ตัด `/healthz` และ expected 4xx ออกอย่างชัดเจน; 5xx และ latency ที่เกินเกณฑ์นับเป็น bad service
4. เห็นทั้ง API-level user SLO และ queue/worker/database health; ไม่ใช้ backlog metric แทน SLO ของผู้ใช้
5. fault drill สร้าง incident ตามเงื่อนไขที่กำหนดและบันทึกหลักฐาน; recovery ปิด/resolve incident ได้พร้อมเหตุผล
6. Change Request ผ่านทั้ง “สิ่งที่ควรเงียบ” และ “failure ที่ยังต้อง alert”; ไม่มี alert ที่อ้างจาก test ไม่ได้
7. Cleanup ระบุ resource inventory และตรวจรายการคงเหลือหลังลบ; มีวิธีป้องกันการลบ project ผิด

## Architecture decisions

| การตัดสินใจ | เหตุผลและผลที่ต้องยอมรับ |
|---|---|
| แยก API และ Worker เป็น Cloud Run คนละ service | ปรับ IAM, concurrency, scaling และ fault injection แยกกัน; เพิ่มจำนวน revision ได้จำกัดตาม budget |
| ใช้ Pub/Sub push + OIDC ไป Worker | แสดง identity ระหว่าง service และ retry; handler ต้อง idempotent เพราะ delivery ซ้ำได้ |
| ใช้ Cloud SQL PostgreSQL private IP ผ่าน Direct VPC egress + PSA พร้อม automatic IAM database authentication | Connector จัดการ TLS และ short-lived token; API/Worker มี IAM database users คนละบัญชี; migration Job แยกจาก runtime และได้รับสิทธิ์ฐานข้อมูลสูงเท่าที่ต้องใช้เฉพาะงาน schema |
| ใช้ log-based counter/distribution metrics สร้าง SLI แบบมี business exclusions | native request metrics ยังใช้ดู platform; structured business event ทำให้ expected 4xx และ health check ไม่ปะปนกับ eligible requests; log-based metric มี processing delay ที่ต้องระบุใน troubleshooting |
| ใช้ SLO targets 99.5% availability และ 95% latency < 1,000 ms บน 7 วัน | เป็น training objectives สำหรับฝึก error budget; ไม่ใช่ผลวัดจริงหรือคำรับรอง production |
| ใช้ burn rates 10×/1h และ 2×/24h | เรียนรู้ fast/slow response; ผู้เรียนต้องตรวจหน้าต่างและ notification delay ก่อนสรุปผล |
| ใช้ Cloud Run sampled traces และ structured log correlation | Trace sampling ไม่รับประกันทุก request; task ID ใช้ตาม flow ข้าม Pub/Sub ได้ |
| ใช้ Cloud SQL single-zone, Cloud Run min instances = 0 และ bounded load | คุมค่าใช้จ่ายของ Lab; ไม่ได้แสดง high availability หรือ capacity ของ production |

### SLI และ Error Budget ที่จะใช้

- `eligible_request_total`: business request ที่ผ่าน validation และเข้าสู่การทำงานจริง; ไม่รวม `/healthz`, expected 4xx และเส้นทางที่ไม่ใช่ user request
- `eligible_request_bad`: eligible request ที่ตอบ 5xx หรือไม่ทำตาม latency/behavior contract
- **Availability:** `good / total` โดย good = total − bad; SLO 99.5% ใน rolling 7 วัน
- **Latency:** distribution ของ `request_duration_ms` สำหรับ eligible requests; good เมื่อใช้เวลาไม่เกิน 1,000 ms; SLO 95% ใน rolling 7 วัน
- **Error budget:** งบเริ่มต้นตาม SLO คือ 0.5% ของ eligible requests; การอ่านต้องดูปริมาณตัวอย่างและช่วง metric ยังไม่พร้อม
- **Metric delay:** logs-based metrics ปรากฏช้ากว่า log entry; Guide ต้องให้ผู้เรียนรอ/refresh ตาม latency ที่หน้า metric ระบุ และเทียบกับ Cloud Run native metrics ห้ามตีความกราฟว่างทันทีว่าไม่มี traffic
- ตัวเลขและ filters นี้เป็น design target สำหรับคู่มือ; ไม่มีการคำนวณหรือผล Cloud ใน checkpoint นี้

### การตอบสนองต่อ Incident

ใช้ Cloud Monitoring Incidents เป็น incident board ของ Lab และกำหนด notification channel ของผู้เรียนเองเมื่อทำ Guide ในอนาคต ลำดับตรวจ: user impact/SLO → API 5xx/latency → Pub/Sub backlog และ oldest unacked age → Worker errors/retry/DLQ → Cloud SQL CPU/connection → mitigation → verify recovery → resolve incident.

การทดสอบสร้าง fault ด้วย revision environment variables สำหรับ API delay/5xx และ Worker processing delay เฉพาะใน Lab project เท่านั้น ไม่มี public chaos endpoint และต้องคืนค่า revision/config หลังตรวจ Fault load จำกัดจำนวน request และช่วงเวลา; ห้ามใช้ load test ต่อเนื่อง

### ขอบเขตค่าใช้จ่ายและความปลอดภัย

Cloud SQL, serverless egress, log ingestion/retention, uptime checks และ notification channels อาจมีค่าใช้จ่ายหรือข้อจำกัดตาม account/region/quota ต้องตรวจราคาและ billing account ก่อนเริ่ม Guide. กำหนด max instances/concurrency, queue test volume, log retention และ cleanup ไว้ในคู่มือ. **Budget เป็น alert-only และไม่ได้จำกัดค่าใช้จ่ายโดยอัตโนมัติ.** ไม่มีการ provision ในงานเขียน Lab นี้.

ไม่มี `allUsers` บน API/Worker; ใช้ distinct service accounts, OIDC push, Monitoring service agent invoker เฉพาะ API และ least privilege. ห้ามใส่ credentials, email ส่วนตัว, task payload จริง หรือข้อมูล billing ลงหลักฐาน.

## Change Request

**CR-19-01 — ลด alert noise โดยคงการตรวจพบเหตุที่กระทบผู้ใช้**

ทีมพบ Incident มากเกินไปจาก input error และ error ชั่วคราวหนึ่งครั้ง จึงต้องปรับ alert ให้ expected 4xx และ isolated failure ไม่ page On-call แต่ sustained 5xx, burn-rate breach, queue backlog/oldest message age ที่เกินเกณฑ์ และ Worker/DB saturation ยังสร้าง Incident ตามลำดับความรุนแรง ผู้เรียนต้องแสดง filter/threshold ก่อนและหลัง พร้อม test cases ที่ยืนยันทั้ง alert suppression และ alert ที่ยังต้องทำงาน ห้ามปิด alert policy ทั้งหมดเพื่อให้เงียบ



## คู่มือทำ Solution Lab

### ขอบเขตการทำจริงและความปลอดภัย

คู่มือนี้ให้ทำใน **Lab project ที่แยกสำหรับฝึก** เท่านั้น ใช้ Cloud Shell, Terraform และ Cloud Console ตามจุดตรวจ; GitHub CI ไม่สร้าง GCP resources และช่อง Actual จะไม่ถูกกรอกแทนผลจริง

Cloud SQL, Cloud Run, Cloud Build, Pub/Sub, Cloud Logging และ Monitoring อาจคิดค่าบริการตามการใช้งาน แม้จำนวนทดสอบถูกจำกัด ค่า min_instance_count = 0, max_instance_count และจำนวน request เป็นขอบเขตของ Lab ไม่ใช่ budget cap ก่อน Apply ให้ตรวจราคา [Google Cloud Pricing Calculator](https://cloud.google.com/products/calculator) และ [Cloud SQL pricing](https://cloud.google.com/sql/pricing). Budget เป็นการแจ้งเตือน ไม่ได้หยุด resource ให้เอง

ห้ามใช้ production project, credentials/token ใน screenshot, task payload จริง หรือส่ง alert ไปยัง production on-call. Task T13 จะเปิด policy noisy ชั่วคราวเพื่อส่งอีเมลไปยัง channel ของ Lab เท่านั้น แล้วปิดด้วย Terraform ก่อนตรวจ SLO policy.

### ค่าที่ใช้ตลอด Lab

| ชื่อ | ค่า |
|---|---|
| Region | asia-southeast1 |
| VPC / subnet | lab19-vpc / lab19-run-egress |
| Cloud SQL | lab19-postgres, database lab19, PostgreSQL 16, private IP |
| API / Worker | lab19-task-api / lab19-task-worker |
| Migration Job | lab19-schema-migrate |
| Pub/Sub | lab19-tasks, lab19-task-push, DLQ lab19-tasks-dlq |
| Artifact Registry | asia-southeast1-docker.pkg.dev/PROJECT_ID/lab19-apps/lab19-service |
| SLO | Availability 99.5%; latency 95% ต่ำกว่า 1,000 ms; rolling 7 วัน |
| สถานะเริ่มต้น | Cloud verification: **Not run** |

### Task T00 — ตรวจ project, สิทธิ์, quota และงบก่อนสร้าง

1. ใน Cloud Console เลือกหรือสร้าง project เฉพาะ Lab ตรวจ Project ID และ billing account.
2. ที่ **Billing → Budgets & alerts** ตั้ง budget/การแจ้งเตือนตามงบที่ยอมรับได้ และจดว่า budget ไม่ได้ปิด resource อัตโนมัติ.
3. ที่ **IAM & Admin → IAM** ตรวจว่า operator จัดการ API services, VPC/PSA, Cloud SQL, Pub/Sub, Artifact Registry, Cloud Build, Cloud Run, Monitoring และ IAM bindings ใน project นี้ได้. การฝึกแบบ project เดี่ยวอาจให้ Project Owner เฉพาะ Lab project; ห้ามขอสิทธิ์ระดับ organization หรือใช้ production project.
4. ที่ **IAM & Admin → Quotas & System Limits** ตรวจ quota ของ Cloud SQL, Cloud Run, Cloud Build และ subnet/IP; ถ้า quota ไม่พอให้หยุดก่อน Foundation Apply.
5. ยืนยัน region asia-southeast1 และตรวจราคา tier db-custom-1-3840 ในวันทำจริง.

**Checkpoint:** มี Project ID, billing, ผู้อนุมัติสิทธิ์, quota และ cost review ครบก่อนสร้าง resource.

**ผลที่คาดหวัง:** ใช้ project แยก มี billing/quota/role พร้อม; ยังไม่มี Lab 19 resources.

**บันทึกจริง / หลักฐาน:** Project ID (ไม่ใส่เลข billing) ______ · Region ______ · สิทธิ์/ผู้อนุมัติ ______ · tier/ราคาและวันที่ตรวจ ______ · Budget alert ______ · quota ที่ติด ______

**ถ้าไม่ผ่าน:** ถ้าไม่มี billing หรือสิทธิ์จัดการ IAM/API ให้หยุดและขอผู้ดูแล Lab project; อย่าเลี่ยงด้วยการใช้ shared/prod project.

### Task T01 — เปิด Cloud Shell และเตรียม working copy

1. เปิด Cloud Console ของ Lab project แล้วเลือก **Activate Cloud Shell**.
2. Clone branch นี้ หรือ fast-forward working copy เดิม:
```bash
if [ ! -d "$HOME/Portfolio-Lab/.git" ]; then
  git clone --branch docs/gcp-solution-labs --depth 1 https://github.com/somkid-s5/Portfolio-Lab.git "$HOME/Portfolio-Lab"
fi
cd "$HOME/Portfolio-Lab"
git fetch origin docs/gcp-solution-labs
git checkout docs/gcp-solution-labs
git pull --ff-only origin docs/gcp-solution-labs

export LAB19_DIR="$HOME/Portfolio-Lab/GCP/LAB-019-service-observability"
export PROJECT_ID="replace-with-your-lab-project-id"
export REGION="asia-southeast1"
case "$PROJECT_ID" in
  replace-*) echo "Set PROJECT_ID to the dedicated Lab project first"; exit 1 ;;
esac

gcloud config set project "$PROJECT_ID"
gcloud auth list --filter=status:ACTIVE --format="table(account,status)"
gcloud version
terraform version
python3 --version
git -C "$HOME/Portfolio-Lab" rev-parse --short HEAD
```
3. แทน Project ID และตรวจ active identity ว่ามีสิทธิ์ตาม T00; HEAD ต้องเป็น commit ของ branch docs/gcp-solution-labs.
4. ใช้ Cloud Shell เดิมเพื่อเก็บ local Terraform state/working files จน Cleanup; คำสั่งต่อไปใช้ LAB19_DIR.

**Checkpoint:** gcloud config get-value project ได้ Lab project; Terraform >= 1.9.8, < 2.0; region เป็น asia-southeast1.

**ผลที่คาดหวัง:** Cloud Shell ชี้ project/identity ถูกต้องและ checkout มี source, scripts, Terraform และ diagram.

**บันทึกจริง / หลักฐาน:** Cloud Shell zone ______ · Project ID ______ · identity type (ไม่บันทึก email) ______ · Terraform version ______ · Git commit ______

**ถ้าไม่ผ่าน:** หาก git pull --ff-only แจ้ง divergence ให้ตรวจ working copy; ห้าม force reset/push. ถ้า Terraform เก่ากว่า requirement ให้อัปเดต tooling ก่อน Init.

### Task T02 — สร้าง Foundation แบบ private ด้วย Terraform

Foundation สร้าง API enablement, VPC/subnet, PSA, Cloud SQL private IP, Pub/Sub topics, Artifact Registry และ service accounts/roles. Cloud SQL tier เริ่มต้น db-custom-1-3840 มีค่าใช้จ่าย.

1. คัดลอกตัวอย่าง tfvars แล้วกรอก Project ID กับ principal ผู้ทำ Lab. operator_member ใช้รูปแบบ user:email หรือ serviceAccount:name@project.iam.gserviceaccount.com; ห้าม commit terraform.tfvars.
2. เปิดแก้ไฟล์:
```bash
cd "$LAB19_DIR/infra/foundation"
cp terraform.tfvars.example terraform.tfvars
nano terraform.tfvars
```
3. กรอก project_id, region = "asia-southeast1", db_tier ที่ผ่าน cost review และ operator_member; ไฟล์นี้ถูก .gitignore ครอบคลุม.
4. Init, validate, สร้าง plan และอ่าน plan ก่อน Apply:
```bash
terraform init
terraform fmt -check -recursive ..
terraform validate
terraform plan -out=foundation.tfplan
terraform show -no-color foundation.tfplan
```
5. ตรวจ project/region/tier, ไม่มี resource นอก Lab, Cloud SQL เป็น ZONAL และไม่มี public IPv4 แล้ว Apply:
```bash
terraform apply foundation.tfplan
terraform output
```
6. รอ Cloud SQL และ Service Networking เสร็จ. ถ้า Apply ล้มเหลวให้แก้สาเหตุและสร้าง plan ใหม่; อย่า Apply plan เก่าหลัง source/input เปลี่ยน.

**ผลที่คาดหวัง:** outputs แสดง connection name, private IP, Artifact Registry และ service accounts; SQL ไม่มี public IPv4. Terraform state ต้องเก็บเป็นข้อมูลส่วนตัวจน Destroy เสร็จ.

**บันทึกจริง / หลักฐาน:** Plan path ______ · Apply timestamp ______ · SQL connection name ______ · private IP (หลักฐานส่วนตัว) ______ · tier/region ______ · ราคาที่ประมาณ ______

**ถ้าไม่ผ่าน:** ตรวจ billing, API enablement, project IAM, quota และ PSA range overlap. อย่าสร้าง VPC/SQL ซ้ำใน Console ขณะ Terraform ยังถือ state.

### Task T03 — ตรวจ source และ Build image ด้วย Cloud Build

1. ตรวจ Python syntax โดยไม่เรียก GCP:
```bash
cd "$LAB19_DIR"
python3 -m py_compile app/*.py scripts/*.py
```
2. สร้าง image tag ใหม่และใช้ Cloud Build service account จาก Foundation:
```bash
cd "$LAB19_DIR/app"
export IMAGE_REPOSITORY="$REGION-docker.pkg.dev/$PROJECT_ID/lab19-apps/lab19-service"
export IMAGE_TAG="lab19-$(date -u +%Y%m%d%H%M%S)"
export IMAGE_URI="$IMAGE_REPOSITORY:$IMAGE_TAG"
export BUILD_SA="projects/$PROJECT_ID/serviceAccounts/lab19-build@$PROJECT_ID.iam.gserviceaccount.com"

gcloud builds submit . \
  --config=cloudbuild.yaml \
  --region="$REGION" \
  --service-account="$BUILD_SA" \
  --substitutions="_IMAGE_URI=$IMAGE_URI"
```
3. Build config ระบุ CLOUD_LOGGING_ONLY; build SA เขียน Artifact Registry ตาม IAM ที่ Foundation ให้.
4. เลือก Build ID ล่าสุดของ project Lab แล้วอ่าน digest (ระหว่างขั้นนี้อย่าส่ง build อื่นใน project เดียวกัน):
```bash
export BUILD_ID="$(gcloud builds list --region="$REGION" --limit=1 --sort-by='~createTime' --format='value(id)')"
gcloud builds describe "$BUILD_ID" --region="$REGION" --format="yaml(id,status,results.images)"
export IMAGE_DIGEST="$(gcloud builds describe "$BUILD_ID" --region="$REGION" --format='value(results.images[0].digest)')"
export IMAGE_REF="$IMAGE_REPOSITORY@$IMAGE_DIGEST"
printf 'IMAGE_DIGEST=%s\nIMAGE_REF=%s\n' "$IMAGE_DIGEST" "$IMAGE_REF"
```
5. ตรวจ SUCCESS และ digest รูปแบบ sha256: ตามด้วย 64 hex; Runtime ใช้ digest immutable ไม่ใช้ tag.

**ผลที่คาดหวัง:** Build สำเร็จและ Artifact Registry มี image ที่ระบุ digest เดียวกัน; เป็นผลจาก Cloud Build ที่ผู้เรียนรันจริง ไม่ได้จำลองโดยคู่มือ.

**บันทึกจริง / หลักฐาน:** Build ID ______ · status ______ · image digest ______ · build log link ______ · source commit ______

**ถ้าไม่ผ่าน:** ตรวจ Cloud Build Editor สำหรับ operator, iam.serviceAccountUser บน lab19-build, Artifact Registry writer สำหรับ build SA, Cloud Build API และ log permission. ตรวจ Build ID/region และ app/cloudbuild.yaml; ห้ามบันทึก access token ลงหลักฐาน.

### Task T04 — Run schema migration Job ด้วย migrator identity

Job นี้สร้าง lab19.tasks และ database roles ก่อน runtime services; ใช้ Cloud SQL IAM database user ที่ตัด suffix .gserviceaccount.com, Cloud SQL Connector และ private VPC egress. ไม่มี DB password.

1. ตั้ง connection name และ username:
```bash
export INSTANCE_CONNECTION_NAME="$PROJECT_ID:$REGION:lab19-postgres"
export MIGRATOR_SA="lab19-migrator@$PROJECT_ID.iam.gserviceaccount.com"
export MIGRATOR_DB_USER="lab19-migrator@$PROJECT_ID.iam"
```
2. Deploy Job จาก image digest เดียวกับ T03:
```bash
gcloud run jobs deploy lab19-schema-migrate \
  --project="$PROJECT_ID" \
  --region="$REGION" \
  --image="$IMAGE_REF" \
  --command=python \
  --args=-m,app.migrate \
  --service-account="$MIGRATOR_SA" \
  --set-env-vars="GOOGLE_CLOUD_PROJECT=$PROJECT_ID,INSTANCE_CONNECTION_NAME=$INSTANCE_CONNECTION_NAME,DB_NAME=lab19,DB_IAM_USER=$MIGRATOR_DB_USER" \
  --network=lab19-vpc \
  --subnet=lab19-run-egress \
  --vpc-egress=private-ranges-only \
  --tasks=1 \
  --max-retries=0 \
  --task-timeout=5m
```
3. Execute แล้วรอจบ:
```bash
gcloud run jobs execute lab19-schema-migrate --project="$PROJECT_ID" --region="$REGION" --wait
```
4. ตรวจ execution และ log:
```bash
gcloud run jobs executions list --job=lab19-schema-migrate --project="$PROJECT_ID" --region="$REGION"
gcloud logging read 'resource.type="cloud_run_job" AND resource.labels.job_name="lab19-schema-migrate" AND textPayload:"migration_status=applied"' \
  --project="$PROJECT_ID" --freshness=1h --limit=10 \
  --format="table(timestamp,textPayload)"
```

**Checkpoint:** log มี migration_status=applied schema=lab19 table=tasks api_role=lab19_api_role worker_role=lab19_worker_role; Job จบ success ก่อน Runtime Apply.

**ผลที่คาดหวัง:** schema/table/roles พร้อม; migration ทำซ้ำได้และไม่เก็บ DB password ใน Cloud Run config.

**บันทึกจริง / หลักฐาน:** execution name ______ · result ______ · log timestamp ______ · schema/table check ______

**ถ้าไม่ผ่าน:** ตรวจ Job service account, roles/cloudsql.client, roles/cloudsql.instanceUser, IAM DB user, Cloud SQL Admin API, Connector log และ private egress/PSA. อย่าสร้าง API/Worker ก่อน migration ผ่าน.

### Task T05 — Deploy Runtime, API, Worker และ Observability

1. Runtime stack สร้าง API/Worker แบบ IAM-only, แยก DB roles, Pub/Sub push OIDC/DLQ/status handlers, log metrics, SLO, alert policies, dashboard และ authenticated uptime check.
2. คัดลอกตัวอย่าง tfvars; กำหนด image digest/ผู้ใช้/email และ fault modes ปิด:
```bash
cd "$LAB19_DIR/infra/runtime"
cp terraform.tfvars.example terraform.tfvars
nano terraform.tfvars
```
3. กรอก project_id, region, image_digest = "$IMAGE_DIGEST", operator_member, alert_email; ตั้ง api_fault_mode = "none", worker_fault_mode = "none", worker_delay_ms = 0, cr_baseline_single_5xx_enabled = false. เก็บ tfvars/state เป็น private.
4. อ่าน plan:
```bash
terraform init
terraform fmt -check
terraform validate
terraform plan -out=runtime.tfplan
terraform show -no-color runtime.tfplan
```
5. ยืนยัน plan ใช้ digest T03, faults none, baseline alert ปิด และไม่มี allUsers; Apply แล้วเก็บ URI:
```bash
terraform apply runtime.tfplan
terraform output
export API_URL="$(terraform output -raw api_uri)"
printf 'API_URL=%s\n' "$API_URL"
```
6. ตรวจ Cloud Run:
```bash
gcloud run services describe lab19-task-api --project="$PROJECT_ID" --region="$REGION" --format="yaml(status.url,status.conditions)"
gcloud run services describe lab19-task-worker --project="$PROJECT_ID" --region="$REGION" --format="yaml(status.url,status.conditions)"
```

**ผลที่คาดหวัง:** outputs มี API URI/SLO names; API/Worker เป็น Ready, ใช้ identities แยก และ faults เป็น none. SLO ยังอาจไม่มี data จนมี request/ingestion.

**บันทึกจริง / หลักฐาน:** Plan ______ · Apply timestamp ______ · API revision ______ · Worker revision ______ · image digest ______ · email channel verification ______

**ถ้าไม่ผ่าน:** หยุด traffic. ตรวจ T04 migration, image digest, Foundation state, project/region และ notification channel.

### Task T06 — พิสูจน์ API, idempotency และผลประมวลผล

1. ดึง URI/token และสร้าง idempotency key ใหม่:
```bash
export API_URL="$(terraform -chdir="$LAB19_DIR/infra/runtime" output -raw api_uri)"
export TOKEN="$(gcloud auth print-identity-token)"
export IDEMPOTENCY_KEY="lab19-manual-$(date -u +%Y%m%d%H%M%S)"
```
2. เขียน payload สังเคราะห์:
```bash
python3 - <<'PY'
import json
import os

payload = {
    "idempotency_key": os.environ["IDEMPOTENCY_KEY"],
    "items": [{"sku": "DEMO-001", "quantity": 2, "unit_price_cents": 1250}],
}
with open("/tmp/lab19-task.json", "w", encoding="utf-8") as handle:
    json.dump(payload, handle)
PY
```
3. ส่ง POST แล้วส่ง payload เดิมซ้ำ:
```bash
curl -sS -o /tmp/lab19-create.json -w 'HTTP %{http_code}\n' \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  --data-binary @/tmp/lab19-task.json "$API_URL/tasks"
cat /tmp/lab19-create.json
export TASK_ID="$(python3 -c 'import json; print(json.load(open("/tmp/lab19-create.json"))["task_id"])')"
curl -sS -o /tmp/lab19-duplicate.json -w 'HTTP %{http_code}\n' \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  --data-binary @/tmp/lab19-task.json "$API_URL/tasks"
cat /tmp/lab19-duplicate.json
```
4. ตรวจ task ID เดิมและ idempotent_replay=true; poll จน Worker เขียนผล:
```bash
for attempt in $(seq 1 20); do
  if curl -fsS -H "Authorization: Bearer $TOKEN" "$API_URL/tasks/$TASK_ID" -o /tmp/lab19-status.json; then
    export TASK_STATUS="$(python3 -c 'import json; print(json.load(open("/tmp/lab19-status.json"))["status"])')"
    cat /tmp/lab19-status.json
    [ "$TASK_STATUS" = "SUCCEEDED" ] && break
  fi
  sleep 2
done
test "$TASK_STATUS" = "SUCCEEDED"
```

**ผลที่คาดหวัง:** POST 202, duplicate ใช้ task ID เดิม, status SUCCEEDED, line_count=1, total_cents=2500; duplicate delivery ไม่ทำ side effect ซ้ำ.

**บันทึกจริง / หลักฐาน:** HTTP status แรก/ซ้ำ ______ / ______ · task ID (ปกปิดใน public image ได้) ______ · final status/result ______ · submit-to-complete duration ______

**ถ้าไม่ผ่าน:** 401/403 ตรวจ token/invoker; 503 ตรวจ API/Worker logs กับ Pub/Sub; task QUEUED ให้ตรวจ backlog, push delivery, Worker และ SQL ก่อนส่งซ้ำ.

### Task T07 — ตรวจ IAM, OIDC และ private database boundary

1. เรียก health แบบไม่มี token:
```bash
ANON_CODE="$(curl -sS -o /tmp/lab19-anonymous.txt -w '%{http_code}' "$API_URL/healthz")"
printf 'anonymous_http_status=%s\n' "$ANON_CODE"
test "$ANON_CODE" = "403"
```
2. ตรวจ IAM policy ของ API/Worker; ต้องไม่มี allUsers:
```bash
gcloud run services get-iam-policy lab19-task-api --project="$PROJECT_ID" --region="$REGION" --format=yaml
gcloud run services get-iam-policy lab19-task-worker --project="$PROJECT_ID" --region="$REGION" --format=yaml
```
3. ตรวจ push OIDC และ DLQ route:
```bash
gcloud pubsub subscriptions describe lab19-task-push --project="$PROJECT_ID" --format="yaml(pushConfig,deadLetterPolicy)"
gcloud pubsub subscriptions describe lab19-task-dlq-status --project="$PROJECT_ID" --format="yaml(pushConfig)"
```
4. ตรวจ Cloud SQL IP config และ IAM users:
```bash
gcloud sql instances describe lab19-postgres --project="$PROJECT_ID" \
  --format="yaml(ipAddresses,settings.ipConfiguration.ipv4Enabled,settings.ipConfiguration.privateNetwork)"
gcloud sql users list --instance=lab19-postgres --project="$PROJECT_ID"
```

**ผลที่คาดหวัง:** anonymous ได้ 403; API/Worker ไม่มี allUsers; push ใช้ lab19-push + OIDC; SQL ipv4Enabled=false มี private network และ IAM identities แยก API/Worker/Migrator.

**บันทึกจริง / หลักฐาน:** anonymous HTTP ______ · API/Worker policy review ______ · push SA/audience ______ · SQL public IPv4 false? ______ · DB users/roles ______

**ถ้าไม่ผ่าน:** อย่าแก้ด้วย public invoker. ตรวจ roles/run.invoker, Pub/Sub token creator/service agent, Cloud SQL client/instanceUser และ custom database roles.

### Task T08 — ตรวจ structured logs และ SLI exclusion

1. ใน Logging → Logs Explorer หรือ Cloud Shell ดู business events:
```bash
gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="lab19-task-api" AND jsonPayload.event="business_request"' \
  --project="$PROJECT_ID" --freshness=1h --limit=30 \
  --format="table(timestamp,jsonPayload.request_id,jsonPayload.task_id,jsonPayload.status_code,jsonPayload.eligible,jsonPayload.outcome,jsonPayload.duration_ms)"
```
2. ตรวจ Worker โดยใช้ service name lab19-task-worker และ event worker_task; เชื่อมด้วย task ID.
3. ตรวจ log-based metric ที่ Terraform สร้าง:
```bash
gcloud logging metrics describe lab19_eligible_requests --project="$PROJECT_ID"
gcloud logging metrics describe lab19_request_duration_ms --project="$PROJECT_ID"
gcloud logging metrics describe lab19_dead_lettered_tasks --project="$PROJECT_ID"
```
4. ตรวจ /healthz และ expected 4xx เป็น eligible=false; success เป็น good; 5xx เป็น bad. Cloud Run Trace เป็น sampled จึงอาจไม่มี trace ทุก request.

**ผลที่คาดหวัง:** JSON logs แยก API/Worker; log metrics นับเฉพาะ eligible API business requests.

**บันทึกจริง / หลักฐาน:** Logs Explorer filter ______ · request/task ID ที่ปกปิดแล้ว ______ · metric descriptors ______ · health/4xx exclusion ______ · trace sample (ถ้ามี) ______

**ถ้าไม่ผ่าน:** ตรวจ service name, JSON field path, metric descriptor/ingestion delay. สร้าง request ใหม่ภายใน limit แล้วรอ metric; ห้ามกรอกค่าที่คาดเดาเป็น Actual.

### Task T09 — ตรวจ Availability/Latency SLO และ dashboard

1. เปิด Monitoring → Services, เลือก lab19-task-api; ตรวจ SLO IDs จาก Terraform.
2. ยืนยัน Availability 99.5% และ latency 95% ต่ำกว่า 1,000 ms, rolling 7 วัน; SLI ใช้ lab19_eligible_requests และ lab19_request_duration_ms.
3. เปิด Monitoring → Dashboards → Lab 19 · Service SLO and operations; ตรวจ eligible outcomes, p95 latency, Pub/Sub oldest age, DLQ tasks และ Cloud SQL CPU.
4. เลือก time range ครอบคลุม T06 และบันทึกเวลาที่ metric เข้า.

**ผลที่คาดหวัง:** config ของ SLO/dashboard ตรง brief; no data/partial data ช่วงแรกไม่ใช่หลักฐานว่า SLO ผ่าน 7 วัน.

**บันทึกจริง / หลักฐาน:** SLO IDs/goals ______ · panels ที่เห็น ______ · time range ______ · metric delay/state ______

**ถ้าไม่ผ่าน:** ตรวจ metric descriptors/SLI filter ก่อนแก้ SLO; อย่าลด goal เพื่อทำให้หน้าจอเขียว.

### Task T10 — ตรวจ burn-rate, resource alerts และ notification channel

1. เปิด Monitoring → Alerting → Policies; ตรวจ policies Task API fast SLO burn, Task API slow SLO burn, Task queue oldest message, Repeated Worker push failures, Tasks exhausted retries and entered DLQ, Cloud SQL CPU saturation.
2. Fast/slow burn ต้องผูก availability-7d: 10×/60m และ 2×/24h. ตรวจ queue/worker/DLQ/SQL เป็นสัญญาณแยกจาก user SLO.
3. เปิด Monitoring → Alerting → Edit notification channels; ตรวจ Lab 19 On-call email และยืนยัน inbox สำหรับ Lab เท่านั้น.
4. ยังไม่ inject fault จน Baseline T12 พร้อม. Policy ที่ไม่มี data ยังไม่ผ่าน alert test.

**ผลที่คาดหวัง:** Terraform สร้าง 6 operational policies + email channel; channel ที่ใช้ทดสอบได้รับการตรวจใน Console.

**บันทึกจริง / หลักฐาน:** policy names/thresholds ______ · channel verified? ______ · inbox type (ไม่บันทึก address) ______ · status ก่อน fault ______

**ถ้าไม่ผ่าน:** ตรวจ channel verification, policy enabled, SLO filter และ metric delay; อย่าส่ง alert ไป production.

### Task T11 — ตรวจ OIDC uptime check

1. เปิด Monitoring → Uptime checks แล้วเลือก Lab 19 · Authenticated Task API health: HTTPS /healthz, Asia Pacific, 60s, OIDC.
2. ตรวจ Monitoring service agent ได้ roles/run.invoker บน API; API ต้องไม่มี allUsers.
3. รอรอบตรวจหลายครั้งและบันทึกผลที่หน้า check แสดง.

**ผลที่คาดหวัง:** check ใช้ OIDC, API ปิด anonymous access และผลปรากฏหลังรอบตรวจ/ingestion.

**บันทึกจริง / หลักฐาน:** check config ______ · service-agent binding ______ · last check/time range ______ · actual result ______

**ถ้าไม่ผ่าน:** ตรวจ service agent, invoker binding, host/SSL/port และ /healthz; อย่าเปิด endpoint เป็น public.

### Task T12 — เก็บ Baseline และ Error Budget

1. ส่ง valid traffic 200 ครั้ง ห่างกัน 100 ms; bounded script จำกัดสูงสุด 500 ครั้งต่อรอบ:
```bash
export API_URL="$(terraform -chdir="$LAB19_DIR/infra/runtime" output -raw api_uri)"
python3 "$LAB19_DIR/scripts/traffic.py" \
  --api-url "$API_URL" --mode valid --count 200 --interval-ms 100 --verify-status \
  | tee /tmp/lab19-baseline.jsonl
```
2. ตรวจ summary: HTTP 202 จำนวน 200 และ status reads/readable ตรงกับ task IDs.
3. รอ log metric แล้วตรวจ eligible good/bad, latency distribution, Pub/Sub oldest age และ SQL CPU/connections. จดเวลาที่เริ่ม/จบและ actual.
4. หากรันซ้ำให้แยก run/time range; อย่ารวมคนละรอบ.

**ผลที่คาดหวัง:** tool รายงาน 200 accepted; task status อ่านได้ครบ. 200 requests เป็น sample ของ Lab ไม่ใช่ capacity benchmark หรือหลักฐาน SLO 7 วัน.

**บันทึกจริง / หลักฐาน:** start/end ______ · HTTP counts ______ · accepted/readable ______ · eligible good/bad ______ · p95/oldest age/CPU ______ · metric delay ______

**ถ้าไม่ผ่าน:** หยุดก่อน fault drill; ตรวจ API logs, Pub/Sub backlog, Worker/SQL. อย่าเพิ่มจำนวนเกิน limit เพื่อเร่ง dashboard.

### Task T13 — Change Request CR-19-01: ลดเสียงเตือนจาก isolated error

เปรียบเทียบ policy baseline ชั่วคราว “eligible 5xx หนึ่งครั้งก็เปิด incident” กับ SLO burn policies. เปิด baseline เฉพาะ Lab project; policy ส่ง email ไปยัง notification channel ของ Lab.

1. ตั้ง cr_baseline_single_5xx_enabled = false และ api_fault_mode = "none" ใน runtime tfvars; อ่าน plan แล้ว Apply. ทดสอบ expected 4xx:
```bash
cd "$LAB19_DIR/infra/runtime"
nano terraform.tfvars
terraform plan -out=runtime-cr-off.tfplan
terraform show -no-color runtime-cr-off.tfplan
terraform apply runtime-cr-off.tfplan
export API_URL="$(terraform output -raw api_uri)"
python3 "$LAB19_DIR/scripts/traffic.py" --api-url "$API_URL" --mode invalid --count 10 --interval-ms 100
```
บันทึก 422 ทั้ง 10 และตรวจไม่เข้า eligible metric.
2. เปิด cr_baseline_single_5xx_enabled = true โดย fault mode ยัง none; ตรวจ plan และ Apply:
```bash
nano terraform.tfvars
terraform plan -out=runtime-cr-baseline.tfplan
terraform show -no-color runtime-cr-baseline.tfplan
terraform apply runtime-cr-baseline.tfplan
```
ยืนยันใน Alerting ว่า policy Lab 19 CR baseline · any eligible 5xx ปรากฏ.
3. สร้าง token, API URL และ request payload สำหรับ error เดี่ยว:
```bash
export TOKEN="$(gcloud auth print-identity-token)"
export API_URL="$(terraform output -raw api_uri)"
export IDEMPOTENCY_KEY="lab19-cr-noisy-$(date -u +%Y%m%d%H%M%S)"
python3 - <<'PY'
import json
import os

payload = {
    "idempotency_key": os.environ["IDEMPOTENCY_KEY"],
    "items": [{"sku": "DEMO-CR", "quantity": 1, "unit_price_cents": 100}],
}
with open("/tmp/lab19-cr-task.json", "w", encoding="utf-8") as handle:
    json.dump(payload, handle)
PY
```
4. ตั้ง api_fault_mode = "5xx" ชั่วคราว, อ่าน/Apply plan แล้วส่งหนึ่ง request:
```bash
nano terraform.tfvars
terraform plan -out=runtime-cr-one-error.tfplan
terraform show -no-color runtime-cr-one-error.tfplan
terraform apply runtime-cr-one-error.tfplan
HTTP_CODE="$(curl -sS -o /tmp/lab19-cr-response.json -w '%{http_code}' \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  --data-binary @/tmp/lab19-cr-task.json "$API_URL/tasks")"
printf 'isolated_error_http=%s\n' "$HTTP_CODE"
test "$HTTP_CODE" = "503"
```
5. รอ metric/Alerting evaluation; ตรวจ incident/email จาก noisy baseline และบันทึก actual. หากไม่เกิด ให้ตรวจ outcome=bad metric ก่อนสรุป.
6. **ก่อนส่ง request รอบถัดไป**, ตั้ง cr_baseline_single_5xx_enabled = false และ api_fault_mode = "none"; สร้าง plan/Apply:
```bash
nano terraform.tfvars
terraform plan -out=runtime-cr-target.tfplan
terraform show -no-color runtime-cr-target.tfplan
terraform apply runtime-cr-target.tfplan
```
ยืนยัน noisy baseline policy ถูกลบและบันทึก incident state ที่ Console แสดง.
7. ทดสอบ isolated 503 รอบที่สองโดย baseline alert คง false. ตั้ง api_fault_mode = "5xx"; plan/Apply แล้วส่ง payload ที่มี key ใหม่:
```bash
nano terraform.tfvars
terraform plan -out=runtime-cr-target-isolated.tfplan
terraform show -no-color runtime-cr-target-isolated.tfplan
terraform apply runtime-cr-target-isolated.tfplan
export IDEMPOTENCY_KEY="lab19-cr-target-$(date -u +%Y%m%d%H%M%S)"
python3 - <<'PY'
import json
import os

payload = {
    "idempotency_key": os.environ["IDEMPOTENCY_KEY"],
    "items": [{"sku": "DEMO-CR", "quantity": 1, "unit_price_cents": 100}],
}
with open("/tmp/lab19-cr-target-task.json", "w", encoding="utf-8") as handle:
    json.dump(payload, handle)
PY
HTTP_CODE="$(curl -sS -o /tmp/lab19-cr-target-response.json -w '%{http_code}' \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  --data-binary @/tmp/lab19-cr-target-task.json "$API_URL/tasks")"
printf 'isolated_error_http=%s\n' "$HTTP_CODE"
test "$HTTP_CODE" = "503"
```
8. คืน api_fault_mode = "none" แล้วทำ plan/Apply ทันที:
```bash
nano terraform.tfvars
terraform plan -out=runtime-cr-complete.tfplan
terraform show -no-color runtime-cr-complete.tfplan
terraform apply runtime-cr-complete.tfplan
```
เมื่อ baseline policy ปิดแล้ว SLO burn policy ไม่ควร page จาก isolated error ที่ยังอยู่ใน budget; ตรวจ active incidents และจด actual.

**ผลที่คาดหวัง:** 422 ไม่เข้า SLI; baseline any-5xx แจ้ง isolated 503; หลัง CR policy นั้นถูกลบ แต่ burn policies ยัง enabled และ isolated error ไม่ page. ใช้หลักฐานจริง ไม่ถือ Expected เป็น PASS.

**บันทึกจริง / หลักฐาน:** policy ก่อน/หลัง ______ · 422 exclusion ______ · 503 timestamps ______ · incident/email ที่เกิดจริง ______ · policies enabled หลัง CR ______ · plan/apply ______

**ถ้าไม่ผ่าน:** 422 เข้า metric ให้ตรวจ eligible; baseline ไม่ alert ตรวจ label/alignment/channel; หลัง CR ยัง alert ตรวจ policy ถูกลบ, baseline good count, SLO window. ห้ามปิด burn alerts เพื่อให้ดูผ่าน.

### Task T14 — Fault drill: API sustained 5xx และ recovery

1. ตั้ง API fault 5xx, worker none, noisy baseline false; plan ต้องแสดงเฉพาะ API revision config เปลี่ยน:
```bash
cd "$LAB19_DIR/infra/runtime"
nano terraform.tfvars
terraform plan -out=runtime-api-fault.tfplan
terraform show -no-color runtime-api-fault.tfplan
terraform apply runtime-api-fault.tfplan
```
2. ส่ง valid requests 30 ครั้งแบบ bounded; exit 1 เป็นผลที่คาดเพราะ tool คาด 202 แต่ได้ 503:
```bash
export API_URL="$(terraform output -raw api_uri)"
python3 "$LAB19_DIR/scripts/traffic.py" \
  --api-url "$API_URL" --mode valid --count 30 --interval-ms 100 \
  > /tmp/lab19-api-fault.jsonl || test "$?" -eq 1
tail -n 8 /tmp/lab19-api-fault.jsonl
```
3. ตรวจ API logs, eligible bad metric, availability SLO, fast-burn policy และ incident. บันทึก detection/user HTTP failure/alert delivery; alert timing ขึ้นกับ ingestion/evaluation.
4. คืน api_fault_mode = "none", สร้าง plan/Apply แล้วส่ง valid request หนึ่งครั้งและตรวจ 202/Task status:
```bash
nano terraform.tfvars
terraform plan -out=runtime-api-recovered.tfplan
terraform show -no-color runtime-api-recovered.tfplan
terraform apply runtime-api-recovered.tfplan
export API_URL="$(terraform output -raw api_uri)"
python3 "$LAB19_DIR/scripts/traffic.py" --api-url "$API_URL" --mode valid --count 1 --interval-ms 0 --verify-status
```
5. หลัง recovery evidence ครบ จึง resolve incident พร้อมเหตุผล.

**ผลที่คาดหวัง:** fault เป็น 503 และเข้า eligible bad; sustained failure มี fast-burn signal เมื่อข้อมูลพร้อม; หลัง recovery request ใหม่กลับ flow ปกติ.

**บันทึกจริง / หลักฐาน:** fault revision ______ · HTTP 503 count ______ · bad metric/SLO ______ · incident/detection ______ · recovery time ______ · resolve note ______

**ถ้าไม่ผ่าน:** exit 2 ของ script คือ tool failure ไม่ใช่ expected fault. ถ้าไม่ alert ตรวจ sample, 60m filter, metric delay/channel; อย่าเพิ่ม traffic เกิน 30 ต่อรอบ.

### Task T15 — Fault drill: Worker retries, DLQ และ bounded redrive

1. ตั้ง worker_fault_mode = "503", worker_delay_ms = 0, API none, baseline alert false; plan ต้องแสดงเฉพาะ Worker revision config:
```bash
cd "$LAB19_DIR/infra/runtime"
nano terraform.tfvars
terraform plan -out=runtime-worker-fault.tfplan
terraform show -no-color runtime-worker-fault.tfplan
terraform apply runtime-worker-fault.tfplan
```
2. สร้าง task ใหม่ขณะ Worker ตอบ 503 แล้วเก็บ task ID:
```bash
export TOKEN="$(gcloud auth print-identity-token)"
export API_URL="$(terraform output -raw api_uri)"
export IDEMPOTENCY_KEY="lab19-worker-fault-$(date -u +%Y%m%d%H%M%S)"
python3 - <<'PY'
import json
import os

payload = {
    "idempotency_key": os.environ["IDEMPOTENCY_KEY"],
    "items": [{"sku": "DEMO-DLQ", "quantity": 1, "unit_price_cents": 500}],
}
with open("/tmp/lab19-dlq-task.json", "w", encoding="utf-8") as handle:
    json.dump(payload, handle)
PY
curl -fsS -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  --data-binary @/tmp/lab19-dlq-task.json "$API_URL/tasks" | tee /tmp/lab19-dlq-create.json
export TASK_ID="$(python3 -c 'import json; print(json.load(open("/tmp/lab19-dlq-create.json"))["task_id"])')"
```
3. Poll ไม่เกิน 20 นาที; ระหว่างรอดู oldest message, Worker failures และ DLQ:
```bash
for attempt in $(seq 1 120); do
  if curl -fsS -H "Authorization: Bearer $TOKEN" "$API_URL/tasks/$TASK_ID" -o /tmp/lab19-dlq-status.json; then
    export TASK_STATUS="$(python3 -c 'import json; print(json.load(open("/tmp/lab19-dlq-status.json"))["status"])')"
    printf 'attempt=%s status=%s\n' "$attempt" "$TASK_STATUS"
    [ "$TASK_STATUS" = "FAILED" ] && break
  fi
  sleep 10
done
test "$TASK_STATUS" = "FAILED"
```
4. แก้ root cause, คืน worker_fault_mode = "none", plan/Apply แล้วตรวจ Worker Ready และ task ยัง FAILED:
```bash
nano terraform.tfvars
terraform plan -out=runtime-worker-recovered.tfplan
terraform show -no-color runtime-worker-recovered.tfplan
terraform apply runtime-worker-recovered.tfplan
gcloud run services describe lab19-task-worker --project="$PROJECT_ID" --region="$REGION" --format="yaml(status.conditions)"
```
5. ติดตั้ง Pub/Sub client ใน Cloud Shell virtualenv และ login ADC ถ้ายังไม่ได้เตรียม:
```bash
python3 -m venv "$HOME/.venvs/lab19"
"$HOME/.venvs/lab19/bin/python" -m pip install -r "$LAB19_DIR/app/requirements.txt"
gcloud auth application-default login
```
6. Redrive ไม่เกินหนึ่ง message; script publish ไป topic ก่อน ACK จาก reader subscription:
```bash
"$HOME/.venvs/lab19/bin/python" "$LAB19_DIR/scripts/redrive_dlq.py" \
  --project "$PROJECT_ID" --max-messages 1
```
7. Poll status ของ task เดิมจน SUCCEEDED; ยืนยัน task ID/result และ DLQ reader backlog หลังจบ.

**ผลที่คาดหวัง:** push retries ถึง DLQ, status handler เปลี่ยนเป็น FAILED, หลัง restore/redrive status เดิมเป็น SUCCEEDED; ACK เกิดหลัง publish สำเร็จ.

**บันทึกจริง / หลักฐาน:** task ID ______ · attempts ที่เห็น ______ · DLQ timestamp/count ______ · status FAILED ______ · redrive output ______ · status/result สุดท้าย ______ · backlog หลังจบ ______

**ถ้าไม่ผ่าน:** หากไม่ FAILED ใน 20 นาทีให้หยุด redrive ตรวจ max attempts, DLQ IAM/service agent, OIDC status route และ Worker logs. หาก publish fail script ต้องไม่ ACK; แก้ IAM ก่อนลองซ้ำ.

### Task T16 — สรุป Incident timeline และ Case Study จาก Actual

1. เก็บ timeline จาก request logs, Monitoring incident, dashboard และ revision; ใช้เวลา/ค่าในหลักฐานจริง.
2. กรอกตารางท้าย README แยก Expected กับ Actual; เลือกภาพ/JSON ที่ไม่เผย token, email, private IP หรือ payload.
3. สรุปเหตุผลที่แยก user SLI จาก queue health, ผล CR-19-01, single-zone boundary และสิ่งที่ยังไม่พิสูจน์. อย่าเรียก sample baseline ว่า production capacity.

**ผลที่คาดหวัง:** incident timeline, recovery proof และ CR before/after ย้อนตรวจได้; ไม่มี Cloud PASS ที่ไม่ได้ทดสอบ.

**บันทึกจริง / หลักฐาน:** start/detect/mitigate/recover/resolve ______ · user impact ______ · error-budget context ______ · CR comparison ______ · evidence/query links ______ · limitations ______

### Task T17 — Cleanup และตรวจ resource คงเหลือ

Cleanup ลบ Runtime/Monitoring ก่อน Cloud SQL/VPC. ตรวจ project ID ซ้ำก่อน destroy; ห้ามลบทั้ง project.

1. คืน API/Worker faults เป็น none, delay 0, noisy baseline false; Apply Runtime และหยุด traffic.
2. เก็บ evidence ที่ไม่ sensitive, resource inventory และตรวจไม่มี incident เปิด.
3. สร้าง/อ่าน Runtime destroy plan:
```bash
cd "$LAB19_DIR/infra/runtime"
terraform plan -destroy -out=runtime-destroy.tfplan
terraform show -no-color runtime-destroy.tfplan
```
อ่านรายการแล้วจึง Apply:
```bash
terraform apply runtime-destroy.tfplan
```
4. ลบ migration Job ที่สร้างด้วย gcloud:
```bash
gcloud run jobs delete lab19-schema-migrate --project="$PROJECT_ID" --region="$REGION"
```
5. สร้างและอ่าน Foundation destroy plan; ตรวจ project/resource ก่อน Apply:
```bash
cd "$LAB19_DIR/infra/foundation"
terraform plan -destroy -out=foundation-destroy.tfplan
terraform show -no-color foundation-destroy.tfplan
```
จากนั้นยืนยัน destroy แบบ interactive:
```bash
terraform apply foundation-destroy.tfplan
```
6. ตรวจ Cloud Run services/jobs, SQL instances, Pub/Sub topics/subscriptions, VPC/subnet และ Monitoring policies. APIs อาจยัง enabled เพราะ disable_on_destroy=false; บันทึกใน inventory.
7. เก็บหรือลบ local state ตามนโยบาย; ห้าม commit tfstate, tfvars, plan files, tokens หรือ output ที่ระบุตัวบุคคล.

**ผลที่คาดหวัง:** Runtime/Foundation resources และ migration Job ถูกลบ; inventory ตรวจแล้ว ไม่มี Lab19 service/database/network/queue คงเหลือ.

**บันทึกจริง / หลักฐาน:** Runtime destroy ______ · Job deletion ______ · Foundation destroy ______ · inventory/time ______ · resource ที่ยังเหลือ/เหตุผล ______ · billing check ______

**ถ้าไม่ผ่าน:** ถ้า destroy ติด dependency ตรวจ Runtime state ก่อน Foundation. ถ้าลบ resource มือแล้ว ให้ refresh/plan และอ่าน diff ก่อน Apply; ห้ามลบ VPC/SQL ใน Console เพื่อข้าม state.

## Runbook เมื่อไม่เป็นไปตามคาด

| อาการ | ตรวจตามลำดับ | การกู้/จุดหยุด |
|---|---|---|
| API anonymous สำเร็จ | Cloud Run IAM policy, invoker setting, request token | หยุดและคืน IAM-only; ห้ามใช้ allUsers |
| API 403 สำหรับ operator | active identity, token, API invoker binding, project | ใช้ identity ที่อนุมัติและออก token ใหม่ |
| POST 503 ก่อน fault drill | API logs, Pub/Sub publish role, SQL Connector/IAM DB user | ตรวจ API SA, Cloud SQL roles และ private egress |
| task ค้าง QUEUED | push subscription/OIDC, Worker logs, backlog age, SQL IAM | แก้ root cause ก่อน redrive; อย่าสร้าง task ใหม่เพื่อกลบปัญหา |
| task FAILED แต่ DLQ ไม่เห็น | dead-letter policy/topic, Pub/Sub service-agent roles, status OIDC route | ตรวจ delivery/logs; อย่า ACK ด้วยมือ |
| redrive ไม่ publish/ACK | Cloud Shell ADC, subscriber role, topic publisher role | script ACK หลัง publish เท่านั้น; แก้ IAM แล้ว retry |
| Logs มีแต่ SLO ไม่มี | log metric descriptor, label/filter, SLO service, ingestion delay | สร้าง bounded traffic และรอ; อย่าแก้ goal โดยไม่เข้าใจ filter |
| ไม่มี alert/email | channel verification, data, enabled policy, alignment/burn window | ตรวจ signal ก่อน; low volume/no data ไม่ยืนยัน policy |
| Cloud SQL timeout | VPC/subnet, PSA, private IP, Connector log/roles | อย่าเพิ่ม public IP; ซ่อม private path |
| Terraform plan แสดง resource นอก Lab | active project, tfvars, state root | หยุดก่อน Apply และตรวจ Project ID/state |

## ไฟล์ใน Lab

- README.md — brief, architecture, T00–T17, Actual/Evidence, troubleshooting, Case Study, cleanup
- assets/solution.svg, assets/solution.html — diagram source/preview ตาม Diagram Design Personal Custom จาก ZIP
- assets/diagram-provenance.json, assets/icons/ — pinned official icon provenance/attribution
- app/ — Task API, idempotent Worker, schema migration, Cloud Build config, Dockerfile/dependencies
- infra/foundation/, infra/runtime/ — Terraform stacks และ example tfvars
- scripts/traffic.py, scripts/redrive_dlq.py — bounded traffic และ DLQ redrive tools
- tests/ — app, design, infrastructure, brief และ Guide checks; ไม่ใช่ผล Cloud
- [Diagram Design style guide](../../docs/diagram-style.md)

## References

- [Cloud Run request tracing](https://docs.cloud.google.com/run/docs/trace) — sampled traces/trace context
- [Cloud Run logging](https://docs.cloud.google.com/run/docs/logging) — structured logs
- [Cloud Monitoring log-based metrics](https://docs.cloud.google.com/logging/docs/logs-based-metrics)
- [Cloud Monitoring metric catalog](https://docs.cloud.google.com/monitoring/api/metrics)
- [Cloud Monitoring SLO concepts](https://docs.cloud.google.com/stackdriver/docs/solutions/slo-monitoring)
- [SLOs from logs-based metrics](https://docs.cloud.google.com/stackdriver/docs/solutions/slo-monitoring/sli-metrics/logs-based-metrics)
- [Burn-rate alerting](https://docs.cloud.google.com/stackdriver/docs/solutions/slo-monitoring/alerting-on-budget-burn-rate)
- [Authenticated uptime checks](https://docs.cloud.google.com/monitoring/uptime-checks)
- [Authenticated Pub/Sub push](https://docs.cloud.google.com/pubsub/docs/authenticate-push-subscriptions)
- [Pub/Sub delivery failure and DLQ](https://docs.cloud.google.com/pubsub/docs/handling-failures)
- [Cloud Run to Cloud SQL](https://docs.cloud.google.com/sql/docs/postgres/connect-run)
- [Cloud SQL IAM authentication](https://docs.cloud.google.com/sql/docs/postgres/iam-authentication)
- [Cloud SQL IAM users](https://docs.cloud.google.com/sql/docs/postgres/add-manage-iam-users)
- [Cloud SQL Python Connector](https://docs.cloud.google.com/sql/docs/postgres/connect-connectors)
- [Cloud Run Direct VPC egress](https://docs.cloud.google.com/run/docs/configuring/vpc-direct-vpc)
- [Deploy Cloud Run jobs](https://docs.cloud.google.com/sdk/gcloud/reference/run/jobs/deploy)
- [Execute Cloud Run jobs](https://docs.cloud.google.com/sdk/gcloud/reference/run/jobs/execute)
- [Submit Cloud Build](https://docs.cloud.google.com/sdk/gcloud/reference/builds/submit)
- [Cloud Build custom service-account logging](https://docs.cloud.google.com/build/docs/securing-builds/configure-user-specified-service-accounts)
- [Cloud Monitoring alert policy resource](https://registry.terraform.io/providers/hashicorp/google/latest/docs/resources/monitoring_alert_policy)
- [Google Cloud icons](https://cloud.google.com/icons)

## สรุป Case Study

**โจทย์:** ทีม Commerce มี asynchronous Task API และต้องเห็น reliability ที่ลูกค้าสัมผัส พร้อมแยกเหตุ API, Queue, Worker และฐานข้อมูล.

**การออกแบบ:** IAM-authenticated Cloud Run API/Worker, Pub/Sub push OIDC, Cloud SQL private IP ผ่าน Direct VPC egress/PSA, SLI/SLO, burn alerts, uptime check, DLQ status handler และ bounded redrive. Diagram ใช้ Diagram Design Personal Custom จาก ZIP พร้อม attribution/pinned icon provenance.

**ผลจริงจากการทำ Lab:** กรอกหลังทำเท่านั้น; ห้ามนำ Expected มาแทน Actual.

| ประเด็น | Actual | Evidence |
|---|---|---|
| Baseline eligible good/bad และ latency | ______ | ______ |
| Availability/latency SLO state และช่วงข้อมูล | ______ | ______ |
| API fault: detect → mitigate → recover | ______ | ______ |
| Worker/DLQ: failure → fix → redrive → success | ______ | ______ |
| CR-19-01 noisy policy ก่อน/หลัง | ______ | ______ |
| ค่าใช้จ่ายและ inventory หลัง cleanup | ______ | ______ |
| ข้อจำกัด (single-zone, sample duration, trace sampling, metric delay) | ______ | ______ |

**Cloud verification:** Not run จนกว่าผู้เรียนจะสร้าง/ทดสอบบน project ของตนและบันทึก Actual พร้อมหลักฐาน
