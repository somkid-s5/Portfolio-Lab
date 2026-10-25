---
lab: LAB-014
platform: GCP
phase: guide-ready
guide_status: guide-ready
cloud_verification: not-run
last_verified: null
---

# Lab 14 — แพลตฟอร์มส่งมอบ App แบบตรวจสอบย้อนกลับได้

> **สถานะเอกสาร:** Guide-ready หลัง repository CI [#367](https://github.com/somkid-s5/Portfolio-Lab/actions/runs/40111516650) ผ่านครบ 50/50 jobs; CI ตรวจ app, Terraform, diagram และคู่มือแบบ offline ไม่ใช่ผลทดสอบ GCP จริง. ใช้ทำตามเมื่อโค้ดชุดนี้อยู่บน `main` และเตรียม project ตามข้อกำหนดแล้ว
> **สถานะ Cloud:** Not run — ไม่มีการสร้างหรือทดสอบทรัพยากร GCP ในการจัดทำเอกสารนี้

## โจทย์

ทีมพัฒนาต้องส่ง Shipping Quote API จาก GitHub ไป staging และ production โดยต้องตอบได้ว่า image ที่ deploy มาจาก commit และ build ใด ใครรับรอง ใครอนุมัติ และจะหยุดหรือกู้ระบบอย่างไรเมื่อ business check ไม่ผ่าน ทีมไม่ต้องเก็บ Service Account key ใน GitHub และไม่ควรให้ release workflow deploy เข้า Cloud Run หรืออนุมัติ production ได้เอง

ให้สร้าง delivery path ที่ทดสอบและ build image ใน Cloud Build, ใช้ Workload Identity Federation (WIF) ให้ GitHub Actions ขอ credential อายุสั้น, ลงนาม attestation ให้ image digest ที่ผ่าน build เท่านั้น, บังคับ Binary Authorization ก่อนสร้าง Cloud Run revision และใช้ Cloud Deploy คุม staging, production approval, canary และ rollback

App ใช้ข้อมูลสังเคราะห์ ไม่ต่อฐานข้อมูลหรือระบบภายนอก โจทย์หลักคือความปลอดภัยและการปฏิบัติการของ software delivery ไม่ใช่การเขียน App

## ผลลัพธ์ที่ต้องพิสูจน์

| รหัส | สิ่งที่ต้องพิสูจน์ | หลักฐานที่ต้องเก็บ |
|---|---|---|
| R1 | Pull request ตรวจ app/config ได้โดยไม่รับ GCP credential; release trust จำกัด repository, main branch, workflow และ Environment | CI run, branch/ref และผลทดสอบ WIF จาก ref ที่ไม่เชื่อถือ |
| R2 | ไม่มี long-lived Service Account key ใน GitHub และแบ่งสิทธิ์ builder, signer, releaser, deployer, verifier, approver และ runtime | WIF condition, IAM role/scope และ negative authorization result |
| R3 | build image ครั้งเดียวและ Cloud Deploy ใช้ image แบบ digest เดียวกัน ไม่ใช้ tag ตัดสิน release | commit SHA, build ID, image digest, attestation และ digest ใน Cloud Deploy release |
| R4 | Cloud Run ปฏิเสธ image ที่ไม่มี attestation จาก attestor นี้ | image digest ที่ไม่มี attestation, deploy error และ revision/traffic ก่อน–หลัง |
| R5 | staging ผ่าน health และ business verification ก่อน promotion | staging rollout, verify job และ quote response |
| R6 | Production ต้องผ่าน Cloud Deploy approval จาก human identity ที่แยกจาก release caller | rollout approval, approver principal และเวลา |
| R7 | Canary เพิ่ม traffic 10% → 50% → 100%; verification ทำงานในแต่ละ phase | phase, traffic split, verify output และ revision ที่รับ traffic |
| R8 | business regression ที่ health ยังผ่านต้องหยุด canary ก่อนเลื่อน traffic ต่อ | failed verify, quote mismatch และ traffic ที่คงอยู่ |
| R9 | rollback กลับ release ที่รู้ว่าดีและตรวจ health/business/traffic ซ้ำ | rollback rollout, revision, traffic และ probe output |
| R10 | Change Request มี owner, reason, scope, digest, approver และวันหมดอายุ; checker ปฏิเสธ record ที่ไม่ครบ/หมดอายุ | JSON record ที่ sanitize แล้วและผล checker |
| R11 | cleanup ทำตาม inventory และไม่ลบ workload อื่นหรือหลักฐานก่อนบันทึก | inventory ก่อน/หลัง, คำสั่งและผล cleanup |

ตัวเลข canary เป็นขั้นของแบบฝึกหัดเพื่อให้เห็นการหยุดและเลื่อน phase ไม่ใช่สัดส่วนที่เหมาะกับ production ทุกระบบ

## Solution diagram

![แผนภาพสถาปัตยกรรม Lab 14](assets/diagrams/solution.svg)

[เปิดแผนภาพ HTML แบบ standalone](assets/diagrams/solution.html) · [ดูที่มาของไอคอนและ layout](assets/diagram-provenance.json)

GitHub PR checks ไม่มี Cloud credential. เมื่อ trusted commit เข้า main, Cloud Build trigger ใช้ builder identity สร้าง image; GitHub Actions ใช้ WIF แยก attestor กับ releaser; Cloud Deploy ใช้ execution identity ต่อหน้าที่ และ Cloud Run ใช้ runtime identity ที่ไม่มี permission เพิ่ม. Binary Authorization policy ใน Lab นี้เป็น **ระดับ project** ไม่ใช่เฉพาะ Cloud Run service สองตัว

## บริการตัวอย่างและสัญญา API

Shipping Quote API มี endpoint:

| Method / path | ใช้ทำอะไร | Expected |
|---|---|---|
| GET `/healthz` | ตรวจว่า process ตอบสนอง | HTTP 200, `{"status":"ok"}` |
| GET `/version` | ดู app, commit และ Cloud Run revision | HTTP 200; commit เป็น SHA ของ build และ revision เป็นชื่อ revision จริง |
| GET `/api/v1/quote?origin=BKK&destination=CNX&weight_kg=5` | ทดสอบ business path | HTTP 200, `total_thb` เป็น `455.00` เมื่อ factor เป็น 1.00 |
| GET `/api/v1/quote?origin=XXX&destination=CNX&weight_kg=5` | ทดสอบ input ที่ไม่รองรับ | HTTP 400, `error=unsupported_route` |

สูตรสำหรับ route BKK-CNX คือ base 35.00 + ระยะทาง 700 km × 0.12 บาท/kg/km × 5 kg × factor 1.00 = 455.00 บาท; factor 1.20 จะได้ 539.00 บาท. API สร้าง request ID และเขียน structured log แต่ไม่รับ/เก็บข้อมูลลูกค้าจริง และไม่บันทึก bearer token

## ขอบเขต identity

| Identity | สิทธิ์ที่ตั้งใจให้มี | สิ่งที่ไม่มี |
|---|---|---|
| GitHub PR workflow | repository tests เท่านั้น | GCP role, OIDC permission หรือ key |
| Cloud Build builder | เขียน image ใน Artifact Registry repo ของ Lab และเขียน build log | sign, deploy, approve หรือแก้ IAM/policy |
| `lab014-attestor` | อ่านผล Cloud Build, ลงนาม KMS key เดียว, attach occurrence ให้ attestor note | สร้าง build, release, deploy, approve หรือแก้ policy |
| `lab014-releaser` | สร้าง Cloud Deploy release; actAs เฉพาะ execution identities | sign, deploy Cloud Run โดยตรง หรือ approve production |
| `lab014-renderer` | Cloud Deploy RENDER job | deploy service หรือ sign |
| `lab014-staging-deployer` / `lab014-production-deployer` | Cloud Deploy DEPLOY job และ Cloud Run update ใน disposable project; actAs runtime SA | sign, แก้ policy หรือ IAM admin |
| `lab014-verifier` | Cloud Deploy VERIFY job, อ่าน Cloud Run service/revision และ invoke service แบบ authenticated | deploy, sign หรือแก้ policy |
| `lab014-runtime` | ไม่มี role เพิ่มสำหรับ App นี้ | build, registry write, sign, deploy |
| ผู้อนุมัติ Production | Cloud Deploy approver role ใน disposable project | build, sign, deploy หรือแก้ policy |

### GitHub OIDC claim contract

Terraform map claims ให้ provider ดังนี้:

~~~text
google.subject=assertion.sub
attribute.repository_id=assertion.repository_id
attribute.ref=assertion.ref
attribute.workflow_ref=assertion.workflow_ref
attribute.environment=assertion.environment

assertion.repository_id == '1428247317' &&
assertion.ref == 'refs/heads/main' &&
assertion.workflow_ref == 'somkid-s5/Portfolio-Lab/.github/workflows/release.yml@refs/heads/main' &&
assertion.environment in ['gcp-attest', 'gcp-release']
~~~

ถ้ามีการย้าย/สร้าง repository ใหม่ immutable repository ID จะเปลี่ยน; ต้อง review และแก้ trust condition กับ offline tests ก่อน apply. GitHub WIF ไม่มีสิทธิ์ `cloudbuild.builds.create`; build ที่ sign ได้ต้องมาจาก Cloud Build trigger ที่ pin builder SA, main branch และ path ของ Lab เท่านั้น

Terraform ให้บาง role ระดับ project เพราะ Cloud Deploy/Cloud Build metadata APIs เป็น project-scoped; Artifact Registry write/read, KMS signing, note attachment และ actAs ถูกจำกัดลงถึง resource เท่าที่ API รองรับ. Binary Authorization attestor delegation SA อ่าน `roles/containeranalysis.notes.occurrences.viewer` บน attestor note. Cloud Build และ Cloud Deploy service agents ที่ Google สร้าง/จัดการไม่ใช่ builder/deployer identities ของ Lab

## ก่อนเริ่ม: ค่าใช้จ่ายและ safety gate

- ใช้ **project ใหม่แบบ disposable และไม่มี Cloud Run workload อื่น** เท่านั้น. Terraform อาจจัดการ Binary Authorization default policy ที่ครอบคลุมทั้ง project; ห้ามใช้ project ที่มี service/job อื่นหรือ policy/exception ที่ต้องเก็บ
- ต้องมี Billing link, quota และสิทธิ์เปิด API, จัดการ IAM/WIF/KMS/Binary Authorization/Cloud Build/Artifact Registry/Cloud Deploy/Cloud Run. เตรียม GitHub repository connection และ human approver แยกจาก GitHub release identity
- Cloud Build, Artifact Registry storage, Cloud Run, Cloud Logging, Cloud Deploy และ Cloud KMS อาจมีค่าใช้จ่าย. ตรวจราคาและ quota ปัจจุบันของ region ก่อนลงมือ; ใน Lab จำกัด build timeout 15 นาที, Cloud Run max instances 2 และ probes มีขอบเขต
- ตั้ง budget alert ได้ แต่ให้ตรวจการใช้งานจริงและลบ resource ที่ไม่ใช้ด้วย; อย่าถือว่า alert เป็นวงเงินตัดค่าใช้จ่าย
- ไม่ใช้ production/customer traffic, ไม่เปิด unauthenticated access, ไม่ใช้ load test ยิงไม่จำกัด และไม่ใช้ breakglass เพื่อทำให้ acceptance test ผ่าน
- คู่มือนี้ใช้จาก branch `main` หลังตรวจและ merge Lab materials แล้ว. ก่อนเริ่มขั้นสร้าง resource หรือ release ต้องตรวจว่า workflow, app และ infra ที่จะทดสอบอยู่บน `main`, เลือก disposable project และเปิด release opt-in เฉพาะเมื่อพร้อมจริง; ไม่ควรเรียก trusted release จาก review branch
- Cloud Build trigger บน GCP อาจทำงานเมื่อมี commit เข้า main ตาม path ที่ตั้งไว้; GitHub Release workflow ถูกปิดไว้โดยค่าเริ่มต้นและจะทำงานร่วมกันได้เฉพาะเมื่อกำหนด repository variable `LAB014_RELEASE_ENABLED=true` หลังสร้าง project/policy/pipeline/GitHub variables ครบแล้ว. ตั้งค่านี้เฉพาะช่วงทดลอง Lab และปิดกลับเป็น `false` ก่อน cleanup; workflow รอ build ของ SHA เดียวกันและหยุดเมื่อหา build ที่ตรงกันไม่ได้. การปิด GitHub workflow **ไม่ได้ปิด Cloud Build trigger ใน GCP**: ตรวจ/Disable trigger ใน Cloud Console ด้วยก่อน merge หรือ cleanup หากไม่ต้องการการ build ที่มีค่าใช้จ่าย.

## เตรียม Cloud Shell

### Task 00 — ตรวจ project และความเสี่ยงก่อนสร้าง

1. เปิด Google Cloud Console แล้วเลือก project สำหรับ Lab 14 โดยตรวจ project ID ให้ตรงกับ project ที่อนุมัติใช้เป็น disposable
2. ไปที่ **Billing** ตรวจว่า project เชื่อม Billing account แล้ว อย่าใช้ project ที่ยังมี application หรือ workload ที่ต้องคงอยู่
3. เปิด **Binary Authorization** และตรวจ/ส่งออก policy ปัจจุบันก่อนเริ่ม. หากมี policy, attestor, allowlist หรือ workload ที่ไม่เข้าใจ ให้หยุดและใช้ project ใหม่
4. เปิด **Cloud Run** และตรวจว่าไม่มี service/job ที่ต้องเก็บ. อย่าทดลองกับ project ที่ใช้ร่วมกับ Lab อื่น
5. ยืนยันว่า human approver เป็นคน/กลุ่มคนละ identity กับ GitHub releaser และตัวเองมีสิทธิ์ขอให้เพิ่ม role ตามที่องค์กรอนุญาต

**Expected:** project ว่างสำหรับ Lab, Billing พร้อม, ไม่มี policy/workload เดิมที่ต้องปกป้อง และมีผู้อนุมัติ Production ที่ระบุตัวได้

**Actual (กรอกหลังทำ):** Project ID: ______ · Billing ตรวจเมื่อ: ______ · policy/workloads ก่อนเริ่ม: ______

**Evidence:** บันทึกเฉพาะ project ID, หน้าจอ/URL ที่ไม่เปิดเผยข้อมูล billing และผล inventory ก่อนสร้าง: ______

### Task 01 — เปิด Cloud Shell และตรวจตัวตน

เปิด Cloud Shell จาก Console แล้วตรวจ active account และ project:

~~~bash
gcloud auth list
gcloud config get-value project
gcloud version
terraform version
~~~

อย่าคัดลอก access token, credential file หรือข้อมูล Billing ลงหลักฐาน. ถ้า Cloud Shell ไม่มี Terraform ให้ติดตั้ง/เปิดใช้ตามคู่มือทางการของ Terraform ที่องค์กรอนุมัติ; อย่าดาวน์โหลด binary จากแหล่งที่ไม่รู้จัก

**Expected:** active account เป็นผู้เรียน, Cloud SDK ใช้งานได้ และ Terraform เป็นรุ่นที่รองรับไฟล์ Lab

**Actual:** account ที่ sanitize แล้ว: ______ · Terraform version: ______

**Evidence:** command output ที่ตัด token/account-sensitive fields แล้ว: ______

### Task 02 — ดึง source ที่ผ่าน review และกำหนดตัวแปร

ทำขั้นนี้เมื่อ Lab materials อยู่บน `main`. ถ้ายังไม่อยู่ ให้หยุดที่การอ่านคู่มือ/ตรวจ source; อย่าใช้ branch feature เพื่อทดลอง trusted release.

~~~bash
git clone --branch main https://github.com/somkid-s5/Portfolio-Lab.git
cd Portfolio-Lab
git status --short
cd GCP/LAB-014-secure-app-delivery
export PROJECT_ID="ใส่-project-id-ที่อนุมัติ"
export REGION="asia-southeast1"
export LAB_DIR="$PWD"
gcloud config set project "$PROJECT_ID"
gcloud config set run/region "$REGION"
~~~

แทนค่าตัวอย่าง project ID ด้วยค่าจริงที่ได้รับอนุมัติ. ตรวจว่า `git status --short` ว่างก่อนเริ่ม และอย่าพิมพ์ command พร้อม credential ลงหลักฐาน

**Expected:** source มาจาก main, project/region ตรงกับ preflight และไม่มี local modification

**Actual:** commit SHA: ______ · project/region: ______

**Evidence:** commit URL และ output ของ `gcloud config list` ที่ sanitize แล้ว: ______

## สร้าง Foundation

### Task 03 — สร้าง Cloud Build GitHub connection

Terraform จะสร้าง repository binding และ trigger แต่ GitHub App connection ต้องสร้างครั้งแรกใน Console:

1. ยืนยันว่าเปิด Cloud Build API ใน project นี้แล้ว; ถ้ายังไม่เปิด ให้เปิดเฉพาะ API นี้ก่อน เพราะยังต้องใช้ Console เชื่อม repository
2. ไปที่ **Cloud Build → Repositories** (หรือ **Repositories → Manage connections** ตามหน้า Console ปัจจุบัน) แล้วเลือกสร้าง connection แบบ GitHub / 2nd gen
3. เลือก region `asia-southeast1` เดียวกับ Terraform; ตั้งชื่อ connection เช่น `lab014-github`
4. กด **Connect** เพื่อไป GitHub และ authorize Google Cloud Build GitHub App. ติดตั้ง App กับ repository `somkid-s5/Portfolio-Lab` นี้เท่านั้น ไม่เลือก all repositories
5. กลับ Console แล้วตรวจ connection เป็น **Available/Connected**; จด full resource name รูปแบบ `projects/PROJECT_ID/locations/REGION/connections/CONNECTION_ID`

อย่าใส่ personal access token หรือ GitHub credential ลง Terraform. หากองค์กรไม่อนุญาตให้ติดตั้ง GitHub App ให้หยุดและขอผู้ดูแล ไม่ใช้ PAT เป็นทางลัด

**Expected:** Cloud Build connection อยู่ใน project/region ที่ตั้งใจและมองเห็น repository นี้เท่านั้น

**Actual:** Connection name/status: ______

**Evidence:** connection resource name และสถานะจาก Console (ไม่แนบ secret): ______

### Task 04 — ตั้งค่าและตรวจ Terraform plan

ใน Cloud Shell จากโฟลเดอร์ Lab สร้างไฟล์ `infra/terraform.tfvars` ที่ไม่ commit. ใส่ค่าจริงของ project, connection และคนอนุมัติ; ตัวอย่างต่อไปนี้เป็นรูปแบบ ไม่ใช่ค่าที่นำไปใช้ได้ทันที:

~~~hcl
project_id = "ใส่-project-id"
region = "asia-southeast1"
cloudbuild_connection_id = "projects/ใส่-project-id/locations/asia-southeast1/connections/lab014-github"
github_repository_uri = "https://github.com/somkid-s5/Portfolio-Lab.git"
approver_principal = "user:อีเมลองค์กรผู้อนุมัติ"
manage_project_binary_authorization_policy = true
~~~

ใช้ `user:email` หรือ `group:email` จริง และอย่าเลือกตัวเองเป็น approver ถ้าตัวเองเป็น owner ของการเปลี่ยนแปลง. ค่า `manage_project_binary_authorization_policy = true` จะเขียน default policy ระดับ project เพื่อบังคับ attestation; ตั้งค่านี้ได้ **ต่อเมื่อ** Task 00 ยืนยัน project ใหม่และ policy เดิมไม่มีสิ่งที่ต้องเก็บ. หากมี policy เดิม ให้หยุด ไม่ตั้ง false แล้วทำเหมือนได้พิสูจน์ Binary Authorization

ตรวจว่าไฟล์ถูก ignore แล้ว จากโฟลเดอร์ `infra`:

~~~bash
cd "$LAB_DIR/infra"
terraform fmt -check -recursive
terraform init
terraform validate
terraform plan -var-file=terraform.tfvars -out=tfplan
~~~

อ่าน plan ทั้งหมดก่อน apply. ต้องเห็นเฉพาะ API, service accounts, WIF, KMS/attestor, Artifact Registry, IAM bindings, Cloud Build connection/trigger และ policy ที่เป็นของ Lab. หยุดถ้า plan จะลบ/เปลี่ยน resource ที่ไม่ใช่ Lab, ไป project ผิด, bind approver ผิด หรือจัดการ policy ที่ไม่รู้จัก

**Expected:** fmt/init/validate ผ่าน; plan ไม่มี destroy/change ของ resource ที่อยู่นอก Lab และมี policy project-level ที่ตั้งใจสร้าง

**Actual:** plan result: ______ · resource add/change/destroy: ______

**Evidence:** commit SHA, สรุป plan ที่ตัดค่าลับออก และยืนยันว่าไม่ commit tfvars/state/plan: ______

### Task 05 — สร้าง Foundation และยืนยัน trust boundary

รัน apply เฉพาะ plan ที่อ่านแล้วใน Task 04:

~~~bash
terraform apply tfplan
terraform output
~~~

บันทึกค่าจาก output สำหรับ GitHub variables ใน Task 07. `cloudbuild_trigger` ต้องไม่เป็น null; ถ้าเป็น null แปลว่า connection ID ไม่ได้ถูกตั้ง/อ่าน ให้หยุดก่อน release. ตรวจเพิ่ม:

~~~bash
gcloud builds triggers list --region="$REGION" --project="$PROJECT_ID"
gcloud iam workload-identity-pools describe lab014-github --location=global --project="$PROJECT_ID"
gcloud iam workload-identity-pools providers describe portfolio-lab-main --location=global --workload-identity-pool=lab014-github --project="$PROJECT_ID"
gcloud artifacts repositories describe lab014-apps --location="$REGION" --project="$PROJECT_ID"
gcloud iam service-accounts list --project="$PROJECT_ID" --filter="email~lab014-"
~~~

ใน Binary Authorization Console ตรวจว่า policy default rule ต้อง require attestation จาก `lab014-release-attestor`; ห้ามตั้ง allow-all, เพิ่ม allowlist หรือใช้ breakglass เพื่อให้ deploy ผ่าน. WIF condition ต้องชี้ repository ID `1428247317`, ref `refs/heads/main`, workflow ref `somkid-s5/Portfolio-Lab/.github/workflows/release.yml@refs/heads/main` และ Environment `gcp-attest`/`gcp-release`.

**Expected:** trigger ใช้ builder SA เฉพาะ, WIF condition แคบตาม repository/ref/workflow/environment, service accounts แยกตามตาราง และ policy ผูก attestor ที่ถูกต้อง

**Actual:** builder/attestor/releaser SA: ______ · trigger ID: ______ · WIF provider: ______ · policy: ______

**Evidence:** Terraform outputs, trigger description, provider condition และ policy/attestor ที่ sanitize แล้ว: ______

### Task 06 — ลงทะเบียน Cloud Deploy pipeline และ targets

ไฟล์ `infra/clouddeploy.yaml` มี project/region placeholders สำหรับ target และ default service account ที่ manifest จะแทนด้วย deploy parameter. สร้าง temporary rendered file โดยแทนเฉพาะ project/region; อย่าใช้ `envsubst` เพราะอาจกิน parameter ของ Cloud Deploy:

~~~bash
export RENDERED_YAML="$(mktemp)"
sed -e 's|[$]PROJECT_ID|'"$PROJECT_ID"'|g' -e 's|[$]REGION|'"$REGION"'|g' "$LAB_DIR/infra/clouddeploy.yaml" > "$RENDERED_YAML"
grep -nE 'projects/|location:|name: (staging|production|lab014-quote-delivery)' "$RENDERED_YAML"
gcloud deploy apply --file="$RENDERED_YAML" --region="$REGION" --project="$PROJECT_ID"
gcloud deploy delivery-pipelines describe lab014-quote-delivery --region="$REGION" --project="$PROJECT_ID"
gcloud deploy targets list --region="$REGION" --project="$PROJECT_ID"
~~~

ก่อน apply ตรวจไฟล์ที่ render แล้วว่าไม่มี `$PROJECT_ID`/`$REGION` ค้างอยู่; มี pipeline `lab014-quote-delivery`, target `staging` ที่ไม่ require approval และ `production` ที่ require approval. ตรวจ execution config ของแต่ละ target ให้ RENDER, DEPLOY, VERIFY ชี้ไปคนละ SA ตามชื่อใน Terraform outputs

**Expected:** Cloud Deploy แสดง pipeline และ targets ใน project/region ที่เลือก; production gate เปิดอยู่

**Actual:** pipeline/target IDs และ approval setting: ______

**Evidence:** YAML ที่ render แล้วโดยลบ project-sensitive line หากจำเป็น, command output และ pipeline URL: ______

## เชื่อม GitHub โดยไม่เก็บ key

### Task 07 — ตั้ง GitHub Environments และตัวแปร non-secret

ก่อน run release workflow ให้ตรวจ repository default branch เป็น `main` และ workflow file `.github/workflows/release.yml` อยู่บน main. ค่าเริ่มต้น `LAB014_RELEASE_ENABLED` ต้องว่างหรือ `false` เพื่อกัน release จากการ merge เอกสารโดยไม่ได้ตั้งใจ. หลังสร้าง GCP sandbox และตรวจสิทธิ์ครบ ให้ตั้ง repository variable `LAB014_RELEASE_ENABLED=true` **ก่อน** push commit ทดลองที่แตะ release path และตั้งกลับเป็น `false` เมื่อจบ; GitHub Environment reviewers ไม่แทน Cloud Deploy production approval. ที่ GitHub repository ไป **Settings → Environments** แล้วสร้าง:

- `gcp-attest`: จำกัด deployment branches เป็น `main`
- `gcp-release`: จำกัด deployment branches เป็น `main`; เพิ่ม required reviewer ได้ตามนโยบายทีม

GitHub Environment approval เป็น gate ก่อน release job ขอ credential; **ไม่ใช่** Cloud Deploy production approval. Production rollout ยังต้องผ่าน `roles/clouddeploy.approver` จาก human identity แยกต่างหาก

ไปที่ **Settings → Secrets and variables → Actions → Variables** แล้วเพิ่ม Repository variables ต่อไปนี้ (ข้อมูลเหล่านี้เป็น resource identifiers ไม่ใช่ secret). อย่าสร้าง Service Account JSON key หรือใส่ credential ใน Secrets:

| Variable | ค่า |
|---|---|
| `LAB014_PROJECT_ID` | project ID ของ disposable project |
| `LAB014_REGION` | `asia-southeast1` |
| `LAB014_WIF_PROVIDER` | ค่า Terraform output `github_wif_provider` |
| `LAB014_ATTESTOR_SA` | ค่า Terraform output `attestor_service_account` |
| `LAB014_RELEASER_SA` | ค่า Terraform output `releaser_service_account` |
| `LAB014_CLOUDBUILD_TRIGGER_ID` | ค่า Terraform output `cloudbuild_trigger` (trigger UUID ไม่ใช่ full resource path) |
| `LAB014_BUILDER_SA` | ค่า Terraform output `builder_service_account` |

ทดสอบ deny path ของ WIF เพิ่มด้วย workflow ชั่วคราวใน branch แยก (อย่า merge เข้า main): สร้าง branch <code>lab014-wif-negative</code> จาก main แล้วเพิ่ม <code>.github/workflows/lab014-wif-negative.yml</code> ด้วยเนื้อหานี้ จากนั้น push branch เพื่อให้ workflow run:

~~~yaml
name: Lab 14 WIF negative control
on:
  push:
    branches: [lab014-wif-negative]
permissions: {}
jobs:
  untrusted_ref:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      id-token: write
    steps:
      - name: Exchange must be denied by the WIF condition
        uses: google-github-actions/auth@7c6bc770dae815cd3e89ee6cdf493a5fab2cc093
        with:
          workload_identity_provider: ${{ vars.LAB014_WIF_PROVIDER }}
          service_account: ${{ vars.LAB014_ATTESTOR_SA }}
          project_id: ${{ vars.LAB014_PROJECT_ID }}
~~~

workflow นี้ไม่มี GitHub Environment และ workflow_ref/ref ไม่ตรง trust condition จึงคาดว่า auth action จะ fail ตอนแลก token. ตรวจ log ให้แน่ใจว่าเป็นการปฏิเสธจาก WIF condition ไม่ใช่ตัวแปรว่างหรือ action หาไฟล์ไม่พบ; อย่าถือ failure ชนิดอื่นเป็นหลักฐาน deny. หลังเก็บ run URL แล้วลบ branch ทดสอบทั้ง branch เพื่อไม่ให้ไฟล์ทดสอบค้างหรือถูกรวมเข้า main.

ตรวจ workflow permissions, commit pin ของ Actions, path filters และ Environment names จากหน้า Code. Pull request CI ไม่มี <code>id-token: write</code>; release workflow ขอ OIDC เฉพาะ job ที่มี Environment. อย่าเพิ่ม secret ที่เป็น key เพื่อแก้ WIF error

**Expected:** Environment จำกัด branch main, ตัวแปรทั้ง 7 ชื่อตรง workflow, ไม่มี GCP key ใน Secrets และ WIF deny workflow หยุดที่ credential exchange

**Actual:** Environment protection และ variable names ที่ตั้งแล้ว: ______

**Evidence:** Settings screenshot ที่ไม่แสดงค่า secret, workflow run URL และผลตรวจ PR permissions: ______

## Release และตรวจบริการ

### Task 08 — รัน baseline จาก trusted commit และตรวจ staging

ทำเมื่อ code/terraform/pipeline พร้อมทั้งหมด, `LAB014_RELEASE_ENABLED=true` (ตั้งโดยผู้ใช้หลังยืนยันการสร้าง Cloud resources/costs), GCP Cloud Build trigger เปิดใช้ตามที่ตั้งไว้ และการนำ PR ขึ้น main ผ่าน review/อนุมัติของผู้ใช้แล้ว. push ที่แตะ path ใน Lab จึงจะทำให้ Cloud Build trigger และ GitHub release workflow ทำงานคู่กัน; หาก flag ยังเป็น `false` งาน release จะถูก skip อย่างตั้งใจ:

1. ใน GitHub ไป **Actions → Lab 14 trusted release** แล้วตรวจ run จาก `refs/heads/main`. Pull request หรือ feature branch ต้องไม่สร้าง Cloud credential หรือ release
2. เปิด Cloud Build → History เลือก build ของ commit เดียวกัน. ตรวจ status SUCCESS, trigger ID, builder SA, source SHA และ image digest
3. รอ job `attest` ให้สำเร็จ; `tools/release.py` จับคู่ trigger ID, commit SHA, builder identity, build status และ digest ก่อน sign. หาก timeout/mismatch/fail ให้หยุด ห้ามนำ digest เก่ามาแทน
4. รอ job `release` ให้สำเร็จและสร้าง Cloud Deploy release ที่อ้าง image ด้วย `@sha256:...`. ไม่มี tag mutable เป็น deployment input

ตรวจจาก Cloud Shell:

~~~bash
export TRIGGER_ID="$(terraform -chdir="$LAB_DIR/infra" output -raw cloudbuild_trigger)"
gcloud builds list --project="$PROJECT_ID" --region="$REGION" --filter="trigger_id=$TRIGGER_ID" --sort-by="~create_time" --limit=10
gcloud deploy releases list --delivery-pipeline=lab014-quote-delivery --region="$REGION" --project="$PROJECT_ID"
~~~

คำสั่งดึง trigger UUID จาก Terraform output ก่อน query build. เปิด release แล้วเทียบ source SHA, build ID และ image digest กับ GitHub/Cloud Build; staging rollout ต้องรัน verifier ผ่าน `/healthz` และ quote 455.00 ก่อน promotion

**Expected:** Cloud Build, attestation และ GitHub release jobs สำเร็จบน SHA เดียว; Cloud Deploy ใช้ digest ตรงกันและ staging verification ผ่าน

**Actual:** GitHub run: ______ · build ID: ______ · commit SHA: ______ · digest: ______ · staging rollout/verify: ______

**Evidence:** links/IDs จาก GitHub Actions, Cloud Build, attestation และ Cloud Deploy release/rollout; ห้ามกรอกผลคาดหวังแทนผลจริง: ______

### Task 09 — Promote staging ไป Production และอนุมัติ baseline

การสร้าง release จะสร้าง rollout ไป target แรกคือ staging; ไม่ได้ข้ามไป production อัตโนมัติ. หลัง staging rollout สำเร็จและตรวจ digest/quote แล้ว ให้ promote release เดิม:

~~~bash
gcloud deploy releases promote --release="RELEASE_ID" --delivery-pipeline=lab014-quote-delivery --region="$REGION" --project="$PROJECT_ID"
gcloud deploy rollouts list --delivery-pipeline=lab014-quote-delivery --release="RELEASE_ID" --region="$REGION" --project="$PROJECT_ID"
~~~

แทน `RELEASE_ID` ด้วย release ที่ตรวจแล้ว. เปิด production rollout ใน Cloud Deploy Console, เลือก **Review**, ตรวจ manifest diff, image digest, staging verification และ change record แล้วให้ผู้มี role `roles/clouddeploy.approver` กด **Approve**. หรือให้ approver รัน:

~~~bash
gcloud deploy rollouts approve "ROLLOUT_ID" --delivery-pipeline=lab014-quote-delivery --release="RELEASE_ID" --region="$REGION" --project="$PROJECT_ID"
~~~

ครั้งแรกของ target production อาจไม่มี revision เดิมให้แบ่ง traffic. Cloud Deploy จึงอาจแสดง canary phase เป็น SKIPPED และ deploy stable 100%; นี่เป็น bootstrap baseline ไม่ใช่หลักฐานว่าได้ทดสอบ canary. เก็บ phase state ตามที่เกิดจริง ห้ามเปลี่ยนให้รายงาน 10%/50% ถ้าไม่มี

**Expected:** principal ผู้อนุมัติเป็น human identity ที่ได้รับ role; baseline revision ใช้ digest เดียวกับ staging; สถานะ canary รอบแรกบันทึกตามจริง

**Actual:** approver: ______ · production rollout: ______ · phase/traffic จริง: ______

**Evidence:** approval event, rollout state, rendered manifest diff, image digest และ audit log: ______

### Task 10 — ตรวจ private access, API contract และ logs

เปิด Cloud Shell อีก terminal หนึ่งแล้วเริ่ม Cloud Run proxy สำหรับ staging; คำสั่งนี้ค้างอยู่และใส่ auth ของ active user ให้ request ที่วิ่งผ่าน proxy:

~~~bash
gcloud run services proxy quote-api-staging --project="$PROJECT_ID" --region="$REGION" --port=8080
~~~

จาก terminal ที่สองเรียก API ผ่าน localhost:

~~~bash
curl --fail-with-body --silent --show-error -i http://127.0.0.1:8080/healthz
curl --fail-with-body --silent --show-error -i http://127.0.0.1:8080/version
curl --fail-with-body --silent --show-error -i "http://127.0.0.1:8080/api/v1/quote?origin=BKK&destination=CNX&weight_kg=5"
~~~

คาดว่า health เป็น 200/ok, version แสดง commit SHA ของ build และ revision จริง, quote เป็น 455.00 THB. ผู้ใช้ที่เรียกผ่าน proxy ต้องมี <code>run.routes.invoke</code>. สำหรับ negative unauth test ดึง canonical URL แล้วเรียกตรงโดยไม่มี Authorization:

~~~bash
export SERVICE_URL="$(gcloud run services describe quote-api-staging --project="$PROJECT_ID" --region="$REGION" --format="value(status.url)")"
curl -i "$SERVICE_URL/healthz"
~~~

คาดว่า request ตรงถูกปฏิเสธ (โดยทั่วไป HTTP 401/403). ถ้าได้ 200 ให้หยุดและตรวจ Invoker IAM/public access ก่อนทำต่อ. เมื่อเสร็จให้กลับ terminal แรกและกด Ctrl-C เพื่อหยุด proxy.

ตรวจ request ID จาก response header และ structured log:

~~~bash
gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="quote-api-staging" AND jsonPayload.event="quote.created"' --project="$PROJECT_ID" --limit=5 --format="table(timestamp,jsonPayload.request_id,jsonPayload.commit_sha,jsonPayload.cloud_run_revision,jsonPayload.amount_thb)"
~~~

Log ต้องเชื่อม request ID, commit และ revision ได้; ไม่คาดหวัง image digest ใน app log เพราะ digest เก็บจาก Cloud Build/Cloud Deploy metadata. ห้ามนำ token หรือ full Authorization header เข้า evidence
**Expected:** ไม่มี auth แล้วเข้าไม่ได้; authenticated request ผ่าน health/business path; log ระบุ request/commit/revision โดยไม่เปิดเผย token

**Actual:** service URL (เก็บใน private evidence หากจำเป็น): ______ · status/quote: ______ · request ID: ______

**Evidence:** HTTP output ที่ไม่ติด token, version, log query และ Cloud Run revision/digest metadata: ______

### Task 11 — ปฏิเสธ image ที่ไม่มี attestation

ทำเฉพาะ disposable project. สร้าง image ทดสอบด้วย manual Cloud Build ที่ใช้ builder identity แต่ **ไม่ใช่ GitHub trigger** จึงไม่ผ่าน release workflow และไม่มี Lab attestation. ใช้ [config สำหรับ manual negative build](tools/cloudbuild-untrusted.yaml) ซึ่งไม่มี trigger/release step; สร้าง temporary context จาก app files ใน Cloud Shell:

~~~bash
export TEST_DIR="$(mktemp -d)"
export TEST_TAG="untrusted-$(date -u +%Y%m%d%H%M%S)"
mkdir -p "$TEST_DIR/app" "$TEST_DIR/tools"
cp "$LAB_DIR/app/Dockerfile" "$TEST_DIR/Dockerfile"
cp "$LAB_DIR/app/quote_api.py" "$TEST_DIR/app/quote_api.py"
cp "$LAB_DIR/app/requirements.txt" "$TEST_DIR/app/requirements.txt"
cp "$LAB_DIR/tools/verify_quote.py" "$TEST_DIR/tools/verify_quote.py"
gcloud builds submit "$TEST_DIR" --config="$LAB_DIR/tools/cloudbuild-untrusted.yaml" --project="$PROJECT_ID" --region="$REGION" --service-account="projects/$PROJECT_ID/serviceAccounts/lab014-builder@$PROJECT_ID.iam.gserviceaccount.com" --substitutions="_REGION=$REGION,_REPOSITORY=lab014-apps,_TAG=$TEST_TAG"
~~~

ถ้าผู้ใช้ไม่มี `cloudbuild.builds.create` หรือ `iam.serviceAccounts.actAs` บน builder SA ให้หยุดและขอสิทธิ์ตามนโยบาย; อย่าเพิ่ม project-wide Editor เพื่อข้ามปัญหา. ตรวจว่า manual build ไม่มี trigger ID และ digest นี้ไม่มี occurrence จาก attestor `lab014-release-attestor`.

จาก Cloud Run Console เปิด `quote-api-staging` → **Edit and deploy new revision** → เปลี่ยน image เป็น tag `untrusted-quote-api` ที่เพิ่งสร้าง → Deploy. คาดว่า Binary Authorization ปฏิเสธการสร้าง revision เพราะ digest ไม่มี attestation; ห้ามกด breakglass. หลัง rejection ตรวจว่า revision และ traffic เดิมยังอยู่และ request ที่ผ่านการยืนยันยังได้ 455.00. ถ้า deploy ผ่าน ให้หยุดทันทีและตรวจ policy/attestor; อย่ารายงาน PASS

**Expected:** image มี digest จริงแต่ไม่มี Lab attestation; Cloud Run admission ปฏิเสธ revision ใหม่และไม่ย้าย traffic

**Actual:** untrusted build ID/digest: ______ · denial result: ______ · revision/traffic ก่อน–หลัง: ______

**Evidence:** build record, attestation lookup, sanitized denial event และ probe ของ revision เดิม: ______

### Task 12 — ทำ regression, หยุด canary และ rollback

ขั้นนี้ทำเฉพาะ disposable project และแบ่งเป็น healthy canary กับ regression. หลัง Task 09 มี baseline production แล้ว ให้ทำ healthy canary ก่อนเพื่อพิสูจน์ทุก phase:

1. ใช้ PR/review เพิ่ม env block นี้ใน manifest production หลัง `QUOTE_PRICE_FACTOR`; คง factor เป็น 1.00. API มี field version นี้อยู่แล้ว; business quote ต้องไม่เปลี่ยน:

~~~yaml
            - name: APP_VERSION
              value: "lab14-canary-ok"
~~~
2. เมื่อ commit ที่อนุมัติเข้า main แล้ว ตรวจ Cloud Build, attestation, staging verification; promote release ไป production และให้ human approver approve
3. ตรวจ `canary-10` ว่า verify ผ่านและ traffic แสดง candidate 10%; ค่อย advance ไป phase ถัดไป:

~~~bash
gcloud deploy rollouts advance "ROLLOUT_ID" --phase-id=canary-50 --delivery-pipeline=lab014-quote-delivery --release="RELEASE_ID" --region="$REGION" --project="$PROJECT_ID"
~~~

หลัง verify ที่ 50% ผ่าน ให้บันทึก traffic แล้ว advance ไป stable 100%:

~~~bash
gcloud deploy rollouts advance "ROLLOUT_ID" --phase-id=stable --delivery-pipeline=lab014-quote-delivery --release="RELEASE_ID" --region="$REGION" --project="$PROJECT_ID"
~~~

4. อย่า advance หาก deploy หรือ verify ของ phase ปัจจุบันไม่สำเร็จ. บันทึก traffic split ที่อ่านได้จริงทั้ง 10%, 50%, 100%; ห้ามกรอกค่าคาดหวังแทนค่าจาก Cloud Run/Cloud Deploy

จากนั้นทดสอบ regression โดยเปิด PR เปลี่ยนเฉพาะ `QUOTE_PRICE_FACTOR=1.00` เป็น `1.20` ใน `deploy/service-production.yaml` (คง APP_VERSION ไว้). เมื่อ commit ที่อนุมัติเข้า main ให้รัน flow เดิม: build/attest, ตรวจ staging, promote และ approve. ที่ `canary-10` health ยังผ่านแต่ business quote จะเป็น 539.00 แทน 455.00; verifier จึงควร fail. **อย่ากด Advance rollout** เมื่อ verify fail. เก็บ job log และยืนยัน traffic ไม่เป็น stable 100%; ถ้ารูปแบบ traffic จริงไม่ตรงคาด ให้หยุดและตรวจ revision/phase แทนการเดาต่อ

เมื่อบันทึก failure แล้ว rollback target production ไป baseline release ที่รู้ว่าดี:

~~~bash
gcloud deploy targets rollback production --delivery-pipeline=lab014-quote-delivery --release="BASELINE_RELEASE_ID" --region="$REGION" --project="$PROJECT_ID"
gcloud deploy rollouts list --delivery-pipeline=lab014-quote-delivery --region="$REGION" --project="$PROJECT_ID"
~~~

ถ้ามี approval pending สำหรับ rollback ให้ผู้อนุมัติพิจารณาตามขั้นตอนปกติ; ห้าม bypass. หลัง rollback ตรวจ private health, version, quote 455.00 และ traffic/revision. จากนั้น revert production manifest ให้กลับเหมือนก่อน Change Request (factor 1.00 และไม่มี APP_VERSION override) ด้วย PR/review เพื่อให้ source กลับตรงกับ release ที่ตั้งใจ; การ revert บน main อาจสร้าง build/release ใหม่ ให้ดำเนิน staging, promotion, approval และ canary ตาม pipeline ไม่สร้าง manual release จาก tag

**Expected:** release regression fail ที่ quote verification ใน canary phase; traffic ไม่เลื่อนไป stable; rollback และตรวจซ้ำยืนยัน baseline

**Actual:** change commit: ______ · release/digest: ______ · failing phase/job: ______ · traffic ก่อน rollback: ______ · rollback rollout: ______ · quote/traffic หลัง rollback: ______

**Evidence:** PR/diff, build/attestation, approval, Cloud Deploy phase/job output, audit logs, revision/traffic และ successful post-rollback probe: ______

### Task 13 — ตรวจ Change Request record

Checker ใน `tools/check_change_request.py` ตรวจรูปแบบ record เท่านั้น ไม่แก้ Binary Authorization policy, ไม่อนุมัติ deployment และไม่สร้าง breakglass path. ทดสอบ suite ที่มี pending/expired/missing owner/self-approval/invalid digest cases:

~~~bash
cd "$LAB_DIR"
python3 -m unittest discover -s tests -p 'test_change_request.py' -v
~~~

จากนั้นสร้าง record `PENDING` ที่ผูกกับ digest จริงของ release และ project ปัจจุบัน. ตัวอย่างนี้ตั้งอายุ 7 วัน, ไม่ใส่ approval reference และไม่เปลี่ยน policy:

~~~bash
cd "$LAB_DIR"
export PROJECT_ID="$(gcloud config get-value project 2>/dev/null)"
export CHANGE_REQUEST_PATH="/tmp/lab014-change-request.json"
test -n "$PROJECT_ID" && test "$PROJECT_ID" != "(unset)" || { echo "เลือก project ใน Task 00 ก่อน" >&2; exit 1; }
python3 - <<'PY'
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path

now = datetime.now(timezone.utc).replace(microsecond=0)
record = {
    'request_id': input('Request ID (เช่น CR-2026-01; ต้องไม่ซ้ำ): ').strip(),
    'owner': input('Owner (เช่น user:you@example.com): ').strip(),
    'reason': input('เหตุผล 20–500 ตัวอักษร: ').strip(),
    'resource_scope': f"projects/{os.environ['PROJECT_ID']}/attestors/lab014-release-attestor",
    'digest': input('Image digest จริง (sha256:...): ').strip(),
    'approver': input('Approver ที่ไม่ใช่ owner (user:... หรือ group:...): ').strip(),
    'approval_status': 'PENDING',
    'approval_reference': '',
    'created_at': now.isoformat().replace('+00:00', 'Z'),
    'expires_at': (now + timedelta(days=7)).isoformat().replace('+00:00', 'Z'),
}
Path(os.environ['CHANGE_REQUEST_PATH']).write_text(
    json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding='utf-8'
)
print(f"Wrote {os.environ['CHANGE_REQUEST_PATH']} (PENDING; expires in 7 days)")
PY
python3 tools/check_change_request.py "$CHANGE_REQUEST_PATH"
~~~

กรอก digest จาก release จริงและใช้ Request ID ที่ไม่ซ้ำ. หากยังไม่มีการอนุมัติ ให้คง `PENDING` และ `approval_reference` ว่าง; ห้ามเปลี่ยนเป็น `APPROVED` หรือแต่งหลักฐานขึ้นเอง. สถานะ `valid` แปลว่า record ผ่าน validation เท่านั้น ไม่ได้อนุมัติ Cloud Deploy และไม่แก้ Binary Authorization policy.

ก่อนจบ Task ให้บันทึกผลแบบปกปิดอีเมล/ข้อมูลส่วนบุคคลตามต้องการ แล้วลบไฟล์ชั่วคราวออกจาก Cloud Shell (อย่า commit record นี้เข้า Git):

~~~bash
rm -- "$CHANGE_REQUEST_PATH"
~~~

Field ที่ checker บังคับมีดังนี้:

| Field | สิ่งที่ใส่ |
|---|---|
| `request_id` | รูปแบบเช่น CR-2026-01; ใช้ ID ไม่ซ้ำ |
| `owner`, `approver` | `user:...` หรือ `group:...`; ต้องไม่ใช่ identity เดียวกัน |
| `reason` | เหตุผล 20–500 ตัวอักษร |
| `resource_scope` | resource path ที่เริ่ม `projects/...` |
| `digest` | `sha256:` ตามด้วย hex lowercase 64 ตัว |
| `approval_status` | PENDING, APPROVED หรือ REJECTED |
| `approval_reference` | ว่างเมื่อยังไม่ APPROVED; ถ้า APPROVED ต้องชี้หลักฐานจริง |
| `created_at`, `expires_at` | RFC 3339 พร้อม UTC offset; อายุไม่เกิน 30 วันและยังไม่หมดอายุ |

รัน `python3 tools/check_change_request.py /path/to/change-request.json`. ผล valid หมายถึง record ผ่านรูปแบบ/เวลาที่ checker กำหนดเท่านั้น ไม่ได้แปลว่า approver อนุมัติ Cloud Deploy หรือ policy ยอมรับ exception. อย่าใช้ record นี้แทนการตรวจ attestation หรือเป็นเหตุให้ข้าม Binauth

**Expected:** unit tests ผ่าน; valid record แสดง `"result":"valid"`; เปลี่ยน expiry เป็นอดีตหรือเอา owner ออกแล้ว checker จบ non-zero พร้อม result invalid

**Actual:** request ID/digest (ถ้าแชร์ได้): ______ · valid result: ______ · negative result: ______

**Evidence:** record ที่ลบข้อมูลส่วนบุคคลตามต้องการ, checker output และ approval reference จริงหรือสถานะ pending: ______

### Task 14 — Operations, audit และ inventory ก่อน cleanup

ก่อนลบ ให้เก็บหลักฐาน R1–R10 และ inventory resource IDs/region/owner. ตรวจ release/rollout ที่ pending; อย่าลบ pipeline ที่ยังมี rollout ทำงาน. เก็บเฉพาะ metadata ที่จำเป็น เช่น GitHub run URL, build ID, digest, attestation/attestor, release/rollout ID, approver, revision, traffic, probes, timestamps และปัญหาที่พบ. ห้ามเก็บ access token, credential file, private key หรือข้อมูล Billing

| สิ่งที่ตรวจ | วิธีดู |
|---|---|
| Cloud Run revisions/traffic | Cloud Run → service → Revisions/Traffic; จด service, revision และ percent จริง |
| Cloud Deploy phases/jobs | Delivery pipelines → pipeline → release/rollout → phase/job; เก็บ failed verify ก่อน rollback |
| Build/digest | Cloud Build → History → build ของ commit; เชื่อมกับ Artifact Registry digest |
| Attestation | Binary Authorization → Attestors/Occurrences; ตรวจชื่อ attestor และ image digest |
| Security/audit | Logs Explorer: Cloud Run request logs, Cloud Build, Cloud Deploy approval/deploy events, Binary Authorization denial |
| Resource inventory | Cloud Run services, Cloud Deploy pipeline/targets/releases, Artifact Registry packages/images, Cloud Build trigger/repository connection, WIF pool/provider, service accounts/IAM, KMS key/version, policy, Cloud Deploy storage buckets |

**Expected:** หลักฐานเชื่อมเหตุการณ์ commit → build → digest → attestation → staging → approval → canary/rollback ได้โดยไม่เปิดเผย secret; inventory ระบุ resource ของ Lab ชัดเจน

**Actual:** สิ่งที่ตรวจครบ/ขาดและเหตุผล: ______

**Evidence:** inventory พร้อม timestamp/region และลิงก์ log/query ที่ sanitize แล้ว: ______

### Task 15 — Cleanup อย่างระวังและตรวจซ้ำ

Cleanup เป็น destructive. **ปิด `LAB014_RELEASE_ENABLED=false` และ disable GCP Cloud Build trigger ก่อน** เพื่อป้องกัน build/release ใหม่ระหว่างลบ. เก็บ/export evidence ก่อน แล้วตรวจ project ID และ resource names ซ้ำทุกครั้ง. อย่าลบ project, policy, key หรือ connection ที่มี resource ร่วมโดยอัตโนมัติ

1. ปฏิเสธ approval ที่ไม่ต้องการและยุติ rollout ที่ยังค้างตาม Cloud Deploy workflow; ตรวจว่าไม่มี rollout ที่กำลังทำงาน
2. ลบ Cloud Run services ของ Lab เท่านั้น:
   
   ~~~bash
   gcloud run services delete quote-api-staging --region="$REGION" --project="$PROJECT_ID"
   gcloud run services delete quote-api-production --region="$REGION" --project="$PROJECT_ID"
   ~~~

3. ลบ Cloud Deploy pipeline/release/rollout หลัง export evidence; `--force` จะลบ release/rollout ย่อยของ pipeline ด้วย ตรวจชื่อก่อนยืนยัน:
   
   ~~~bash
   gcloud deploy delivery-pipelines delete lab014-quote-delivery --region="$REGION" --project="$PROJECT_ID" --force
   gcloud deploy targets delete staging --region="$REGION" --project="$PROJECT_ID"
   gcloud deploy targets delete production --region="$REGION" --project="$PROJECT_ID"
   ~~~

4. ตรวจ Artifact Registry package/image list และลบ image ของ Lab ทีละ digest/tag ที่บันทึกไว้ รวม untrusted test image; อย่าลบ repository ถ้ายังมี image หรือไม่ตรง Lab
5. กลับ `infra` แล้วตรวจ `terraform plan -destroy -var-file=terraform.tfvars`; plan อาจลบ project-wide Binary Authorization policy, IAM, APIs bindings, WIF, trigger, repository, attestor และ KMS resources. ตรวจอีกครั้งว่า project ไม่มี workload อื่นก่อนยืนยัน `terraform destroy -var-file=terraform.tfvars`
6. Cloud KMS key version มีช่วง scheduled destruction (ค่า default ของ Cloud KMS ปัจจุบัน 30 วัน); การตั้ง destruction เป็นการกระทำถาวรหลังพ้นช่วงกู้คืน. อ่านสถานะ key version และคำเตือนใน plan/Console ก่อนยืนยัน. ถ้าไม่ตั้งใจ schedule key destruction ให้หยุดก่อน Terraform destroy และทำ cleanup แบบเก็บ KMS/state ที่เหลือไว้หรือให้ผู้ดูแลวางแผนเฉพาะ
7. Cloud Build GitHub connection สร้างด้วยมือและอาจมีการใช้งานอื่น; ลบ connection/GitHub App installation เฉพาะเมื่อยืนยันว่าไม่มี trigger/repository อื่นใช้อยู่
8. หลัง cleanup ตรวจ Cloud Run services, Cloud Deploy targets/pipeline, Artifact Registry packages, Cloud Build triggers, WIF, IAM bindings และ Binary Authorization policy ซ้ำ. เก็บ timestamp/result; ไม่รายงาน “ลบหมด” ถ้ายังมี KMS key/version, bucket, image หรือ API ที่คงอยู่

**Expected:** ลบเฉพาะ resource ของ Lab หลังหลักฐานครบ; บันทึก key/policy/connection ที่ตั้งใจเก็บและ resource ที่ยังคงอยู่

**Actual:** เริ่ม/จบ cleanup: ______ · deleted: ______ · retained: ______ · blockers: ______

**Evidence:** destroy plan ที่ review แล้ว, command result และ inventory หลัง cleanup: ______

## Troubleshooting

| อาการ | ตรวจอะไร | วิธีทำต่ออย่างปลอดภัย |
|---|---|---|
| Terraform plan แสดง policy/resource ที่ไม่คาดคิด | project ID, state, policy เดิม, tfvars | หยุด apply; ใช้ dedicated project ใหม่หรือให้ policy owner review |
| GitHub connection ใช้ไม่ได้/trigger null | API, region, repository installation, full connection resource name | แก้ connection input แล้ว plan ใหม่; อย่าสร้าง trigger ด้วย PAT |
| GitHub auth action ปฏิเสธ WIF | repo ID, branch/ref, workflow path/ref, Environment name, provider output, branch protection | ตรวจ provider condition และ vars; ห้ามแก้ condition ให้กว้างหรือเพิ่ม key |
| Release รอ build แล้ว timeout | trigger ID, region, commit SHA, trigger filters, Cloud Build history | ตรวจว่ามี build ของ SHA เดียวกันและ trigger จริง; ห้ามเลือก build ล่าสุด/digest เก่า |
| Attestation ไม่ผ่าน | digest, KMS key version/state, attestor public key/note, attestor SA roles | เทียบ digest จาก build, ตรวจ KMS และ note IAM; ห้ามลด Binary Authorization |
| Deploy ปฏิเสธ image ที่คิดว่าลงนามแล้ว | Cloud Deploy digest, attestation occurrence/attestor, Binauth error | ยืนยันว่าเป็น digest เดียวกันและ policy ใช้ attestor นี้; ห้าม breakglass |
| Cloud Deploy render บอก service account ผิด | release มี deploy parameter `runtime-service-account` หรือไม่ และชื่อ SA อยู่ project ถูกต้องหรือไม่ | สร้าง release ใหม่จาก digest ที่ตรวจแล้วพร้อม parameter ถูกต้อง; อย่าแก้ live service ด้วย default identity |
| Staging verifier ได้ 401/403 | service Invoker IAM, verifier identity, token audience canonical service URI, ingress | ตรวจ verifier SA มี run.invoker และ audience เป็น canonical Cloud Run URI; อย่าเปิด unauthenticated |
| Verifier บอกไม่พบ revision/tag/traffic | rollout phase, Cloud Run trafficStatuses, tag, percent | เก็บ API/output จริงและหยุด; อย่าฝืน advance โดยสมมติ phase |
| Canary verify fail | quote response, expected factor, verify job logs, request ID | คง traffic ไว้, อย่า advance, เก็บ failed rollout แล้ว rollback release ที่รู้ว่าดี |
| Rollback ไม่ผ่าน | release/rollout ที่เลือก, approval, attestation, policy, current pipeline version | ตรวจ diff และ approval ตามปกติ; ไม่ใช้ bypass policy |
| ลบ Cloud Deploy ไม่ได้ | rollout ยัง active/pending หรือ resource names ไม่ตรง | ปิด/ยุติ rollout ตามสถานะและ export evidence ก่อนลองใหม่ |
| Terraform destroy ติด KMS | key version lifecycle / destruction schedule / key ring | อย่าลบ state หรือใช้ force; ตรวจคำเตือนและเลือกเก็บ key หรือทำขั้นตอน KMS ที่อนุมัติ |

## สรุป Case Study สำหรับ Portfolio

กรอกหลังทำจริงเท่านั้น:

> ออกแบบและทดลอง delivery platform สำหรับ Shipping Quote API บน Google Cloud โดยแยก build, artifact signing, release, deployment และ production approval ออกจากกัน ใช้ GitHub OIDC/WIF โดยไม่มี long-lived key, Cloud Build สร้าง image ที่ผูกกับ commit, Binary Authorization ตรวจ attestation และ Cloud Deploy คุม staging/canary/rollback
>
> **ผลที่วัดได้จริง:** [จำนวน run/build/release ที่ทดลอง, digest, canary/rollback outcome และช่วงเวลาที่วัดจริง]
>
> **หลักฐาน:** [GitHub Actions URL] · [Cloud Build ID] · [attestation] · [Cloud Deploy release/rollout] · [sanitized probe/log]
>
> **ข้อจำกัด/บทเรียน:** [สิ่งที่ fail, สิ่งที่ยังไม่ได้ทดสอบ, ค่าใช้จ่ายที่ตรวจจาก Billing และสิ่งที่ต้องเปลี่ยนก่อนใช้กับ production]

ห้ามนำตัวเลข Expected, repository CI หรือแผนการทดลองมาเขียนเป็นผล Cloud จริง. ผลการทำ repository CI ไม่ใช่ Cloud-verified.

## แหล่งอ้างอิงทางการ

- [Workload Identity Federation สำหรับ deployment pipelines](https://docs.cloud.google.com/iam/docs/workload-identity-federation-with-deployment-pipelines) — claim, attribute condition และ short-lived credential
- [เชื่อม Cloud Build กับ repositories](https://docs.cloud.google.com/build/docs/repositories), [Cloud Build triggers](https://docs.cloud.google.com/build/docs/triggers) และ [gcloud builds submit](https://docs.cloud.google.com/sdk/gcloud/reference/builds/submit) — GitHub connection, trigger และ manual negative-image build
- [Cloud Build user-managed service account](https://docs.cloud.google.com/build/docs/securing-builds/configure-user-specified-service-accounts) — service account และ logging
- [Cloud Run authentication สำหรับ developer](https://docs.cloud.google.com/run/docs/authenticating/developers) — proxy, ID token, audience และ Invoker
- [Binary Authorization บน Cloud Run](https://docs.cloud.google.com/binary-authorization/docs/run/overview) และ [สร้าง attestation](https://docs.cloud.google.com/binary-authorization/docs/making-attestations) — policy enforcement, attestor และ signing
- [Cloud Deploy pipeline/targets](https://docs.cloud.google.com/deploy/docs/create-pipeline-targets) และ [deploy parameters](https://docs.cloud.google.com/deploy/docs/parameters) — register pipeline, target approval และ manifest parameters
- [Cloud Deploy canary บน Cloud Run](https://docs.cloud.google.com/deploy/docs/deployment-strategies/canary/cloud-run) และ [จัดการ rollout](https://docs.cloud.google.com/deploy/docs/deployment-strategies/manage-rollout) — phase, verification และ first deployment
- [Approve/reject rollout](https://docs.cloud.google.com/deploy/docs/promote-release) · [rollback target](https://docs.cloud.google.com/deploy/docs/roll-back) · [ลบ Cloud Deploy resources](https://docs.cloud.google.com/deploy/docs/delete-pipeline)
- [ทำลายและกู้คืน Cloud KMS key versions](https://docs.cloud.google.com/kms/docs/destroy-restore) — scheduled destruction และระยะกู้คืน

## Diagram attribution

ดู [diagram provenance](assets/diagram-provenance.json). ไอคอน Google Cloud ใช้ตาม source/license ที่บันทึกไว้; สัญลักษณ์ generic ระบุชื่อ service โดยไม่อ้างว่าเป็น official icon
