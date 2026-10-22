---
lab: LAB-004
platform: GCP
guide_status: authoring
cloud_verification: not-run
last_verified: null
---
# Lab 04 — Booking บน Cloud Run ที่ข้อมูลคงอยู่และไม่จองเกินความจุ

ทีมบริการต้องให้ผู้ใช้ดูช่วงเวลา จอง และยกเลิกการจองได้ผ่าน HTTPS เมื่อ Deploy revision ใหม่ข้อมูลต้องยังอยู่ และการเพิ่ม concurrency ต้องไม่ทำให้จองเกินจำนวนที่รับได้หรือเปิด DB connections จนเต็ม

## Requirements และ Acceptance

| ID | ความต้องการ | วิธีพิสูจน์ / หลักฐาน |
|---|---|---|
| R1 | ผู้ใช้ login และทำ booking journey ผ่าน HTTPS | Browser login → list slots → reserve → view own booking → cancel; HTTP/status/request IDs และ DB rows จริง |
| R2 | แยก App user ออกจาก Cloud IAM | ไม่มี session ได้401, ผู้ใช้หนึ่งอ่าน/ยกเลิกของอีกคนไม่ได้, role operator ตาม scope; runtime SA/deployer/invoker มีหน้าที่คนละส่วน |
| R3 | ไม่จองเกิน capacity และ retry ไม่ซ้ำ | ยิงคำขอพร้อมกันแบบจำกัด, retry keyเดิม, ตรวจ confirmed bookings ต่อ slot ไม่เกิน capacity และ cancellation คืนที่นั่งครั้งเดียว |
| R4 | ข้อมูลอยู่ข้าม revision และ rollback | จองบน v1 → Deploy v2 → อ่านรายการเดิม → ชี้ traffic กลับ v1 → อ่าน/ยกเลิกได้ โดย schema ยังเข้ากัน |
| R5 | DB private และ Secret เข้าถึงเฉพาะ runtime | Cloud SQL ไม่มี public IP; Cloud Run ต่อ private IP ผ่าน Direct VPC + connector; SA ไม่เกี่ยวข้องอ่าน secret ไม่ได้; ไม่ใส่ password ใน image/Repo/logs |
| R6 | หมุน DB credential อย่างควบคุม | เตรียม login B/grantsเท่ากัน + secret versionใหม่, deploy revisionใช้B, verify, ถอนAหลังไม่เหลือtraffic/connection; บันทึก rollback boundary ไม่สัญญาว่า old credential ยังใช้ได้หลัง revoke |
| R7 | เพิ่ม concurrency โดยคง data/connection safety | เปลี่ยน8→16, pool4/instance, max instanceตามขอบเขต; วัด request/error/latency + active DB connections และ business invariants ก่อน/หลัง |
| R8 | Dependency fault/recovery และ Cleanup | ตั้ง config/DB access ที่ผิดแบบจำกัดบน no-traffic revision, ตรวจhealth/logs แล้วแก้; ลบ Run/SQL/secrets/images/VPC/PSA ตาม inventory และบันทึก rebuild commit |

## Architecture และขอบเขตที่เลือก

- Singapore region, Cloud Run service เดียวให้ UI/API ด้วย managed run.app HTTPS endpoint ไม่ต้องมี domain หรือ LB เพิ่ม
- Cloud SQL PostgreSQL 16, Enterprise edition, private services access (PSA), **ไม่มี public IP**; baseline single-zone ไม่อ้าง database HA ซึ่งจะเจาะใน Lab 05
- Custom VPC และ regional subnet สำหรับ Direct VPC egress; PSA allocated range เป็น service-producer allocation ไม่ใช่ subnet ของ VM
- Cloud SQL Python Connector ใช้ private IP และจัดการ TLS/instance identity; connector ไม่สร้าง network path ให้เอง ต้องมี Direct VPC/PSA จริง
- Runtime service account เฉพาะ Lab มี Cloud SQL Client และ Secret Accessor เฉพาะ secret ที่ต้องใช้ ไม่ใช้ default Compute SA หรือ project-wide Editor
- Secret Manager เก็บ DB login configuration, demo user password hashes และ session signing key ใช้ versionที่ pin ชัดสำหรับแต่ละ revision ไม่ใช้ latest แบบอธิบายผล rotation ไม่ได้
- Container images ใน Artifact Registry; Dockerfile/runtime code/schema/seed/probes อยู่ใน Lab นี้ ไม่พึ่ง resource ของ Lab ก่อน

## Identity และ Browser flow

เลือก public Cloud Run entry สำหรับหน้า login แต่ทุก business endpoint ต้องผ่าน App session/role/ownership checks Public invoker ไม่ใช่การเปิดข้อมูล booking และไม่ใช่หลักฐานว่า IAM ยืนยัน end user ให้

App ใช้ demo users/booker/operator, password hashes, HttpOnly Secure SameSite cookies, session expiry และ CSRF สำหรับ state-changing requests บน HTTPS แยก deployer IAM, runtime service identity และ App identity อย่างชัดเจน ไม่อ้างว่า demo login เป็น enterprise SSO หาก organization ห้าม public invoker ให้หยุด baselineและออกแบบทางเข้าใหม่โดยไม่ปิด policy

ไม่ทำ UI ที่เก็บ DB password หรือ privileged token ใน browser, URL query, localStorage หรือ screenshot หลักฐานต้อง redact cookie/secret values

## Business data และ App contract

เตรียม slots อย่างน้อย5ช่วงพร้อม capacity, usersสองคนและoperator, bookings/status/idempotency/audit fields มี transaction/row lock หรือ conditional mutationที่พิสูจน์ invariantได้ UI รองรับ list/reserve/cancel และแสดง booking reference/request ID ไม่ให้ผู้เรียนไปคิด App ใหม่

มี /livez ตรวจ process, /healthz ตรวจDB/schema และ structured request/dependency logs แบบไม่เผย credentials การ pool ต้องปิด connectionกลับpoolครบเมื่อexception มี bounded wait/statement timeouts ไม่สร้างunbounded reconnect loop

v1/v2 ใช้ schema compatible กันใน baseline ไม่ยัด destructive migration ลง rollback demo การเปลี่ยน schemaในอนาคตต้องแยก expand/contract และบอก boundary ก่อน deploy

## Connection budget และต้นทุนก่อนลงมือ

เริ่ม concurrency8, application poolสูงสุด4ต่อinstanceและ max instance2 เป็นค่าฝึก ไม่ใช่ capacity recommendation สำหรับ production ระหว่าง rollout อาจมีหลาย revision/instanceและแพลตฟอร์มอาจเกินเป้าชั่วคราว จึงคำนวณเผื่อ old+new revisions, admin connections และ monitor pg_stat_activity ไม่อ้าง max-instances เป็น hard cap ของ DB connections

Cloud SQL คิดค่าใช้จ่ายแม้ Run scale-to-zero; มี storage/backup/PSA/Artifact Registry/Secret/egress/logs ตามใช้ เลือกmachine/region/edition/quotaและเวลาปิดใน Guide ก่อนสร้าง Budgetเป็นalert ไม่ใช่hard cap งานจัดทำเอกสารนี้ไม่ provision GCP resources

## Rotation และ Failure drill ที่ต้องออกแบบให้ครบ

DB credential rotation ใช้สอง loginชั่วคราว A/B เพื่อให้ revisionเก่ากับใหม่ทำงานคู่กันได้โดยไม่ reset passwordของloginที่ยังรับงานทันที หลัง verifyB แล้วค่อย retireA หาก revokeAแล้วต้องกู้ด้วยlogin/secretที่ยังvalid ไม่ใช่blind traffic rollback

Fault ใช้ revisionที่ไม่รับ production traffic ใน sandboxและมีtagสำหรับทดสอบจำกัด ไม่ทำลายDBเพื่อให้มีincident ต้องบันทึกerror/สาเหตุ/การแก้/retestจริง พร้อมลบfault revisionตอนปิดงาน


## ลงมือทำ

### Task 0 — เตรียม Sandbox และกำหนดเวลาปิด

**ทำที่ไหน:** Google Cloud Console และ Cloud Shell (Bash) ทุกคำสั่งด้านล่างรันใน Cloud Shell ไม่ใช่ PowerShell บนเครื่องส่วนตัว

1. เลือก Project สำหรับฝึกโดยเฉพาะ เปิด Billing และยืนยันว่าองค์กรอนุญาต Cloud Run public entry, Secret Manager และ Cloud SQL private services access หาก policy ไม่อนุญาต อย่าปิด policy เพื่อให้ผ่าน
2. เปิด **Billing → Budgets & alerts → Create budget** เลือก Project นี้ ตั้งวงเงินที่ยอมรับและผู้รับแจ้งเตือน Budget แจ้งเตือนเท่านั้น ไม่หยุดค่าใช้จ่ายอัตโนมัติ
3. กำหนดเวลาลบระบบ เช่น ภายในวันเดียวหลังทำเสร็จ Cloud SQL มีค่าใช้จ่ายแม้ไม่มีคนเปิดเว็บ คิดรวม instance, disk/backup/PITR, Secret versions, image storage, requests และ logs ตรวจ [เครื่องคำนวณราคา](https://cloud.google.com/products/calculator) ก่อน Apply ไม่ใช้ยอดจาก Lab อื่น
4. ผู้จัดเตรียม Sandbox ต้องให้สิทธิ์ตามงาน: Service Usage Admin, Compute Network Admin, Cloud SQL Admin, Service Account Admin, Secret Manager Admin, Artifact Registry Admin, Project IAM Admin และ Cloud Run Admin ภายใน Project ฝึกนี้ การมอบ IAM สำหรับ runtime เป็นงานแยกจากสิทธิ์ login หน้าเว็บ ไม่ต้องใช้ Owner เป็น baseline
5. เปิดปุ่ม **Activate Cloud Shell** มุมขวาบน ตรวจบัญชีก่อนเริ่ม:

```bash
gcloud auth list --filter=status:ACTIVE --format='value(account)'
export PROJECT_ID='เปลี่ยนเป็น-project-id-จริง'
export REGION='asia-southeast1'
gcloud config set project "$PROJECT_ID"
gcloud projects describe "$PROJECT_ID" --format='value(projectId)'
git clone --branch docs/gcp-solution-labs https://github.com/somkid-s5/Portfolio-Lab.git portfolio-booking
cd portfolio-booking
export LAB_ROOT="$PWD/GCP/LAB-004-serverless-booking"
git rev-parse HEAD
gcloud version
terraform version
docker version
```

ถ้าเคย clone แล้ว ให้เปิด checkout เดิมและตรวจ branch/commit แทนการ clone ทับ ถ้า Terraform ไม่มี ให้ติดตั้งตาม [คู่มือ HashiCorp](https://developer.hashicorp.com/terraform/install) รุ่นที่เข้าเงื่อนไข versions.tf; CI ของชุดนี้ใช้ 1.9.8 / Google provider 6.50.0 ไม่ถือว่าเป็นรุ่นล่าสุด Docker ต้องตอบทั้ง Client และ Server

**Expected:** บัญชี/Project ตรง Sandbox, อยู่ใน Repo นี้, มีเครื่องมือครบ ยังไม่มี GCP resource ของ Lab ถูกสร้าง

**บันทึก T00:** วันที่ ___ / Project ___ / Region ___ / Source commit ___ / Tool versions ___ / Budget และเวลาปิด ___ (ไม่บันทึก access token)

**ไปต่อเมื่อ:** มีสิทธิ์และงบ/เวลาปิดชัด หากได้ permission denied ให้ขอสิทธิ์เฉพาะงานจากผู้ดูแล ไม่เปลี่ยนไปใช้บัญชีร่วม

### Task 1 — สร้าง Foundation และตรวจขอบเขต Private

**ทำที่ไหน:** Cloud Shell, เริ่มจาก Lab root

```bash
cd "$LAB_ROOT"
gcloud services enable serviceusage.googleapis.com cloudresourcemanager.googleapis.com iam.googleapis.com
terraform -chdir=infra init
terraform -chdir=infra validate
terraform -chdir=infra plan -var="project_id=$PROJECT_ID" -out=booking.tfplan
terraform -chdir=infra show -no-color booking.tfplan
```

อ่าน Plan ก่อน Apply: VPC lab004-vpc, subnet 10.44.0.0/24, PSA range 10.84.0.0/16, PostgreSQL16 Enterprise ZONAL, SSD10GB fixed size, private IP เท่านั้น, backups2/PITR1วัน, Secret containers4ชื่อ, SA runtime/bootstrap และ Artifact Registry1แห่ง ไม่ควรมีการลบของระบบอื่นหรือ secret payload ใน Plan ห้ามเปลี่ยน CIDR ถ้าไม่ตรวจว่าทับเครือข่ายที่ต้องเชื่อมต่อหรือไม่

```bash
terraform -chdir=infra apply booking.tfplan
export INSTANCE_CONNECTION_NAME="$(terraform -chdir=infra output -raw instance_connection_name)"
export RUNTIME_SA="$(terraform -chdir=infra output -raw runtime_service_account)"
export BOOTSTRAP_SA="$(terraform -chdir=infra output -raw bootstrap_service_account)"
export IMAGE_REPO="$(terraform -chdir=infra output -raw image_repository)"
gcloud sql instances describe lab004-sql --format='yaml(databaseVersion,region,settings.edition,settings.availabilityType,settings.ipConfiguration,ipAddresses)'
gcloud secrets list --filter='name:lab004-' --format='table(name)'
```

**Expected:** SQL มี PRIVATE address และ ipv4Enabled=false; ไม่มี PRIMARY/Public address Secret เพิ่งสร้างยังไม่มี version ค่าลับ Terraform ไม่ได้สร้าง DB password หรือ Cloud Run revision

หาก instance สร้างไม่สำเร็จ ตรวจ SQL operation/error, quota/region/tier, API และ PSA connection อย่าสร้าง instance สำรองแบบ Public IP เพื่อข้ามปัญหา ถ้า CIDR ชนให้หยุดและออกแบบ range ใหม่ก่อนสร้าง App

State/plan แม้ไม่มี password ยังเป็นข้อมูลโครงสร้างระบบ อย่า commit ลง Repo เก็บ checkout/infra state ใน Cloud Shell อย่างปลอดภัยจน Cleanup เสร็จ หากสลับเครื่องทำงาน ต้องใช้ state เดิม ไม่เริ่ม apply ด้วย state ว่าง

**บันทึก T01:** Plan resource counts ___ / SQL private address (redact ตามนโยบาย) ___ / edition-zone ___ / state location ___ / evidence `assets/evidence/T01-private-boundary.txt` ___

### Task 2 — เตรียม Secret โดยแยก Admin กับ Runtime

**ทำที่ไหน:** Cloud Shell, Lab root ไม่เปิด shell tracing (`set -x`) และไม่บันทึกหน้าจอขณะเปิดไฟล์ลับ

```bash
cd "$LAB_ROOT"
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python scripts/create-secrets.py --out secrets
git status --short --untracked-files=all
```

Generator สร้าง directory700/files600 และปฏิเสธ directory ที่มีอยู่แล้ว `auth.json` เก็บ password hashes/session key, `demo-logins.json` เป็นรหัสสำหรับเข้าเว็บ, `db-a.json`/`db-b.json` เป็น runtime login และ `bootstrap-admin.json` ใช้ postgres เฉพาะตอนตั้ง schema ไม่มีไฟล์เหล่านี้ควรปรากฏใน git status ถ้าเผลอเผยแพร่ให้ถือว่า secret รั่วและเปลี่ยนใหม่ ไม่ใช่แค่ลบออกจาก commit ล่าสุด

เปิด **Cloud Shell Editor → secrets/sql-admin-password.txt** คัดลอกรหัสไปใช้กับ prompt ต่อไปนี้ (ไม่ใส่รหัสใน command line และไม่ใช้ cat พิมพ์ลง log):

```bash
gcloud sql users set-password postgres --instance=lab004-sql --prompt-for-password
```

วางรหัสจากไฟล์แล้ว Enter ต้องตรงกับ bootstrap-admin.json หากไม่ตรง bootstrap จะ authentication failed ปิดไฟล์ลับหลังใช้ จากนั้นเพิ่ม Secret versions โดยส่งจากไฟล์โดยตรง:

```bash
export AUTH_VERSION="$(gcloud secrets versions add lab004-auth --data-file=secrets/auth.json --format='value(name)' | awk -F/ '{print $NF}')"
export A_VERSION="$(gcloud secrets versions add lab004-db-a --data-file=secrets/db-a.json --format='value(name)' | awk -F/ '{print $NF}')"
export B_VERSION="$(gcloud secrets versions add lab004-db-b --data-file=secrets/db-b.json --format='value(name)' | awk -F/ '{print $NF}')"
export ADMIN_VERSION="$(gcloud secrets versions add lab004-bootstrap-admin --data-file=secrets/bootstrap-admin.json --format='value(name)' | awk -F/ '{print $NF}')"
printf 'auth=%s dbA=%s dbB=%s bootstrap=%s\n' "$AUTH_VERSION" "$A_VERSION" "$B_VERSION" "$ADMIN_VERSION"
```

**Expected:** ได้เลข version บวก4ค่า ไม่ใช่ latest; คำสั่งไม่แสดง payload Runtime SA อ่านเฉพาะ auth/db-a/db-b ส่วน bootstrap อ่าน admin/db-a/db-b ไม่อ่าน auth บัญชีผู้ใช้ที่ Deploy ต้องมี iam.serviceAccounts.actAs บน SA ที่ใช้ ผู้ดูแลสามารถให้ Service Account User เฉพาะ runtime/bootstrap ดังนี้:

```bash
export DEPLOYER_EMAIL="$(gcloud config get-value account)"
gcloud iam service-accounts add-iam-policy-binding "$RUNTIME_SA" --member="user:$DEPLOYER_EMAIL" --role=roles/iam.serviceAccountUser
gcloud iam service-accounts add-iam-policy-binding "$BOOTSTRAP_SA" --member="user:$DEPLOYER_EMAIL" --role=roles/iam.serviceAccountUser
```

ตัวอย่างนี้ใช้ human user หากเป็น federated/service-account deployer ต้องใช้ member type ที่ถูกต้อง ไม่แปลงทุก identity เป็น user โดยอัตโนมัติ

**บันทึก T02:** Secret names+version numbers ___ / runtime/bootstrap role review ___ / file permission check ___ ห้ามแนบ demo passwords/cookies/JSON payload

### Task 3 — สร้าง Image และตรึง Digest

**ทำที่ไหน:** Cloud Shell, Docker build บน Cloud Shell ไม่ใช้เครื่องผู้เรียน ไม่มี secret รวมใน image เพราะ .dockerignore กัน secrets/ ออก

```bash
cd "$LAB_ROOT"
export SOURCE_COMMIT="$(git rev-parse --short=12 HEAD)"
export IMAGE_TAG="$IMAGE_REPO/booking:$SOURCE_COMMIT"
gcloud auth configure-docker "$REGION-docker.pkg.dev"
docker build --pull -t "$IMAGE_TAG" .
docker push "$IMAGE_TAG"
export IMAGE_DIGEST="$(gcloud artifacts docker images describe "$IMAGE_TAG" --format='value(image_summary.digest)')"
export IMAGE_PIN="$IMAGE_REPO/booking@$IMAGE_DIGEST"
printf '%s\n' "$IMAGE_PIN"
```

**Expected:** digest รูป sha256: ตามด้วย64ตัวอักษร ไม่ใช้ tag ที่อาจถูกเขียนทับตอน Deploy ถ้า push denied ตรวจ active account และสิทธิ์ Artifact Registry ใน repo lab004-images; อย่าเอา runtime SA ไปเป็น image builder หรือมอบ Editor ให้ runtime

**บันทึก T03:** Commit ___ / Image digest ___ / Build result ___ / ไม่พบ secret ใน context ___

### Task 4 — Bootstrap ฐานข้อมูลด้วย Job แยก

**ทำที่ไหน:** Cloud Shell; Job รันใน Cloud Run ผ่าน Direct VPC ภายในregionเดียวกัน

```bash
gcloud run jobs create lab004-bootstrap --region="$REGION" \
  --image="$IMAGE_PIN" --service-account="$BOOTSTRAP_SA" \
  --network=lab004-vpc --subnet=lab004-run-subnet --vpc-egress=private-ranges-only \
  --tasks=1 --parallelism=1 --max-retries=0 --task-timeout=300s \
  --cpu=1 --memory=512Mi --command=python \
  --args=scripts/init-db.py,--role-a-file,/secrets/a/config.json,--role-b-file,/secrets/b/config.json \
  --set-env-vars="DB_MODE=cloud,DB_CONFIG_FILE=/secrets/admin/config.json,INSTANCE_CONNECTION_NAME=$INSTANCE_CONNECTION_NAME" \
  --set-secrets="/secrets/admin/config.json=lab004-bootstrap-admin:$ADMIN_VERSION,/secrets/a/config.json=lab004-db-a:$A_VERSION,/secrets/b/config.json=lab004-db-b:$B_VERSION"
gcloud run jobs execute lab004-bootstrap --region="$REGION" --wait
gcloud run jobs logs read lab004-bootstrap --region="$REGION" --limit=30
```

**Expected:** execution สำเร็จ และข้อความ Schema, seed and least-privilege logins created atomically ไม่มี password จะได้ slots5แถว/schema/booking_a/booking_b ที่ไม่ใช่ superuser การสร้างทั้งหมดอยู่ใน transaction เดียว

หาก timeout ระหว่าง Direct VPC เริ่มต้นหรือ SQL connector เชื่อมต่อ ให้ตรวจ execution logs และ rerun **execute** หลังแก้เครือข่าย/permission ไม่ต้อง create job ซ้ำ ถ้าพบ Runtime role exists แสดงว่าฐานข้อมูลผ่าน bootstrap แล้วหรือมีของเดิมอยู่ ให้ตรวจ ไม่ reset password ขณะระบบยังใช้งานอยู่ ถ้า Job จบไปแล้วแต่ response หาย ห้ามอนุมานว่า transaction ล้มเหลว

**บันทึก T04:** Execution name ___ / status ___ / schema message ___ / error+retest ___ / evidence `assets/evidence/T04-bootstrap.txt` (ตรวจว่าไม่มี secret)

### Task 5 — Deploy v1 และเปิด Booking UI

**ทำที่ไหน:** Cloud Shell แล้วเปิด URL ใน Browser

```bash
cd "$LAB_ROOT"
.venv/bin/python scripts/deploy-service.py \
  --project "$PROJECT_ID" --region "$REGION" --image "$IMAGE_PIN" \
  --auth-version "$AUTH_VERSION" --db-version "$A_VERSION" --suffix v1-a01
```

ครั้งแรกเป็น **dry-run** อ่าน command ที่แสดง: runtime SA ถูกตัว, Direct VPC/subnetถูก, DB private config, secret versionเป็นเลข, concurrency8, max-instances2, poolใน App4/instance, ไม่มี APP_LOCAL_TEST หรือ admin secret จากนั้นรันชุดเดิมโดยเติม `--execute`:

```bash
.venv/bin/python scripts/deploy-service.py \
  --project "$PROJECT_ID" --region "$REGION" --image "$IMAGE_PIN" \
  --auth-version "$AUTH_VERSION" --db-version "$A_VERSION" --suffix v1-a01 --execute
export SERVICE_URL="$(gcloud run services describe lab004-booking --region="$REGION" --format='value(status.url)')"
curl --max-time 15 --fail-with-body "$SERVICE_URL/livez"
curl --max-time 15 --fail-with-body "$SERVICE_URL/healthz"
curl --max-time 15 -i "$SERVICE_URL/api/bookings"
gcloud run services describe lab004-booking --region="$REGION" --format='yaml(status.latestReadyRevisionName,status.traffic)'
```

**Expected:** livez alive=true/version=v1; healthz ready=true; ไม่ login แล้ว bookings=401 login_required (ตั้งใจให้ curl คำสั่งนี้ไม่ใช้ --fail) Startup/liveness ตรวจ process ไม่บังคับ restart ทุกครั้งที่ DBขัดข้อง การ deploy สำเร็จจึงยังไม่พิสูจน์ DB ต้องตรวจ healthz แยก

เปิด SERVICE_URL → หน้า Booking → เปิด demo-logins.json ใน Editor แบบส่วนตัว → login alice → เห็น5slots → จองช่วงที่เลือก → รายการของฉันมี booking → ยกเลิกแล้วสถานะ cancelled จำนวนที่นั่งกลับคืน Login cookie เป็น Secure/HttpOnly/SameSite=Lax และหมดอายุเมื่อไม่มี activity10นาที ไม่มีการใส่ DB secret ใน Browser

หาก revision เดิมชื่อ v1-a01 มีอยู่แล้ว ให้ตรวจว่า Deploy เดิมสำเร็จหรือไม่ก่อน เลือก suffix ใหม่เช่น v1-a02 เมื่อกำลังสร้าง revisionใหม่ ไม่ลบของเดิมเพื่อให้ชื่อว่าง
- livezไม่ผ่าน: ดู container import/startup/secret mount/PORT
- livezผ่านแต่healthz503: ดู database_unavailable, SQLClient/SecretAccessor, VPC/PSA/region, admin bootstrap, DB login และ version ไม่พิมพ์ connection string ที่มีpassword
- Cloud Run403ก่อนเห็นหน้าlogin: ตรวจ invoker policy และ org policy ไม่ใช่รหัส alice ผิด
- login401: ตรวจ demo user/password จากbundleเดียวกับ auth version; login403csrf_required: refreshหน้าและรับsessionใหม่ ไม่ปิดCSRF

**บันทึก T05:** URL ___ / Ready revision ___ / Secret versions ___ / livez-healthz-anonymous statuses ___ / Alice booking reference+cancel result ___ / Screenshotหลังloginที่ไม่เห็นรหัส ___

**เกณฑ์ไปต่อ:** Browser journey สำเร็จและ healthz ผ่าน จด revision v1 ไว้สำหรับเปรียบเทียบ v2/rollback ใน Task ถัดไป


### Task 6 — พิสูจน์ Business Rules และตรวจฐานข้อมูล

**ทำที่ไหน:** Cloud Shell และ Cloud Run Jobs ใช้เฉพาะข้อมูลสังเคราะห์ของ Lab

```bash
cd "$LAB_ROOT"
mkdir -p assets/evidence
.venv/bin/python scripts/probe.py --url "$SERVICE_URL" --logins secrets/demo-logins.json \
  --mode journey > assets/evidence/T06-journey.json
```

**Expected:** exit0/checks=completed; anonymous401, ไม่มีCSRF403, reserve201 → retrykeyเดิม200/bookingIDเดิม, Bobอ่าน/ยกเลิกAlice404, bookerเข้าoperator403, operatorอ่าน200, cancelครั้งแรกreplayed=falseและครั้งต่อไปtrue Probeยกเลิกเฉพาะรายการที่ตนสร้าง ไม่เปลี่ยนรายการที่ผู้เรียนจองไว้

เปิด Browser ตรวจและยกเลิก **ทุก confirmed booking ใน slot1** ของ Alice/Bob/operator ให้booked=0ก่อนrace ห้ามลบDBrowsเพื่อให้ผ่าน:

```bash
.venv/bin/python scripts/probe.py --url "$SERVICE_URL" --logins secrets/demo-logins.json \
  --mode race > assets/evidence/T06-capacity-race.json
```

**Expected:** seed slot1 capacity2, ผู้ใช้ต่างกัน3คนส่งพร้อมกัน ได้201สองคำขอและ409หนึ่งคำขอ; bookedไม่เกิน2และกลับ0หลังprobeยกเลิก ทั้งนี้ต้องไม่มีผู้ใช้อื่นกำลังแก้slot1พร้อมกัน ถ้าresponseหายหรือprobeล้ม ให้ตรวจรายการในBrowser/DBก่อนยิงซ้ำ ไม่สมมติว่าคำขอที่timeoutไม่เกิดผล

ตรวจDBด้วยJobอ่านอย่างเดียว ใช้bootstrap SA/admin configแยกจากApp เพราะต้องเห็นconnectionและrole metadata ไม่เปิดPostgreSQLผ่านPublic IP:

```bash
gcloud run jobs create lab004-inspect --region="$REGION" \
  --image="$IMAGE_PIN" --service-account="$BOOTSTRAP_SA" \
  --network=lab004-vpc --subnet=lab004-run-subnet --vpc-egress=private-ranges-only \
  --tasks=1 --parallelism=1 --max-retries=0 --task-timeout=300s \
  --cpu=1 --memory=512Mi --command=python --args=scripts/inspect-db.py \
  --set-env-vars="DB_MODE=cloud,DB_CONFIG_FILE=/secrets/admin/config.json,INSTANCE_CONNECTION_NAME=$INSTANCE_CONNECTION_NAME" \
  --set-secrets="/secrets/admin/config.json=lab004-bootstrap-admin:$ADMIN_VERSION"
gcloud run jobs execute lab004-inspect --region="$REGION" --wait
gcloud run jobs logs read lab004-inspect --region="$REGION" --limit=20
```

**Expected:** invariant_violations=[]; slotsมีcapacity/bookedถูกต้อง; runtime roles rolsuper/rolcreatedb/rolcreaterole=false โดยroleA/BอาจยังLOGINได้ทั้งคู่ ข้อมูล connections เป็น snapshot ในขณะ Jobอ่าน ไม่ใช่ค่าสูงสุดตลอดการทดสอบ ห้ามแปลbooked=0เป็นไม่มีhistoricalbookings เพราะรายการcancelledยังเก็บอยู่

**บันทึก T06:** journeyผล ___ / race HTTPcounts ___ / invariant violations ___ / DBconnections snapshot ___ / exitcodes ___ / requestIDตัวอย่าง ___

### Task 7 — Deploy v2 แล้ว Rollback โดยไม่ย้อนข้อมูล

**ทำที่ไหน:** Browser + Cloud Shell

1. ในBrowser loginAlice จองslotที่ว่างหนึ่งรายการและ **ยังไม่ยกเลิก** จดbookingreference/slot/statusเป็นหลักฐานก่อนDeploy
2. เก็บชื่อv1และpin trafficกับrevisionจริง ไม่ใช้LATESTลอยตามrevisionถัดไป:

```bash
export REV_A="$(gcloud run services describe lab004-booking --region="$REGION" --format='value(status.latestReadyRevisionName)')"
gcloud run services update-traffic lab004-booking --region="$REGION" --to-revisions="$REV_A=100"
.venv/bin/python scripts/deploy-service.py \
  --project "$PROJECT_ID" --region "$REGION" --image "$IMAGE_PIN" \
  --auth-version "$AUTH_VERSION" --db-version "$A_VERSION" \
  --app-version v2 --suffix v2-a01 --candidate
```

อ่านdry-runแล้วรันคำสั่งเดิมเพิ่ม --execute ครั้งนี้ใช้imageเดียวกันแต่เปิดv2ผ่านAPP_VERSIONเพื่อแยกการเปลี่ยนพฤติกรรมออกจากschema ไม่มีmigrationลบข้อมูล และยังใช้loginA

```bash
.venv/bin/python scripts/deploy-service.py \
  --project "$PROJECT_ID" --region "$REGION" --image "$IMAGE_PIN" \
  --auth-version "$AUTH_VERSION" --db-version "$A_VERSION" \
  --app-version v2 --suffix v2-a01 --candidate --execute
export REV_V2_A="$(gcloud run services describe lab004-booking --region="$REGION" --format='value(status.latestReadyRevisionName)')"
gcloud run services describe lab004-booking --region="$REGION" --format=json > assets/evidence/T07-service.json
export CANDIDATE_URL="$(python3 -c 'import json; d=json.load(open("assets/evidence/T07-service.json")); print(next(t["url"] for t in d["status"]["traffic"] if t.get("tag")=="candidate"))')"
curl --max-time 15 --fail-with-body "$CANDIDATE_URL/healthz"
```

**Expected:** candidate healthready/version=v2; mainยัง100%REV_A เปิดcandidateURLแล้วloginAlice เห็นbookingเดิม จากนั้น promoteและทดสอบrollback:

```bash
gcloud run services update-traffic lab004-booking --region="$REGION" --to-revisions="$REV_V2_A=100"
curl --max-time 15 --fail-with-body "$SERVICE_URL/healthz"
gcloud run services update-traffic lab004-booking --region="$REGION" --to-revisions="$REV_A=100"
curl --max-time 15 --fail-with-body "$SERVICE_URL/healthz"
```

เปิดmainURLหลังแต่ละสลับ: versionเปลี่ยนตามtrafficแต่bookingเดิมยังconfirmedและreferenceเดิม หลังrollbackยกเลิกรายการนั้นบนv1 แล้วpromoteREV_V2_Aกลับ100%เพื่อเตรียมrotation (ใช้คำสั่งpromoteด้านบนอีกครั้ง)

**Expected:** ไม่มองว่าtrafficเปลี่ยนสำเร็จทันทีเท่ากับทุกclientอยู่revisionใหม่แล้ว รอdescribe trafficและprobeตอบversionเป้าหมาย ถ้าจองเดิมหายให้หยุด ตรวจProject/DB_CONFIG_FILE/instance/database ไม่seedใหม่กลบเหตุ

**บันทึก T07:** bookingreferenceก่อน ___ / v1revision ___ / v2revision ___ / before-after-rollback status ___ / คำอธิบายว่าทำไมrollbackไม่ย้อนDB ___

### Task 8 — หมุน Credential A → B และกำหนดจุดที่ถอยไม่ได้

**ทำที่ไหน:** Cloud Shell กับBrowser; ทำหลังT07ผ่าน

Bถูกสร้างและgrantsเท่ากับAตั้งแต่bootstrap แต่ยังไม่มีrevisionบริการใช้B นี่คือการสลับไปloginคนละตัว ไม่resetpasswordของloginที่ยังรับงาน เพิ่มเลขSecret versionสำหรับconfigurationBที่จะใช้รอบนี้ (payloadเป็นBที่เตรียมไว้ ไม่อ้างว่าเป็นการเปลี่ยนpasswordBรอบใหม่):

```bash
export B_VERSION="$(gcloud secrets versions add lab004-db-b --data-file=secrets/db-b.json --format='value(name)' | awk -F/ '{print $NF}')"
.venv/bin/python scripts/deploy-service.py \
  --project "$PROJECT_ID" --region "$REGION" --image "$IMAGE_PIN" \
  --auth-version "$AUTH_VERSION" --db-version "$B_VERSION" --login b \
  --app-version v2 --suffix v2-b01 --candidate --execute
export REV_B="$(gcloud run services describe lab004-booking --region="$REGION" --format='value(status.latestReadyRevisionName)')"
gcloud run services describe lab004-booking --region="$REGION" --format=json > assets/evidence/T08-service.json
export B_URL="$(python3 -c 'import json; d=json.load(open("assets/evidence/T08-service.json")); print(next(t["url"] for t in d["status"]["traffic"] if t.get("tag")=="candidate"))')"
.venv/bin/python scripts/probe.py --url "$B_URL" --logins secrets/demo-logins.json --mode journey > assets/evidence/T08-B-journey.json
```

**Expected:** Bloginอ่าน/จอง/ยกเลิกได้ ใช้ฐานข้อมูลเดิม ไม่ได้เปิดadminsecretให้runtime หากไม่ผ่านให้คงmaintrafficบนA ตรวจBsecret/grants/DBloginก่อน ไม่ถอนA

เมื่อBผ่านจึงpromote:

```bash
gcloud run services update-traffic lab004-booking --region="$REGION" --to-revisions="$REV_B=100"
gcloud run services describe lab004-booking --region="$REGION" --format='yaml(status.traffic)'
curl --max-time 15 --fail-with-body "$SERVICE_URL/healthz"
```

ก่อนถอนA ยังสามารถrollbackกลับREV_A/REV_V2_Aได้หลังตรวจhealthของA แต่เมื่อถอนAแล้ว revisionเหล่านั้นจะต่อDBใหม่ไม่ได้ **อย่าสั่งtrafficrollbackกลับAหลังจุดนี้** ทางกู้คือdeploycodeรุ่นเดิมโดยใช้validB/configที่ยังใช้ได้ ไม่ใช่คืนรหัสเก่าที่อาจรั่ว

ตรวจไม่มีtagชี้A แล้วลบเฉพาะสองrevisionAที่เก็บชื่อไว้ (ตรวจdescribeก่อนdelete; ห้ามใช้globหรือลบทุกrevision):

```bash
gcloud run revisions describe "$REV_A" --region="$REGION" --format='yaml(metadata.name,spec.serviceAccountName,spec.containers)'
gcloud run revisions describe "$REV_V2_A" --region="$REGION" --format='yaml(metadata.name,spec.serviceAccountName,spec.containers)'
gcloud run revisions delete "$REV_A" --region="$REGION"
gcloud run revisions delete "$REV_V2_A" --region="$REGION"
gcloud run jobs execute lab004-inspect --region="$REGION" --wait
gcloud run jobs logs read lab004-inspect --region="$REGION" --limit=20
```

ตอนตรวจcontainersจะเห็นsecret references/envpathsไม่ใช่payload แต่ยังควรredactprojectmetadataตามนโยบาย รอsnapshotไม่มีconnectionของbooking_a; revisionไม่มีtrafficแต่ยังมีtagก็เรียกใช้งานได้ ต้องตรวจtagsจริง หากAยังมีconnectionให้รอการdrain/scale-downและตรวจworkloadที่ใช้A ไม่terminateconnectionเพื่อให้ตัวเลขผ่าน

เมื่อAไม่มีtraffic/tag/live revision/jobและconnectionsเป็น0 จึงเปลี่ยนinspectjobให้ทำคำสั่งถอนAที่มีguard:

```bash
gcloud run jobs update lab004-inspect --region="$REGION" \
  --args=scripts/inspect-db.py,--retire-a,--confirm-drained
gcloud run jobs execute lab004-inspect --region="$REGION" --wait
gcloud run jobs logs read lab004-inspect --region="$REGION" --limit=20
gcloud run jobs update lab004-inspect --region="$REGION" --args=scripts/inspect-db.py
gcloud secrets versions disable "$A_VERSION" --secret=lab004-db-a
.venv/bin/python scripts/probe.py --url "$SERVICE_URL" --logins secrets/demo-logins.json --mode journey > assets/evidence/T08-after-retire.json
```

**Expected:** Arolcanlogin=false, B=true, ไม่มีAconnection, businessjourneyBยังผ่าน, invariantว่าง Guardเป็นDBcheckร่วมกับการยืนยันของผู้ทำ ไม่สามารถตรวจCloudRuntrafficให้เอง NOLOGINไม่ฆ่าexistingconnections และไม่พิสูจน์ว่าBcredentialsถูกต้องหากไม่ได้ทำjourneyก่อน อย่าใช้--confirm-drainedแทนการตรวจจริง

**บันทึก T08:** Bversion/revision ___ / ผลก่อนpromote ___ / Atraffic/tags/connection0หลักฐาน ___ / A NOLOGIN ___ / ผลหลังถอนA ___ / rollback boundary ___

## สถานะการจัดทำ

ยืนยัน identity/network/schema/rotation/connection budget → working App + PostgreSQL integration tests + container → deployment/IaC materials → Diagramตามscopeจริง → READMEพาทำครบjourney/negative/ops/change/cleanup → Review/render/Guide-ready

สถานะ Authoring: มี App UI/API, schema/seed/invariants, bounded pool, secret generator, bootstrap/grants และ Dockerfile พร้อม PostgreSQL integration tests กำลังตรวจ cloud CI ยังไม่มีคู่มือ Deploy เต็มหรือผล GCP จริง

ไฟล์ประกอบ: [App](app/main.py), [DB pool/connector](app/database.py), [UI](app/templates/index.html), [schema](db/schema.sql), [seed](db/seed.sql), [grants](db/grants.sql), [invariants](db/check-invariants.sql), [secret generator](scripts/create-secrets.py), [bootstrap](scripts/init-db.py), [tests](tests/test_booking.py)

App pool4/max_overflow0, pool wait3s, statement5s, lock3s ใช้ Gunicorn1worker/16threads ทำให้จำนวน pool ต่อ instanceชัด ไม่เพิ่ม workers โดยไม่คูณ connection budget Runtime DB logins booking_a/booking_b ไม่มี superuser/DDL/delete-ledger ส่วน admin bootstrap เป็น jobแยก ไม่ใช้ credentialเดียวกับ App

## แหล่งอ้างอิงขอบเขต

- [Cloud Run Direct VPC egress](https://docs.cloud.google.com/run/docs/configuring/vpc-direct-vpc)
- [Cloud SQL private services access](https://docs.cloud.google.com/sql/docs/postgres/configure-private-services-access)
- [Cloud Run Secret Manager integration](https://docs.cloud.google.com/run/docs/configuring/services/secrets)
