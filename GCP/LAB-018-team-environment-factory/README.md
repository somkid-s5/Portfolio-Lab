# Lab 18 — แพลตฟอร์มสร้าง Environment ให้ทีมใหม่

> **สถานะ:** Guide-ready — [CI #401](https://github.com/somkid-s5/Portfolio-Lab/actions/runs/40162370516) ผ่าน 71/71 repository jobs และ Lab 18 ผ่าน 6/6 checks  
> **Cloud verification:** Not run — ไม่มีการสร้าง GCP resources ในงานจัดทำคู่มือนี้  
> **มาตรฐาน Diagram:** Diagram Design Personal Custom จาก ZIP ตาม [docs/diagram-style.md](../../docs/diagram-style.md)

## ภาพรวม Solution

ทีม Platform ต้องเปิด Dev และ Staging ให้ทีม Commerce โดยแยก project, สิทธิ์, ค่าใช้จ่าย และ log จาก profile ชุดเดียว Solution นี้ใช้ Terraform สร้าง Projects ใต้ Folder ที่องค์กรจัดเตรียมไว้ แล้วเปิด Artifact Registry, Cloud Run Status API, project budget, IAM และส่ง log ไป Cloud Logging bucket ส่วนกลางตาม region ที่อนุมัติ

Terraform seeder จัดการ lifecycle ของ Project เท่านั้น; หลังสร้างแล้วผู้ดูแลกำหนด IAM ให้ factory/seeder ผ่าน controlled handoff และถอน Owner ของ creator ก่อนใช้งานประจำ Factory ทำงานด้วย service account แบบ keyless ผ่าน impersonation และเก็บ state ใน GCS แยก prefix ตาม Environment

Lab ไม่สร้าง Organization, Folder หรือ Billing Account และไม่แก้ Organization Policy ตัวอย่าง project ID, group และอีเมลใน config เป็นค่าตัวอย่าง ต้องเปลี่ยนเป็นค่าที่มีจริงในองค์กรก่อน Cloud execution

## สถานการณ์และปัญหา

ทีม commerce ขอ Dev และ Staging เพื่อทดสอบ Status API ก่อนเริ่มงาน ทีมเดิมใช้ Project ร่วมกัน ให้ Editor กว้าง ๆ และตั้งชื่อ resource ไม่สม่ำเสมอ ทำให้แยกการเข้าถึง ค่าใช้จ่าย drift และเจ้าของ resource ได้ยาก

ทีม Platform ต้องส่งมอบ Environment ที่สร้างซ้ำได้ มี owner/team/environment/cost labels, budget alert, authenticated service, central logs และขั้นตอนถอนสิทธิ์สร้าง Project หลัง controlled handoff

## Requirements

| ID | Requirement | เกณฑ์พิสูจน์ |
|---|---|---|
| R01 | Dev และ Staging เป็นคนละ Project ใต้ Folder ที่กำหนด | Project ID และ parent ใน Resource Manager ตรงกับ profile |
| R02 | ใช้ profile และ Terraform roots เดียวกัน โดยรับ team, project ID, region, group และ budget เป็น input | profile ที่ขาดค่า project ID ซ้ำ หรือ region นอก allowlist ถูกปฏิเสธก่อน plan |
| R03 | ใช้ seeder เฉพาะสร้างและ handoff; ถอน Owner ของผู้สร้างหลัง factory ได้ role ที่ต้องใช้ | IAM ก่อน/หลัง handoff แสดงว่าไม่มี Owner/Editor ค้างใน Environment |
| R04 | Dev และ Staging ใช้ group และ runtime identity แยกกัน ไม่มี service-account key | IAM ไม่มี binding ข้าม Environment; runtime ใช้ SA คนละ Project |
| R05 | เก็บ Terraform state ใน GCS ที่เปิด Versioning, UBLA และ public access prevention พร้อม prefix แยก | ตรวจ bucket settings, state object และพฤติกรรม lock; ห้าม force-unlock โดยไม่ตรวจ lock |
| R06 | มี budget แยก Project และ threshold notification | Budget filter ระบุ project number, threshold และผู้รับ; alert ไม่ใช่ spending cap |
| R07 | Project labels มี owner, team, environment, cost_center และ managed_by | profile validator ปฏิเสธ label ที่ขาด; inventory ตรง profile |
| R08 | มี Authenticated Cloud Run Status API พร้อม health check | /healthz ตอบข้อมูล Environment เมื่อมีสิทธิ์; unauthenticated และบัญชีที่ไม่มี invoker ถูกปฏิเสธ |
| R09 | Status API logs ถูกส่งไป central regional log bucket | ค้น log ของทั้งสอง Project ที่ bucket ปลายทาง และตรวจ role ของ sink writer |
| R10 | การเปลี่ยน label นอก Terraform แสดง drift และคืนค่าตาม profile ได้ | เก็บ plan ก่อนและหลังแก้ drift |
| R11 | Change Request ต้องผ่าน region/access policy ก่อนสร้าง Environment | asia-east1 ถูกปฏิเสธก่อนอนุมัติ; contractor ดู metadata ได้แต่ไม่มี invoker/deploy |
| R12 | Cleanup ตรวจ inventory ก่อนลบ Project และเก็บ Foundation state/log ต่อ | ยืนยัน Project ที่จะลบ; state bucket และ central log buckets ยังคงอยู่ |

## Acceptance Criteria

1. สร้าง dev และ staging ด้วย shared profile โดย project ID, labels และ IAM ไม่ทับกัน
2. สมาชิก Dev group เรียก Dev ได้แต่เรียก Staging ไม่ได้; ทดสอบกลับทิศด้วยผู้ใช้ Staging แยกบัญชี
3. หลัง handoff ไม่มี roles/owner หรือ roles/editor ใน Environment projects; seeder เหลือเพียง Project Viewer/Deleter
4. Terraform roots ใช้ GCS prefix คนละชุดต่อ Environment; state operation ใช้ backend locking และไม่มี force-unlock แบบเดาสุ่ม
5. Budget filter มีเฉพาะ project number ที่กำหนดและส่ง threshold alerts; budget ไม่จำกัดการใช้เงินจริง
6. Log จาก Status API ปรากฏใน bucket ส่วนกลางหลัง grant roles/logging.logWriter และ roles/logging.bucketWriter ให้ sink writer
7. เปลี่ยน label ด้วยมือแล้ว plan แสดง drift และ apply คืนค่าได้
8. Dataops region ที่ยังไม่อนุมัติไม่ผ่าน validator; หลังอนุมัติ contractor ไม่มี roles/run.invoker หรือ deploy permission
9. Cleanup ลบเฉพาะ Environment ที่ยืนยัน; Foundation Project, remote state และ log buckets คงอยู่
10. CI ตรวจ App, profile, Terraform syntax, Guide และ Diagram โดยไม่เรียก GCP API

## Architecture decisions

| หัวข้อ | การตัดสินใจ |
|---|---|
| Environment boundary | หนึ่ง Project ต่อหนึ่ง Environment |
| Baseline region | asia-southeast1 สำหรับ Cloud Run และ bucket ส่วนกลาง; region อื่นต้องอยู่ใน allowlist |
| Resource hierarchy | ใช้ Organization/Folder ที่มีอยู่; ไม่สร้าง/แก้ hierarchy และไม่เปลี่ยน Organization Policy |
| Project creation | Terraform seeder จัดการ Project lifecycle; ผู้ดูแลผูก IAM ให้ factory/seeder แล้วถอน Owner ของ creator หลัง handoff |
| Terraform state | GCS backend, UBLA, public access prevention, object versioning และ prefix ต่อ root/Environment |
| IAM | ไม่มี Owner/Editor ประจำ; team group มี Artifact Registry Writer, Cloud Run Developer, Invoker และ actAs เฉพาะ runtime SA |
| Runtime | Cloud Run Status API private by IAM; runtime service account ไม่มีสิทธิ์ GCP เพิ่ม |
| Logs | project-level sink ส่งเฉพาะ status-api ไป regional Cloud Logging bucket |
| Sink permissions | log bucket ไม่มี IAM policy ราย bucket; ให้ writer มี roles/logging.logWriter และ roles/logging.bucketWriter ที่ Foundation Project ซึ่งเป็น **Project-wide IAM scope** |
| Budget | threshold email alert; เป็น alert-only ไม่ใช่ quota หรือ spending cap |
| Change Request | อนุมัติ region/data location ก่อน; roles/run.viewer ดู metadata ได้แต่ไม่ให้ invoke |
| Cleanup | ลบ Environment ทีละ Project หลังตรวจ inventory; ห้าม destroy Foundation root |

Google Cloud สร้าง roles/owner ให้ principal ที่สร้าง Project โดยอัตโนมัติ จึงต้องทำ controlled handoff: ให้ factory มี role ที่จำเป็น, ให้ seeder มี Project Viewer/Deleter สำหรับตรวจและ cleanup, ตรวจ policy แล้วถอน Owner ของ creator ก่อนงานประจำ [Project IAM access control](https://docs.cloud.google.com/resource-manager/docs/access-control-proj)

GCS backend ต้องใช้ bucket ที่มีอยู่ก่อน init; backend รองรับ state locking และ HashiCorp แนะนำเปิด Object Versioning เพื่อกู้ state จากการแก้/ลบผิดพลาด [Terraform GCS backend](https://developer.hashicorp.com/terraform/language/backend/gcs)

Cloud Logging log bucket ไม่มี IAM allow policy ของตัวเอง สำหรับ log ข้าม Project ให้ sink writer มี Logs Writer และ Logs Bucket Writer ที่ Project ปลายทาง สิทธิ์ที่ Project scope จึงครอบคลุม log buckets ใน Project นั้น ไม่ใช่ bucket เดียว [Cloud Logging destination permissions](https://docs.cloud.google.com/logging/docs/export/configure_export_v2) [Cloud Logging IAM](https://docs.cloud.google.com/logging/docs/access-control)

## Cost boundary

Cloud Run ตั้ง min instances เป็น 0 และ max เป็น 2; Artifact Registry เก็บ image จนลบ; Cloud Logging มี ingestion/retention cost และ egress อาจมีค่าใช้จ่าย Project budget เป็น alert-only ไม่ได้จำกัดค่าใช้จ่ายโดยอัตโนมัติ และไม่หยุดการใช้เงินจริง ตรวจ billing currency/เจ้าของงบก่อน apply และ cleanup Environment หลังเก็บหลักฐาน อย่าใช้ budget alert แทนการอนุมัติงบ

## Solution diagram

![Lab 18 environment factory architecture](assets/solution.svg)

ภาพนี้เป็น architecture ที่ออกแบบไว้ ไม่ใช่ผลจากการสร้าง GCP จริง ลูกศรแสดง Terraform/state flow และ log routing; dev/staging อยู่คนละ Project

## Change Request — ทีม dataops

ทีม dataops ขอ Environment ที่ region asia-east1 และให้ contractor group ตรวจ metadata ของ Cloud Run ได้ โดยไม่มีสิทธิ์ deploy หรือเรียก service

- Validator ต้องปฏิเสธ region ก่อน data owner อนุมัติ
- หลังอนุมัติ ให้เพิ่ม region ใน allowlist, เพิ่ม regional log bucket ใน Foundation และใส่เลขอ้างอิงอนุมัติใน profile
- เพิ่ม contractor_group เฉพาะ Environment ที่อนุมัติ; factory ผูก roles/run.viewer กับ service นั้นเท่านั้น
- ตรวจ plan/IAM diff และทดสอบว่า contractor เรียก /healthz ไม่ได้
- ห้ามใส่ contractor เข้า Dev/Staging group และห้ามให้ roles/run.invoker, deploy role หรือ Secret access

## ก่อนเริ่ม Cloud execution

| สิ่งที่ต้องมี | เหตุผล / ขอบเขต |
|---|---|
| Organization และ team Folder ที่มีอยู่แล้ว | Lab สร้าง Projects ใต้ parent ที่มีอยู่เท่านั้น |
| Principal ที่มี roles/resourcemanager.projectCreator บน Folder | ใช้สร้าง Project ได้เฉพาะตำแหน่งนั้น |
| ผู้ทำ Lab มีสิทธิ์ผูก billing; Factory SA ได้ Billing Account Costs Manager ตามอนุมัติ | สร้าง Projects และ budgets |
| Foundation Project ที่อนุมัติ | เก็บ remote state และ log buckets |
| Google Groups ที่มีสมาชิกทดสอบแยกกัน | พิสูจน์การแยก Dev/Staging |
| Docker, gcloud, Terraform 1.9.8+, Python 3.10+ และ curl | build/push image, run Terraform และ probe |
| Budget ใช้สกุลเงินเดียวกับ Billing Account; notification email มีจริง | budget ต้องตรง currency และ Monitoring email channel อาจต้องยืนยัน |

Project creation ต้องมี resourcemanager.projects.create; การ link billing ต้องมี billing roles ที่เหมาะสม [Create and manage projects](https://docs.cloud.google.com/resource-manager/docs/creating-managing-projects) [Cloud Billing budget access](https://docs.cloud.google.com/billing/docs/how-to/budget-api-access-control)

หากไม่มี Organization/Folder/Billing Account ที่อนุมัติ ให้ทำ App, profile, Docker และ CI checks ต่อได้ แต่บันทึก Cloud execution เป็น Not run ห้ามแทนด้วย project ส่วนตัวแล้วอ้างว่า project isolation ผ่าน ตัวอย่าง group/email @example.com และ project ID suffix demo ต้องเปลี่ยนก่อน apply

## ขั้นตอนทำ Lab

### Task 00 — กำหนดขอบเขตและหลักฐาน

อ่านโจทย์และ R01–R12 ก่อน เริ่มเฉพาะ Foundation Project และ Environment สำหรับ Lab นี้ที่ได้รับอนุมัติ อย่ารันคำสั่งสร้าง resource ใน production project

บันทึกผู้อนุมัติ parent Folder, Foundation project, billing account, Dev/Staging group, budget owner, region และช่วงเวลาทำงานลงช่อง Case Study ด้านล่าง ห้ามใส่ access token, key, state file หรือ secret

**ผลที่คาดหวัง:** มี scope, owner และ resource ที่จะสร้างก่อนเปิด Cloud Console

**บันทึกจริง / หลักฐาน:** ผู้อนุมัติ: ______; Folder: ______; Foundation Project: ______; Environment projects: ______; ช่วงเวลา: ______

### Task 01 — ตรวจสิทธิ์และค่าองค์กร

ใน Google Cloud Console เลือก Organization/Folder เป้าหมาย ตรวจว่าผู้รัน Terraform มี Project Creator บน Folder และสิทธิ์ link Project กับ Billing Account ตรวจว่า Foundation operator มี Storage Admin/Project IAM Admin ตามที่ผู้ดูแลมอบให้

ตรวจ Google Groups ใน Admin/Groups ว่ามี Dev, Staging และ Platform Operators groups จริง และเตรียมผู้ใช้ทดสอบคนละบัญชีเพื่อพิสูจน์ boundary

สำหรับ billing budget ให้ผู้ดูแล Billing Account เพิ่ม factory service account เป็น Billing Account Costs Manager หลังสร้าง service account ใน Task 05 เท่านั้น อย่าให้ Billing Account role กับกลุ่มผู้พัฒนา

**ผลที่คาดหวัง:** สิทธิ์อยู่บน parent/billing/project ที่ตั้งใจ และมีผู้ทดสอบ Dev กับ Staging แยกกัน

**บันทึกจริง / หลักฐาน:** Principal ผู้สร้าง Project: ______; Folder role: ______; Billing approver: ______; Dev identity: ______; Staging identity: ______

### Task 02 — เปิด source และเตรียมตัวแปร

ทำงานใน Cloud Shell หรือเครื่องที่ติดตั้ง gcloud, Terraform, Docker และ Python แล้ว clone branch งานจาก GitHub

```bash
git clone --branch docs/gcp-solution-labs https://github.com/somkid-s5/Portfolio-Lab.git
cd Portfolio-Lab/GCP/LAB-018-team-environment-factory
gcloud auth list
gcloud auth application-default print-access-token >/dev/null
gcloud config get-value project
terraform version
docker version
python3 --version
```

กำหนดค่าทำงานใน shell นี้ โดยแทน placeholder ด้วย resource ที่อนุมัติแล้ว

```bash
export FOUNDATION_PROJECT_ID="replace-with-foundation-project"
export STATE_BUCKET="replace-with-globally-unique-state-bucket"
export FOLDER_ID="replace-with-numeric-folder-id"
export BILLING_ACCOUNT_ID="000000-000000-000000"
export OPERATOR_MEMBER="user:operator@your-domain.example"
export PLATFORM_GROUP="platform-operators@your-domain.example"
export FACTORY_SERVICE_ACCOUNT_EMAIL=""
export ENVIRONMENT="dev"
```

Terraform ใช้ ADC; ถ้าใช้เครื่อง local ให้ตั้ง ADC เป็น principal เดียวกับผู้สร้าง Project. ยืนยันว่า project IDs ไม่ซ้ำและใช้ตัวอักษรเล็ก/ตัวเลข/ขีดกลางตามข้อกำหนด Google Cloud project ID ต้องไม่ถูกใช้โดย project อื่นทั่วโลก

**ผลที่คาดหวัง:** gcloud แสดง principal ที่อนุมัติ; เครื่องมือแสดงเวอร์ชัน; ไม่มีการพิมพ์ credential ลงไฟล์หรือ log

**บันทึกจริง / หลักฐาน:** account type: ______; Terraform version: ______; Docker version: ______; Project IDs ที่ตรวจแล้ว: ______

### Task 03 — ตรวจ profile และ Change Request ที่ยังไม่อนุมัติ

เปิด config/environments.json แทน project ID, group, owner/team/cost center, budget currency/amount และ notification email ด้วยค่าจริงที่อนุมัติ ใช้ group email จริงและ currency ของ Billing Account

ตรวจ JSON และ policy:

```bash
python3 -m json.tool config/environments.json
python3 scripts/validate_profiles.py --profile config/environments.json
```

จากนั้นตรวจ candidate dataops ซึ่งตั้งใจให้ยังไม่ผ่าน เพราะ region ยังไม่อนุมัติและ approval reference ยังเป็น PENDING:

```bash
if python3 scripts/validate_profiles.py --profile config/environments.json --candidate config/change-request-dataops.example.json; then
  echo "ERROR: candidate should be rejected before approval"
  exit 1
else
  echo "Expected rejection: region/approval is not ready"
fi
```

คำสั่งนี้ตรวจไฟล์ในเครื่องเท่านั้น ไม่เรียก Google Cloud API อย่าเพิ่ม asia-east1 ใน allowlist ก่อนมี approval

**ผลที่คาดหวัง:** Baseline profile ผ่าน; dataops candidate ถูกปฏิเสธและแสดงเหตุผล region/approval

**บันทึกจริง / หลักฐาน:** Profile commit/hash: ______; Baseline result: ______; Candidate rejection: ______

### Task 04 — สร้าง GCS state bucket

ใน Google Cloud Console เปิด Foundation Project แล้วไปที่ **Cloud Storage → Buckets → Create** ตั้งค่า:

1. ใส่ชื่อ bucket แบบ globally unique ที่กำหนดใน STATE_BUCKET
2. Location type เลือก Multi-region และ location ASIA เพื่อแยกจาก regional log buckets
3. Access control เลือก **Uniform**
4. Public access prevention ตั้งเป็น **Enforced**
5. Data protection เปิด **Object Versioning**
6. สร้าง bucket; ไม่ตั้ง retention lock ที่ป้องกัน cleanup โดยไม่ผ่านการทบทวน

ตรวจค่าด้วย gcloud:

```bash
gcloud storage buckets describe "gs://$STATE_BUCKET" --format="yaml(name,location,iamConfiguration,versioning)"
```

ผู้สร้าง bucket ต้องเข้าถึง object ได้เพื่อ init backend และ import bucket ใน Task ถัดไป ห้ามเปิด public access ห้ามใช้ bucket เก็บ application data หรือแชร์ state file

**ผลที่คาดหวัง:** bucket อยู่ใน Foundation Project, location ASIA, UBLA เปิด, public access prevention enforced และ versioning enabled

**บันทึกจริง / หลักฐาน:** Bucket: ______; location: ______; UBLA: ______; public access prevention: ______; versioning: ______

### Task 05 — ตั้ง Foundation remote state และ regional log bucket

คัดลอกตัวอย่างตัวแปรแล้วแทน project/operator/group/bucket ด้วยค่าที่อนุมัติ

```bash
cd infra/foundation
cp terraform.tfvars.example terraform.tfvars
```

terraform.tfvars ไม่ติดตามใน Git. ตรวจไฟล์ก่อนใช้ แล้ว initialize remote state:

```bash
terraform init -backend-config="bucket=$STATE_BUCKET" -backend-config="prefix=lab018/foundation"
```

นำ bucket ที่สร้างใน Task 04 เข้า Terraform state ก่อน plan:

```bash
terraform import -var-file=terraform.tfvars google_storage_bucket.tf_state "$STATE_BUCKET"
terraform plan -var-file=terraform.tfvars -out=foundation.tfplan
terraform show foundation.tfplan
```

ตรวจว่า plan ไม่เสนอให้แทนที่หรือลบ state bucket จากนั้นจึง apply:

```bash
terraform apply foundation.tfplan
terraform output -raw factory_service_account_email
terraform output -raw state_bucket_name
terraform output central_log_bucket_ids
```

บันทึก SA email ลง FACTORY_SERVICE_ACCOUNT_EMAIL ใน shell หลัก จากนั้นให้ Billing administrator เพิ่ม principal นี้เป็น Billing Account Costs Manager และตรวจว่า Foundation state bucket อนุญาต operator/factory เฉพาะที่จำเป็น

**ผลที่คาดหวัง:** Foundation state อยู่ใน prefix lab018/foundation; bucket ถูก import ไม่ได้สร้างซ้ำ; มี factory SA และ regional log bucket

**บันทึกจริง / หลักฐาน:** Foundation plan summary: ______; SA email: ______; regional log bucket ID: ______; state object path: ______; billing role result: ______

### Task 06 — สร้าง Dev Project ด้วย seeder

ตรวจ Folder ID, Billing Account ID, factory SA email และ principal ผู้สร้าง Project ก่อนเริ่ม ค่า SEEDER_MEMBER ต้องตรงกับ principal ใน Application Default Credentials (ADC) ที่สร้าง Project; gcloud active account อาจไม่ใช่ ADC

```bash
export SEEDER_MEMBER="user:operator@your-domain.example"
export ENVIRONMENT="dev"
cd ../seeder
terraform init -reconfigure -backend-config="bucket=$STATE_BUCKET" -backend-config="prefix=lab018/seeder/dev"
terraform plan \
  -var="environment=$ENVIRONMENT" \
  -var="folder_id=$FOLDER_ID" \
  -var="billing_account_id=$BILLING_ACCOUNT_ID" \
  -out=dev.tfplan
terraform show dev.tfplan
```

ทบทวน project ID, Folder, billing link, labels และ role bindings ก่อน apply:

```bash
terraform apply dev.tfplan
terraform output project_id
terraform output project_number
```

Project ถูกสร้างโดยปิด default network ด้วย auto_create_network=false; Lab นี้ไม่สร้าง VPC เพิ่ม เปิด **IAM & Admin → IAM → Grant access** ใน Project นี้ แล้วเพิ่ม factory SA ด้วย roles/artifactregistry.admin, roles/iam.serviceAccountAdmin, roles/logging.configWriter, roles/monitoring.editor, roles/resourcemanager.projectIamAdmin, roles/run.admin และ roles/serviceusage.serviceUsageAdmin. เพิ่ม principal ผู้สร้างด้วย roles/resourcemanager.projectViewer และ roles/resourcemanager.projectDeleter. ใช้ role เฉพาะ project นี้ แล้วบันทึก IAM diff; ขั้นนี้เป็น controlled handoff ก่อนถอน Owner ใน Task 08.

**ผลที่คาดหวัง:** Dev Project อยู่ใต้ Folder ที่กำหนด; factory ได้ role เฉพาะ; seeder ได้ Viewer/Deleter สำหรับ handoff/cleanup

**บันทึกจริง / หลักฐาน:** Dev project ID/number/parent: ______; plan summary: ______; labels: ______; factory roles: ______

### Task 07 — สร้าง Staging ด้วย state แยก

เปลี่ยน Environment และ backend prefix เป็น staging แล้วตรวจแผนอีกครั้ง คำสั่ง init เลือก state คนละ prefix กับ Dev

```bash
export ENVIRONMENT="staging"
terraform init -reconfigure -backend-config="bucket=$STATE_BUCKET" -backend-config="prefix=lab018/seeder/staging"
terraform plan \
  -var="environment=$ENVIRONMENT" \
  -var="folder_id=$FOLDER_ID" \
  -var="billing_account_id=$BILLING_ACCOUNT_ID" \
  -out=staging.tfplan
terraform show staging.tfplan
```

ยืนยันว่า project ID เป็น Staging และไม่ใช่ Dev ก่อน apply:

```bash
terraform apply staging.tfplan
terraform output project_id
terraform output project_number
```

Backend prefix แยก state แต่ไม่ใช่ IAM boundary ผู้ที่เข้าถึง bucket/backend อาจเข้าถึงทั้งสอง prefix ได้

ทำ IAM handoff แบบเดียวกับ Task 06 ใน Staging Project ด้วย ห้าม reuse binding ของ Dev

**ผลที่คาดหวัง:** Dev และ Staging มี project number คนละค่า และ seeder state แยก prefix

**บันทึกจริง / หลักฐาน:** Staging project ID/number/parent: ______; Dev prefix: ______; Staging prefix: ______

### Task 08 — ทำ Owner handoff ก่อนงานประจำ

สำหรับแต่ละ Environment ตรวจ IAM policy ก่อนถอน Owner:

```bash
gcloud projects get-iam-policy "$PROJECT_ID" --format="yaml(bindings)"
```

ตรวจว่า factory SA มี roles ที่มอบให้ใน Task 06 และ SEEDER_MEMBER มี Project Viewer/Deleter แล้ว จากนั้นถอน Owner ของ principal ผู้สร้าง Project:

```bash
gcloud projects remove-iam-policy-binding "$PROJECT_ID" \
  --member="$SEEDER_MEMBER" \
  --role="roles/owner" \
  --condition=None
gcloud projects get-iam-policy "$PROJECT_ID" --format="yaml(bindings)"
```

ทำซ้ำกับอีก Project. ถ้า Owner binding เป็น group หรือ inherited จาก Folder/Organization อย่าลบ binding ที่สืบทอดมา; หยุดและให้ผู้ดูแลตรวจ policy source. ยืนยันว่า effective project IAM ไม่มี Owner/Editor ที่ Lab เพิ่มไว้

**ผลที่คาดหวัง:** factory ทำงานด้วย role เฉพาะ; seeder ยังตรวจและลบ Project ได้; ไม่มี Owner/Editor project-level จาก Lab

**บันทึกจริง / หลักฐาน:** Dev policy ก่อน/หลัง: ______; Staging policyก่อน/หลัง: ______; ผู้อนุมัติถอน Owner: ______; inherited binding ที่พบ: ______

### Task 09 — สร้าง factory baseline ต่อ Environment

ให้ Billing administrator grant roles/billing.costsManager แก่ factory SA เฉพาะ Billing Account ของ Lab. ตรวจ currency budget ตรงกับ billing account และ email channel เป็นผู้รับจริง

เริ่ม factory root ใน Dev โดย backend impersonate service account จาก Foundation:

```bash
export GOOGLE_BACKEND_IMPERSONATE_SERVICE_ACCOUNT="$FACTORY_SERVICE_ACCOUNT_EMAIL"
export ENVIRONMENT="dev"
cd ../factory
terraform init -reconfigure -backend-config="bucket=$STATE_BUCKET" -backend-config="prefix=lab018/factory/dev"
terraform plan \
  -var="environment=$ENVIRONMENT" \
  -var="factory_service_account_email=$FACTORY_SERVICE_ACCOUNT_EMAIL" \
  -var="foundation_project_id=$FOUNDATION_PROJECT_ID" \
  -var="central_log_bucket_id=lab18-central-asiasoutheast1" \
  -var="billing_account_id=$BILLING_ACCOUNT_ID" \
  -var="deploy_service=false" \
  -out=dev-foundation.tfplan
terraform show dev-foundation.tfplan
```

ตรวจ project target, API list, runtime identity, Artifact Registry, budget filter และ log sink ก่อน apply:

```bash
terraform apply dev-foundation.tfplan
terraform output artifact_repository_uri
terraform output sink_writer_identity
terraform output runtime_service_account
```

ทำซ้ำ Staging โดยเปลี่ยน ENVIRONMENT, backend prefix และชื่อ plan. deploy_service=false ยังไม่สร้าง Cloud Run จนมี image digest

**ผลที่คาดหวัง:** แต่ละ Environment มี repository, runtime SA, alert budget และ project log sink; factory state ใช้ impersonation/prefix แยก

**บันทึกจริง / หลักฐาน:** Dev/Staging factory prefixes: ______; repository URI: ______; writer identities: ______; budget filters/currency: ______; email channel status: ______

### Task 10 — Build และ push Status API

กลับไป directory ของ Lab. เปิด Artifact Registry Docker credential helper สำหรับ region

```bash
cd ../../
gcloud auth configure-docker asia-southeast1-docker.pkg.dev
```

ในแต่ละ Environment ให้ user ที่เป็นสมาชิก team group push image ไปยัง URI ที่ factory output ให้:

```bash
export IMAGE_URI="asia-southeast1-docker.pkg.dev/replace-project/lab18-status-api/status-api"
docker buildx build --platform linux/amd64 --tag "$IMAGE_URI:lab18" --push app
gcloud artifacts docker images describe "$IMAGE_URI:lab18" \
  --format="value(image_summary.digest)" \
  --project="$PROJECT_ID"
```

เก็บ digest รูปแบบ sha256: ตามด้วย 64 ตัวอักษร hex. Deploy ด้วย digest ไม่ใช้ mutable tag. ถ้า Dev/Staging แยกสิทธิ์ push ให้ push แยก repository ด้วย member ที่อนุมัติ

**ผลที่คาดหวัง:** Image แสดงใน repository ของ Environment และ digest ขึ้นต้นด้วย sha256:

**บันทึกจริง / หลักฐาน:** Image tag: ______; Dev digest: ______; Staging digest: ______; ผู้ push/project: ______; ห้ามบันทึก token

### Task 11 — เปิดสิทธิ์ routing ไป central logs

Factory output ให้ writer identity ของแต่ละ sink จดทั้งสองค่าไว้ จากนั้นแก้ sink_writer_identities ใน infra/foundation/terraform.tfvars และ plan Foundation อีกครั้ง

ให้ Foundation root เพิ่ม role สองตัวแก่ sink writers:
- roles/logging.logWriter
- roles/logging.bucketWriter

ทั้งสอง role ถูกผูกที่ **Project-wide IAM scope** ของ Foundation เพราะ Cloud Logging log bucket ไม่มี IAM policy ราย bucket การให้สิทธิ์นี้ครอบคลุม log buckets ใน Project ปลายทางทั้งหมด ตรวจว่า Foundation Project นี้ใช้ตามขอบเขตที่อนุมัติ

```bash
cd infra/foundation
terraform plan -var-file=terraform.tfvars -out=logs-iam.tfplan
terraform show logs-iam.tfplan
```

หาก plan เพิ่มเฉพาะ writer identities/roles ที่ระบุ จึง apply:

```bash
terraform apply logs-iam.tfplan
gcloud projects get-iam-policy "$FOUNDATION_PROJECT_ID" --format="yaml(bindings)"
```

หลัง deploy service เปิด Logs Explorer เลือก Foundation Project และ bucket lab18-central-asiasoutheast1; ใช้ query resource.type="cloud_run_revision" AND resource.labels.service_name="status-api" AND logName:"run.googleapis.com%2Fstdout"

**ผลที่คาดหวัง:** sink writer มีสอง role ที่ Foundation Project; ไม่มีการอ้างว่า role ผูกได้เฉพาะ bucket

**บันทึกจริง / หลักฐาน:** Writer identity → role bindings: ______; Foundation project scope: ______; query/เวลาค้น: ______

### Task 12 — Deploy Cloud Run จาก digest

กลับไป factory root และตั้ง image digest ของ Environment ปัจจุบัน จากนั้น plan ด้วย deploy_service=true. ทบทวน image repository, digest, project, region, runtime SA และ invoker principal ก่อน apply

```bash
cd ../factory
export ENVIRONMENT="dev"
export IMAGE_DIGEST="sha256:replace-with-64-lowercase-hex-characters"
terraform plan \
  -var="environment=$ENVIRONMENT" \
  -var="factory_service_account_email=$FACTORY_SERVICE_ACCOUNT_EMAIL" \
  -var="foundation_project_id=$FOUNDATION_PROJECT_ID" \
  -var="central_log_bucket_id=lab18-central-asiasoutheast1" \
  -var="billing_account_id=$BILLING_ACCOUNT_ID" \
  -var="deploy_service=true" \
  -var="image_digest=$IMAGE_DIGEST" \
  -out=dev-service.tfplan
terraform show dev-service.tfplan
```

หลังยืนยันว่าแผนมีเฉพาะ Environment ที่ตั้งใจจึง apply และบันทึก URL:

```bash
terraform apply dev-service.tfplan
terraform output -raw service_url
```

ทำซ้ำ Staging ด้วย staging digest และ state/prefix ของ Staging. Cloud Run รับ HTTPS โดย network ingress เป็น all แต่ IAM บังคับ authenticate; ไม่มี allUsers binding. Runtime SA ไม่มีสิทธิ์ GCP เพิ่มและไม่มี key

**ผลที่คาดหวัง:** Cloud Run revision ชี้ image digest ที่บันทึก; service URL มีค่า; invoker เป็น group ของ Environment

**บันทึกจริง / หลักฐาน:** Dev URL/revision/digest: ______; Staging URL/revision/digest: ______; IAM invoker: ______

### Task 13 — ทดสอบ HTTP, IAM และ log delivery

บันทึก service URL และใช้ probe ที่จำกัดสูงสุด 10 request, timeout ไม่เกิน 10 วินาที

ทดสอบ unauthenticated:

```bash
cd ../../
python3 scripts/probe_status.py --url "$SERVICE_URL" --mode unauthenticated
```

จากนั้น active gcloud user ที่เป็นสมาชิก group ที่ถูกต้องทดสอบ authenticated:

```bash
python3 scripts/probe_status.py --url "$SERVICE_URL" --mode authenticated --count 3 --timeout 5
```

คาดหวัง unauthenticated ได้ HTTP 401/403 และ authenticated ได้ HTTP 200 พร้อม environment/status. ใช้ผู้ใช้ทดสอบอีก group เรียก service ที่ไม่ใช่ Environment ของตน แล้วคาดหวัง 403. อย่าใช้บัญชีเดียวที่เป็นสมาชิกทั้งสองกลุ่มสรุปว่า isolation ผ่าน

ใน Logs Explorer เลือก Foundation Project → bucket ตาม region → query จาก Task 11. ตรวจ event status_request, Environment และ status code; ตรวจว่า log ไม่มี token, IP, query string หรือข้อมูลส่วนบุคคล

**ผลที่คาดหวัง:** Authorized request สำเร็จ; unauthenticated/กลุ่มผิดถูกปฏิเสธ; log ของ Dev/Staging ระบุ Environment ได้

**บันทึกจริง / หลักฐาน:** Dev auth/deny: ______; Staging auth/deny: ______; cross-environment result: ______; log timestamp/reference: ______

### Task 14 — ตรวจ drift และฝึก incident diagnosis

เก็บ Terraform plan baseline ก่อนเปลี่ยนค่า จากนั้นแก้ label owner ของ Dev project ด้วยมือใน Console หรือคำสั่ง gcloud ที่องค์กรอนุมัติ

```bash
export PROJECT_ID="replace-with-dev-project"
gcloud projects update "$PROJECT_ID" --project="$PROJECT_ID" --update-labels=owner=manual-test
```

รัน seeder plan โดยเลือก Dev backend prefix เดิม ตรวจว่าความเปลี่ยนแปลงถูกเสนอให้กลับตรง profile แล้วคืนค่าด้วย Terraform หลังเก็บ plan diff

```bash
cd infra/seeder
terraform init -reconfigure -backend-config="bucket=$STATE_BUCKET" -backend-config="prefix=lab018/seeder/dev"
terraform plan \
  -var="environment=dev" \
  -var="folder_id=$FOLDER_ID" \
  -var="billing_account_id=$BILLING_ACCOUNT_ID" \
  -out=drift.tfplan
terraform show drift.tfplan
# หลังตรวจว่า drift มีเฉพาะ label owner ให้คืนค่าจาก profile
terraform apply drift.tfplan
```

หาก plan แสดง IAM/resource ที่ไม่เกี่ยวกับ label ให้หยุดและตรวจ state/profile ก่อน apply. สำหรับ incident ของ log routing ให้ไล่ sink destination → writer identity → roles/logging.logWriter/roles/logging.bucketWriter ที่ Foundation Project → bucket location/filter. อย่าถอดสิทธิ์ writer ใน Foundation ที่ใช้ร่วมกับระบบอื่น

ทดสอบ state lock โดยเปิด plan สอง terminal กับ backend prefix เดียวในช่วงเดียวกัน หาก operation หนึ่งรอหรือแสดง lock owner ให้บันทึกผล; ถ้าไม่ทันเห็นการแข่งขันให้บันทึก Not observed แล้วจบการตรวจ ไม่สร้าง fake lock และไม่ใช้ force-unlock เพื่อบังคับให้ผ่าน

**ผลที่คาดหวัง:** plan แสดง label drift; ไม่มีการแก้ IAM จริงเพื่อจำลองเหตุ; state lock ไม่ถูกข้าม

**บันทึกจริง / หลักฐาน:** Baseline plan: ______; manual label change: ______; drift plan/recovery: ______; lock contention observed/not observed: ______

### Task 15 — ประเมิน Change Request ของ dataops

ตรวจ candidate ก่อนอนุมัติ:

```bash
cd ../../
python3 scripts/validate_profiles.py \
  --profile config/environments.json \
  --candidate config/change-request-dataops.example.json
```

ก่อนอนุมัติ คำสั่งต้องคืน error เพราะ asia-east1 ไม่อยู่ใน allowlist และ approval reference ยังเป็น PENDING. บันทึกการปฏิเสธ อย่าแก้ profile เพื่อหลบ policy

หลัง Data Owner อนุมัติจริง ให้บันทึกเลข approval, เพิ่ม region ใน allowed_regions, เพิ่ม dataops profile และเพิ่ม asia-east1 ใน log_locations ของ Foundation. รัน Foundation plan/apply เพื่อสร้าง regional bucket ก่อนสร้าง sink; จากนั้น seeder สร้าง Project และ factory สร้าง sink/repository/budget ด้วย state prefix lab018/.../dataops. เมื่อ sink ให้ writer identity ใหม่ เพิ่มใน Foundation config แล้ว grant สอง Logging roles

ตรวจ contractor group ได้เฉพาะ roles/run.viewer บน service dataops และไม่มี invoker, deploy role, secret access หรือ membership ใน Dev/Staging. ใช้ identity contractor ทดสอบ URL; คาดหวัง 403. ทำ Cloud apply เฉพาะเมื่อ change record, data location และ billing owner อนุมัติ

**ผลที่คาดหวัง:** candidate ที่ยังไม่อนุมัติถูกปฏิเสธ; หลังอนุมัติผ่าน allowlist และสร้าง regional bucket/Project แยก โดยไม่ขยาย contractor access

**บันทึกจริง / หลักฐาน:** Candidate rejection: ______; approval reference: ______; data location approver: ______; IAM diff/plan: ______; contractor HTTP result: ______

### Task 16 — ตรวจ inventory และ cleanup Environment

ก่อนลบ บันทึก project ID/number, resources, image digest, budget, sink, log location และหลักฐานที่ต้องเก็บ ใช้ terraform plan -destroy แยก Dev กับ Staging แล้วตรวจว่าระบุ Environment เดียว

ปิด Cloud Run deletion protection ด้วยตัวแปรเฉพาะ cleanup แล้วทบทวน plan:

```bash
cd infra/factory
terraform plan -destroy \
  -var="environment=dev" \
  -var="factory_service_account_email=$FACTORY_SERVICE_ACCOUNT_EMAIL" \
  -var="foundation_project_id=$FOUNDATION_PROJECT_ID" \
  -var="central_log_bucket_id=lab18-central-asiasoutheast1" \
  -var="billing_account_id=$BILLING_ACCOUNT_ID" \
  -var="allow_destroy=true" \
  -out=dev-destroy.tfplan
terraform show dev-destroy.tfplan
```

ถ้า plan มี Project หรือ Foundation resource ให้หยุด. เมื่อยืนยันเฉพาะ resource ของ Dev แล้วจึง apply และเปลี่ยน seeder deletion policy ก่อนตรวจแผนลบ Project:

```bash
terraform apply dev-destroy.tfplan
cd ../seeder
terraform init -reconfigure -backend-config="bucket=$STATE_BUCKET" -backend-config="prefix=lab018/seeder/dev"
terraform plan -var="environment=dev" -var="folder_id=$FOLDER_ID" -var="billing_account_id=$BILLING_ACCOUNT_ID" -var="allow_project_delete=true" -out=dev-delete-policy.tfplan
terraform show dev-delete-policy.tfplan
terraform apply dev-delete-policy.tfplan
terraform plan -destroy -var="environment=dev" -var="folder_id=$FOLDER_ID" -var="billing_account_id=$BILLING_ACCOUNT_ID" -var="allow_project_delete=true" -out=dev-project-delete.tfplan
terraform show dev-project-delete.tfplan
```

ยืนยันว่า plan ลบเฉพาะ Dev Project จากนั้น apply:

```bash
terraform apply dev-project-delete.tfplan
```

ทำซ้ำ Factory cleanup และ seeder Project cleanup สำหรับ Staging โดย reconfigure backend prefix เป็น lab018/factory/staging และ lab018/seeder/staging ตามลำดับ. คง Foundation state bucket, regional log buckets และหลักฐานตาม retention policy; ห้าม destroy Foundation root. ตรวจสถานะ Project หลัง cleanup ตามพฤติกรรม Resource Manager

คง Foundation state bucket, regional log buckets และหลักฐานตาม retention policy; ห้าม destroy Foundation root. ตรวจสถานะ Project หลัง cleanup ตามพฤติกรรม Resource Manager

**ผลที่คาดหวัง:** ลบเฉพาะ Environment ที่เลือก; Foundation project/state/log buckets คงอยู่; ไม่มีแผนลบที่ยังไม่ได้ตรวจ

**บันทึกจริง / หลักฐาน:** Inventory: ______; destroy plan review: ______; Dev cleanup: ______; Staging cleanup: ______; Foundation retained: ______

## Troubleshooting

| อาการ | ตรวจอะไร | แนวทางแก้ |
|---|---|---|
| project creation permission denied | Folder ID, creator principal, inherited deny/policy | ให้ Folder administrator ตรวจ Project Creator และ deny policy; Lab ไม่แก้ Organization Policy |
| ผูก billing ไม่ได้ | Billing Account User, ID, creator role | ให้ Billing administrator ตรวจ link permission และ account status |
| seeder สร้าง Project แต่ผูก IAM ไม่ได้ | API propagation และ principal creator | รอ IAM propagation แล้ว plan ใหม่; อย่าเพิ่ม Owner/Editor เป็นทางลัด |
| backend 403 / state lock | bucket IAM, backend impersonation, active process | ตรวจ role/tokenCreator และรอ operation เดิม; อย่า force-unlock ก่อนพิสูจน์ lock ID/owner/process |
| Artifact Registry push 403 | project/repository, artifactregistry.writer, docker helper | ใช้สมาชิก group ที่ถูกต้องและ URI จาก Terraform output |
| Cloud Run 403 เมื่อควรเข้าได้ | service IAM, active account, group membership | ตรวจ roles/run.invoker และ token audience; อย่าเปิด unauthenticated เพื่อแก้ |
| Cloud Run เข้าได้จาก group ผิด | inherited IAM หรือ project Owner/Editor | ตรวจ inherited/project bindings; ลบเฉพาะ binding ที่ Lab สร้างและอนุมัติ |
| Budget apply 403 | Factory SA billing role, API, quota consumer | ตรวจ Billing Account Costs Manager และ API enablement |
| Budget notification ไม่เข้า | channel verification, recipient, threshold | Monitoring → Alerting → Notification channels ตรวจสถานะยืนยัน |
| Logs ไม่เข้าปลายทาง | sink filter/destination/writer identity | ตรวจ roles/logging.logWriter และ bucketWriter ที่ Foundation Project และ region |
| Terraform plan จะแทนที่ Project | project ID/parent/billing/profile หรือ backend prefix | ห้าม apply; ตรวจ Environment, prefix และ state ก่อน |
| roles/run.viewer เรียก API ไม่ได้ | เป็นพฤติกรรมที่ตั้งใจ | Viewer อ่าน metadata; Invoker เป็นสิทธิ์แยก |

## บันทึกผลเป็น Case Study

กรอก actual values หลังทำจริงเท่านั้น; ระหว่างจัดทำคู่มือช่องนี้ยังว่างและ Cloud verification ยัง Not run

- **ปัญหางาน:** ______
- **Requirement/ข้อจำกัด:** ______
- **Architecture และ trade-off:** ______
- **Project IDs/regions ที่สร้างจริง:** ______
- **สิทธิ์ seeder ก่อน/หลัง handoff:** ______
- **ผล deploy และ digest ของแต่ละ Environment:** ______
- **ผล auth, cross-environment denial และ health:** ______
- **Budget filters/thresholds/ผู้รับแจ้งเตือน:** ______
- **Log routing และ query ที่ใช้พิสูจน์:** ______
- **Drift/incident ที่ตรวจและ recovery:** ______
- **Change Request และ approval reference:** ______
- **เวลา/ค่าใช้จ่ายจาก billing จริง:** ______
- **Cleanup inventory/result:** ______
- **หลักฐาน:** evidence/lab18-<date>/ เก็บ screenshot/plan summary/log query ที่ลบข้อมูลส่วนตัวแล้ว; ห้าม commit state, token, secret หรือ credential
- **ข้อจำกัด:** ห้ามสรุป performance, cost saving หรือ Cloud PASS หากไม่มีผลวัดจริง

## References

- [Create and manage projects](https://docs.cloud.google.com/resource-manager/docs/creating-managing-projects)
- [Project IAM access control](https://docs.cloud.google.com/resource-manager/docs/access-control-proj)
- [Terraform GCS backend and state locking](https://developer.hashicorp.com/terraform/language/backend/gcs)
- [Terraform Google provider: Project resource](https://registry.terraform.io/providers/hashicorp/google/7.29.0/docs/resources/google_project)
- [Terraform Google provider: Billing budget](https://registry.terraform.io/providers/hashicorp/google/7.29.0/docs/resources/billing_budget)
- [Cloud Billing budget permissions](https://docs.cloud.google.com/billing/docs/how-to/budget-api-access-control)
- [Cloud Run authentication overview](https://docs.cloud.google.com/run/docs/authenticating/overview)
- [Authenticate developers to private Cloud Run services](https://docs.cloud.google.com/run/docs/authenticating/developers)
- [gcloud identity token command](https://docs.cloud.google.com/sdk/gcloud/reference/auth/print-identity-token)
- [Cloud Logging sink destination permissions](https://docs.cloud.google.com/logging/docs/export/configure_export_v2)
- [Cloud Logging access control](https://docs.cloud.google.com/logging/docs/access-control)
- [Terraform Google provider: Cloud Run v2 service](https://registry.terraform.io/providers/hashicorp/google/7.29.0/docs/resources/cloud_run_v2_service)
- [Terraform Google provider: project log sink](https://registry.terraform.io/providers/hashicorp/google/7.29.0/docs/resources/logging_project_sink)
