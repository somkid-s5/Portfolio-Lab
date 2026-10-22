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
| R2 | แยก App user ออกจาก Cloud IAM | ไม่มี session ได้ 401, ผู้ใช้หนึ่งอ่าน/ยกเลิกของอีกคนไม่ได้, role operator ตาม scope; runtime SA/deployer/invoker มีหน้าที่คนละส่วน |
| R3 | ไม่จองเกิน capacity และ retry ไม่ซ้ำ | ยิงคำขอพร้อมกันแบบจำกัด, retry key เดิม, ตรวจ confirmed bookings ต่อ slot ไม่เกิน capacity และ cancellation คืนที่นั่งครั้งเดียว |
| R4 | ข้อมูลอยู่ข้าม revision และ rollback | จองบน v1 → Deploy v2 → อ่านรายการเดิม → ชี้ traffic กลับ v1 → อ่าน/ยกเลิกได้ โดย schema ยังเข้ากัน |
| R5 | DB private และ Secret เข้าถึงเฉพาะ runtime | Cloud SQL ไม่มี public IP; Cloud Run ต่อ private IP ผ่าน Direct VPC + connector; SA ไม่เกี่ยวข้องอ่าน secret ไม่ได้; ไม่ใส่ password ใน image/Repo/logs |
| R6 | หมุน DB credential อย่างควบคุม | เตรียม login B/grants เท่ากัน + secret version ใหม่, deploy revision ใช้ B, verify, ถอน A หลังไม่เหลือ traffic/connection; บันทึก rollback boundary ไม่สัญญาว่า old credential ยังใช้ได้หลัง revoke |
| R7 | เพิ่ม concurrency โดยคง data/connection safety | เปลี่ยน 8→16, pool4/instance, max instance ตามขอบเขต; วัด request/error/latency + active DB connections และ business invariants ก่อน/หลัง |
| R8 | Dependency fault/recovery และ Cleanup | ตั้ง config/DB access ที่ผิดแบบจำกัดบน no-traffic revision, ตรวจ health/logs แล้วแก้; ลบ Run/SQL/secrets/images/VPC/PSA ตาม inventory และบันทึก rebuild commit |

## Architecture และขอบเขตที่เลือก

- Singapore region, Cloud Run service เดียวให้ UI/API ด้วย managed run.app HTTPS endpoint ไม่ต้องมี domain หรือ LB เพิ่ม
- Cloud SQL PostgreSQL 16, Enterprise edition, private services access (PSA), **ไม่มี public IP**; baseline single-zone ไม่อ้าง database HA ซึ่งจะเจาะใน Lab 05
- Custom VPC และ regional subnet สำหรับ Direct VPC egress; PSA allocated range เป็น service-producer allocation ไม่ใช่ subnet ของ VM
- Cloud SQL Python Connector ใช้ private IP และจัดการ TLS/instance identity; connector ไม่สร้าง network path ให้เอง ต้องมี Direct VPC/PSA จริง
- Runtime service account เฉพาะ Lab มี Cloud SQL Client และ Secret Accessor เฉพาะ secret ที่ต้องใช้ ไม่ใช้ default Compute SA หรือ project-wide Editor
- Secret Manager เก็บ DB login configuration, demo user password hashes และ session signing key ใช้ version ที่ pin ชัดสำหรับแต่ละ revision ไม่ใช้ latest แบบอธิบายผล rotation ไม่ได้
- Container images ใน Artifact Registry; Dockerfile/runtime code/schema/seed/probes อยู่ใน Lab นี้ ไม่พึ่ง resource ของ Lab ก่อน

## Identity และ Browser flow

เลือก public Cloud Run entry สำหรับหน้า login แต่ทุก business endpoint ต้องผ่าน App session/role/ownership checks Public invoker ไม่ใช่การเปิดข้อมูล booking และไม่ใช่หลักฐานว่า IAM ยืนยัน end user ให้

App ใช้ demo users/booker/operator, password hashes, HttpOnly Secure SameSite cookies, session expiry และ CSRF สำหรับ state-changing requests บน HTTPS แยก deployer IAM, runtime service identity และ App identity อย่างชัดเจน ไม่อ้างว่า demo login เป็น enterprise SSO หาก organization ห้าม public invoker ให้หยุด baseline และออกแบบทางเข้าใหม่โดยไม่ปิด policy

ไม่ทำ UI ที่เก็บ DB password หรือ privileged token ใน browser, URL query, localStorage หรือ screenshot หลักฐานต้อง redact cookie/secret values

## Business data และ App contract

เตรียม slots อย่างน้อย 5 ช่วงพร้อม capacity, users สองคนและ operator, bookings/status/idempotency/audit fields มี transaction/row lock หรือ conditional mutation ที่พิสูจน์ invariant ได้ UI รองรับ list/reserve/cancel และแสดง booking reference/request ID ไม่ให้ผู้เรียนไปคิด App ใหม่

มี /livez ตรวจ process, /healthz ตรวจ DB/schema และ structured request/dependency logs แบบไม่เผย credentials การ pool ต้องปิด connection กลับ pool ครบเมื่อ exception มี bounded wait/statement timeouts ไม่สร้าง unbounded reconnect loop

v1/v2 ใช้ schema compatible กันใน baseline ไม่ยัด destructive migration ลง rollback demo การเปลี่ยน schema ในอนาคตต้องแยก expand/contract และบอก boundary ก่อน deploy

## Connection budget และต้นทุนก่อนลงมือ

เริ่ม concurrency8, application pool สูงสุด 4 ต่อ instance และ max instance2 เป็นค่าฝึก ไม่ใช่ capacity recommendation สำหรับ production ระหว่าง rollout อาจมีหลาย revision/instance และแพลตฟอร์มอาจเกินเป้าชั่วคราว จึงคำนวณเผื่อ old+new revisions, admin connections และ monitor pg_stat_activity ไม่อ้าง max-instances เป็น hard cap ของ DB connections

Cloud SQL คิดค่าใช้จ่ายแม้ Run scale-to-zero; มี storage/backup/PSA/Artifact Registry/Secret/egress/logs ตามใช้ เลือก machine/region/edition/quota และเวลาปิดใน Guide ก่อนสร้าง Budget เป็น alert ไม่ใช่ hard cap งานจัดทำเอกสารนี้ไม่ provision GCP resources

## Rotation และ Failure drill ที่ต้องออกแบบให้ครบ

DB credential rotation ใช้สอง login ชั่วคราว A/B เพื่อให้ revision เก่ากับใหม่ทำงานคู่กันได้โดยไม่ reset password ของ login ที่ยังรับงานทันที หลัง verifyB แล้วค่อย retireA หาก revokeA แล้วต้องกู้ด้วย login/secret ที่ยัง valid ไม่ใช่ blind traffic rollback

Fault ใช้ revision ที่ไม่รับ production traffic ใน sandbox และมี tag สำหรับทดสอบจำกัด ไม่ทำลาย DB เพื่อให้มี incident ต้องบันทึก error/สาเหตุ/การแก้/retest จริง พร้อมลบ fault revision ตอนปิดงาน


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

อ่าน Plan ก่อน Apply: VPC lab004-vpc, subnet 10.44.0.0/24, PSA range 10.84.0.0/16, PostgreSQL16 Enterprise ZONAL, SSD10GB fixed size, private IP เท่านั้น, backups2/PITR1 วัน, Secret containers4 ชื่อ, SA runtime/bootstrap และ Artifact Registry1 แห่ง ไม่ควรมีการลบของระบบอื่นหรือ secret payload ใน Plan ห้ามเปลี่ยน CIDR ถ้าไม่ตรวจว่าทับเครือข่ายที่ต้องเชื่อมต่อหรือไม่

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

**Expected:** ได้เลข version บวก 4 ค่า ไม่ใช่ latest; คำสั่งไม่แสดง payload Runtime SA อ่านเฉพาะ auth/db-a/db-b ส่วน bootstrap อ่าน admin/db-a/db-b ไม่อ่าน auth บัญชีผู้ใช้ที่ Deploy ต้องมี iam.serviceAccounts.actAs บน SA ที่ใช้ ผู้ดูแลสามารถให้ Service Account User เฉพาะ runtime/bootstrap ดังนี้:

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

**Expected:** digest รูป sha256: ตามด้วย 64 ตัวอักษร ไม่ใช้ tag ที่อาจถูกเขียนทับตอน Deploy ถ้า push denied ตรวจ active account และสิทธิ์ Artifact Registry ใน repo lab004-images; อย่าเอา runtime SA ไปเป็น image builder หรือมอบ Editor ให้ runtime

**บันทึก T03:** Commit ___ / Image digest ___ / Build result ___ / ไม่พบ secret ใน context ___

### Task 4 — Bootstrap ฐานข้อมูลด้วย Job แยก

**ทำที่ไหน:** Cloud Shell; Job รันใน Cloud Run ผ่าน Direct VPC ภายใน region เดียวกัน

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

**Expected:** execution สำเร็จ และข้อความ Schema, seed and least-privilege logins created atomically ไม่มี password จะได้ slots5 แถว/schema/booking_a/booking_b ที่ไม่ใช่ superuser การสร้างทั้งหมดอยู่ใน transaction เดียว

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

ครั้งแรกเป็น **dry-run** อ่าน command ที่แสดง: runtime SA ถูกตัว, Direct VPC/subnet ถูก, DB private config, secret version เป็นเลข, concurrency8, max-instances2, pool ใน App4/instance, ไม่มี APP_LOCAL_TEST หรือ admin secret จากนั้นรันชุดเดิมโดยเติม `--execute`:

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

**Expected:** livez alive=true/version=v1; healthz ready=true; ไม่ login แล้ว bookings=401 login_required (ตั้งใจให้ curl คำสั่งนี้ไม่ใช้ --fail) Startup/liveness ตรวจ process ไม่บังคับ restart ทุกครั้งที่ DB ขัดข้อง การ deploy สำเร็จจึงยังไม่พิสูจน์ DB ต้องตรวจ healthz แยก

เปิด SERVICE_URL → หน้า Booking → เปิด demo-logins.json ใน Editor แบบส่วนตัว → login alice → เห็น 5slots → จองช่วงที่เลือก → รายการของฉันมี booking → ยกเลิกแล้วสถานะ cancelled จำนวนที่นั่งกลับคืน Login cookie เป็น Secure/HttpOnly/SameSite=Lax และหมดอายุเมื่อไม่มี activity10 นาที ไม่มีการใส่ DB secret ใน Browser

หาก revision เดิมชื่อ v1-a01 มีอยู่แล้ว ให้ตรวจว่า Deploy เดิมสำเร็จหรือไม่ก่อน เลือก suffix ใหม่เช่น v1-a02 เมื่อกำลังสร้าง revision ใหม่ ไม่ลบของเดิมเพื่อให้ชื่อว่าง
- livez ไม่ผ่าน: ดู container import/startup/secret mount/PORT
- livez ผ่านแต่ healthz503: ดู database_unavailable, SQLClient/SecretAccessor, VPC/PSA/region, admin bootstrap, DB login และ version ไม่พิมพ์ connection string ที่มี password
- Cloud Run403 ก่อนเห็นหน้า login: ตรวจ invoker policy และ org policy ไม่ใช่รหัส alice ผิด
- login401: ตรวจ demo user/password จาก bundle เดียวกับ auth version; login403csrf_required: refresh หน้าและรับ session ใหม่ ไม่ปิด CSRF

**บันทึก T05:** URL ___ / Ready revision ___ / Secret versions ___ / livez-healthz-anonymous statuses ___ / Alice booking reference+cancel result ___ / Screenshot หลัง login ที่ไม่เห็นรหัส ___

**เกณฑ์ไปต่อ:** Browser journey สำเร็จและ healthz ผ่าน จด revision v1 ไว้สำหรับเปรียบเทียบ v2/rollback ใน Task ถัดไป


### Task 6 — พิสูจน์ Business Rules และตรวจฐานข้อมูล

**ทำที่ไหน:** Cloud Shell และ Cloud Run Jobs ใช้เฉพาะข้อมูลสังเคราะห์ของ Lab

```bash
cd "$LAB_ROOT"
mkdir -p assets/evidence
.venv/bin/python scripts/probe.py --url "$SERVICE_URL" --logins secrets/demo-logins.json \
  --mode journey > assets/evidence/T06-journey.json
```

**Expected:** exit0/checks=completed; anonymous401, ไม่มี CSRF403, reserve201 → retrykey เดิม 200/bookingID เดิม, Bob อ่าน/ยกเลิก Alice404, booker เข้า operator403, operator อ่าน 200, cancel ครั้งแรก replayed=false และครั้งต่อไป true Probe ยกเลิกเฉพาะรายการที่ตนสร้าง ไม่เปลี่ยนรายการที่ผู้เรียนจองไว้

เปิด Browser ตรวจและยกเลิก **ทุก confirmed booking ใน slot1** ของ Alice/Bob/operator ให้ booked=0 ก่อน race ห้ามลบ DBrows เพื่อให้ผ่าน:

```bash
.venv/bin/python scripts/probe.py --url "$SERVICE_URL" --logins secrets/demo-logins.json \
  --mode race > assets/evidence/T06-capacity-race.json
```

**Expected:** seed slot1 capacity2, ผู้ใช้ต่างกัน 3 คนส่งพร้อมกัน ได้ 201 สองคำขอและ 409 หนึ่งคำขอ; booked ไม่เกิน 2 และกลับ 0 หลัง probe ยกเลิก ทั้งนี้ต้องไม่มีผู้ใช้อื่นกำลังแก้ slot1 พร้อมกัน ถ้า response หายหรือ probe ล้ม ให้ตรวจรายการใน Browser/DB ก่อนยิงซ้ำ ไม่สมมติว่าคำขอที่ timeout ไม่เกิดผล

ตรวจ DB ด้วย Job อ่านอย่างเดียว ใช้ bootstrap SA/admin config แยกจาก App เพราะต้องเห็น connection และ role metadata ไม่เปิด PostgreSQL ผ่าน Public IP:

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

**Expected:** invariant_violations=[]; slots มี capacity/booked ถูกต้อง; runtime roles rolsuper/rolcreatedb/rolcreaterole=false โดย roleA/B อาจยัง LOGIN ได้ทั้งคู่ ข้อมูล connections เป็น snapshot ในขณะ Job อ่าน ไม่ใช่ค่าสูงสุดตลอดการทดสอบ ห้ามแปล booked=0 เป็นไม่มี historicalbookings เพราะรายการ cancelled ยังเก็บอยู่

**บันทึก T06:** journey ผล ___ / race HTTPcounts ___ / invariant violations ___ / DBconnections snapshot ___ / exitcodes ___ / requestID ตัวอย่าง ___

### Task 7 — Deploy v2 แล้ว Rollback โดยไม่ย้อนข้อมูล

**ทำที่ไหน:** Browser + Cloud Shell

1. ใน Browser loginAlice จอง slot ที่ว่างหนึ่งรายการและ **ยังไม่ยกเลิก** จด bookingreference/slot/status เป็นหลักฐานก่อน Deploy
2. เก็บชื่อ v1 และ pin traffic กับ revision จริง ไม่ใช้ LATEST ลอยตาม revision ถัดไป:

```bash
export REV_A="$(gcloud run services describe lab004-booking --region="$REGION" --format='value(status.latestReadyRevisionName)')"
gcloud run services update-traffic lab004-booking --region="$REGION" --to-revisions="$REV_A=100"
.venv/bin/python scripts/deploy-service.py \
  --project "$PROJECT_ID" --region "$REGION" --image "$IMAGE_PIN" \
  --auth-version "$AUTH_VERSION" --db-version "$A_VERSION" \
  --app-version v2 --suffix v2-a01 --candidate
```

อ่าน dry-run แล้วรันคำสั่งเดิมเพิ่ม --execute ครั้งนี้ใช้ image เดียวกันแต่เปิด v2 ผ่าน APP_VERSION เพื่อแยกการเปลี่ยนพฤติกรรมออกจาก schema ไม่มี migration ลบข้อมูล และยังใช้ loginA

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

**Expected:** candidate healthready/version=v2; main ยัง 100%REV_A เปิด candidateURL แล้ว loginAlice เห็น booking เดิม จากนั้น promote และทดสอบ rollback:

```bash
gcloud run services update-traffic lab004-booking --region="$REGION" --to-revisions="$REV_V2_A=100"
curl --max-time 15 --fail-with-body "$SERVICE_URL/healthz"
gcloud run services update-traffic lab004-booking --region="$REGION" --to-revisions="$REV_A=100"
curl --max-time 15 --fail-with-body "$SERVICE_URL/healthz"
```

เปิด mainURL หลังแต่ละสลับ: version เปลี่ยนตาม traffic แต่ booking เดิมยัง confirmed และ reference เดิม หลัง rollback ยกเลิกรายการนั้นบน v1 แล้ว promoteREV_V2_A กลับ 100%เพื่อเตรียม rotation (ใช้คำสั่ง promote ด้านบนอีกครั้ง)

**Expected:** ไม่มองว่า traffic เปลี่ยนสำเร็จทันทีเท่ากับทุก client อยู่ revision ใหม่แล้ว รอ describe traffic และ probe ตอบ version เป้าหมาย ถ้าจองเดิมหายให้หยุด ตรวจ Project/DB_CONFIG_FILE/instance/database ไม่ seed ใหม่กลบเหตุ

**บันทึก T07:** bookingreference ก่อน ___ / v1revision ___ / v2revision ___ / before-after-rollback status ___ / คำอธิบายว่าทำไม rollback ไม่ย้อน DB ___

### Task 8 — หมุน Credential A → B และกำหนดจุดที่ถอยไม่ได้

**ทำที่ไหน:** Cloud Shell กับ Browser; ทำหลัง T07 ผ่าน

B ถูกสร้างและ grants เท่ากับ A ตั้งแต่ bootstrap แต่ยังไม่มี revision บริการใช้ B นี่คือการสลับไป login คนละตัว ไม่ resetpassword ของ login ที่ยังรับงาน เพิ่มเลข Secret version สำหรับ configurationB ที่จะใช้รอบนี้ (payload เป็น B ที่เตรียมไว้ ไม่อ้างว่าเป็นการเปลี่ยน passwordB รอบใหม่):

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

**Expected:** Blogin อ่าน/จอง/ยกเลิกได้ ใช้ฐานข้อมูลเดิม ไม่ได้เปิด adminsecret ให้ runtime หากไม่ผ่านให้คง maintraffic บน A ตรวจ Bsecret/grants/DBlogin ก่อน ไม่ถอน A

เมื่อ B ผ่านจึง promote:

```bash
gcloud run services update-traffic lab004-booking --region="$REGION" --to-revisions="$REV_B=100"
gcloud run services describe lab004-booking --region="$REGION" --format='yaml(status.traffic)'
curl --max-time 15 --fail-with-body "$SERVICE_URL/healthz"
```

ก่อนถอน A ยังสามารถ rollback กลับ REV_A/REV_V2_A ได้หลังตรวจ health ของ A แต่เมื่อถอน A แล้ว revision เหล่านั้นจะต่อ DB ใหม่ไม่ได้ **อย่าสั่ง trafficrollback กลับ A หลังจุดนี้** ทางกู้คือ deploycode รุ่นเดิมโดยใช้ validB/config ที่ยังใช้ได้ ไม่ใช่คืนรหัสเก่าที่อาจรั่ว

ตรวจไม่มี tag ชี้ A แล้วลบเฉพาะสอง revisionA ที่เก็บชื่อไว้ (ตรวจ describe ก่อน delete; ห้ามใช้ glob หรือลบทุก revision):

```bash
gcloud run revisions describe "$REV_A" --region="$REGION" --format='yaml(metadata.name,spec.serviceAccountName,spec.containers)'
gcloud run revisions describe "$REV_V2_A" --region="$REGION" --format='yaml(metadata.name,spec.serviceAccountName,spec.containers)'
gcloud run revisions delete "$REV_A" --region="$REGION"
gcloud run revisions delete "$REV_V2_A" --region="$REGION"
gcloud run jobs execute lab004-inspect --region="$REGION" --wait
gcloud run jobs logs read lab004-inspect --region="$REGION" --limit=20
```

ตอนตรวจ containers จะเห็น secret references/envpaths ไม่ใช่ payload แต่ยังควร redactprojectmetadata ตามนโยบาย รอ snapshot ไม่มี connection ของ booking_a; revision ไม่มี traffic แต่ยังมี tag ก็เรียกใช้งานได้ ต้องตรวจ tags จริง หาก A ยังมี connection ให้รอการ drain/scale-down และตรวจ workload ที่ใช้ A ไม่ terminateconnection เพื่อให้ตัวเลขผ่าน

เมื่อ A ไม่มี traffic/tag/live revision/job และ connections เป็น 0 จึงเปลี่ยน inspectjob ให้ทำคำสั่งถอน A ที่มี guard:

```bash
gcloud run jobs update lab004-inspect --region="$REGION" \
  --args=scripts/inspect-db.py,--retire-a,--confirm-drained
gcloud run jobs execute lab004-inspect --region="$REGION" --wait
gcloud run jobs logs read lab004-inspect --region="$REGION" --limit=20
gcloud run jobs update lab004-inspect --region="$REGION" --args=scripts/inspect-db.py
gcloud secrets versions disable "$A_VERSION" --secret=lab004-db-a
.venv/bin/python scripts/probe.py --url "$SERVICE_URL" --logins secrets/demo-logins.json --mode journey > assets/evidence/T08-after-retire.json
```

**Expected:** Arolcanlogin=false, B=true, ไม่มี Aconnection, businessjourneyB ยังผ่าน, invariant ว่าง Guard เป็น DBcheck ร่วมกับการยืนยันของผู้ทำ ไม่สามารถตรวจ CloudRuntraffic ให้เอง NOLOGIN ไม่ฆ่า existingconnections และไม่พิสูจน์ว่า Bcredentials ถูกต้องหากไม่ได้ทำ journey ก่อน อย่าใช้--confirm-drained แทนการตรวจจริง

**บันทึก T08:** Bversion/revision ___ / ผลก่อน promote ___ / Atraffic/tags/connection0 หลักฐาน ___ / A NOLOGIN ___ / ผลหลังถอน A ___ / rollback boundary ___


### Task 9 — แยก IAM Boundary และซ้อม Dependency Fault

**ทำที่ไหน:** Cloud Shell / Cloud Run Jobs / Logs Explorer

#### 9A — พิสูจน์ว่า Runtime อ่าน Admin Secret ไม่ได้

ใช้ Job ที่รันด้วย **runtime SA จริง** ไม่ใช่บัญชี Cloud Shell และไม่ mountadminsecret คำสั่งจะเรียก Secret API แต่ไม่แสดง payload แม้เผลอได้สิทธิ์อ่านจริง หากได้ 200 ให้ถือว่า **ไม่ผ่าน** แล้วตรวจ inherited/project-wide IAM

```bash
gcloud run jobs create lab004-access-check --region="$REGION" \
  --image="$IMAGE_PIN" --service-account="$RUNTIME_SA" \
  --tasks=1 --parallelism=1 --max-retries=0 --task-timeout=120s \
  --command=python \
  --args="scripts/check-secret-boundary.py,--project,$PROJECT_ID,--version,$ADMIN_VERSION"
gcloud run jobs execute lab004-access-check --region="$REGION" --wait
gcloud run jobs logs read lab004-access-check --region="$REGION" --limit=20
```

**Expected:** runtime_cannot_read_bootstrap_admin, status403, denied=true; 401/404/5xx ไม่ใช่หลักฐานสิทธิ์ถูกต้อง ตรวจ secret/version มีอยู่จริงและบัญชี runtime ที่ Job ใช้ด้วย ไม่อนุมานว่าได้ 403 จาก serviceentry คือ SecretAPI ปฏิเสธ

#### 9B — ทำ Config ผิดเฉพาะ Revision ที่ไม่รับ Main Traffic

ตรวจ main100%อยู่ B และเก็บ configuration ก่อนเปลี่ยน ใช้ชื่อตัวอย่าง instance ที่ไม่มีจริง ไม่ปิด CloudSQL หรือถอนสิทธิ์จาก revision ที่ให้บริการอยู่:

```bash
gcloud run services describe lab004-booking --region="$REGION" --format=json > assets/evidence/T09-before.json
gcloud run services update-traffic lab004-booking --region="$REGION" --to-revisions="$REV_B=100"
gcloud run services update lab004-booking --region="$REGION" \
  --update-env-vars="INSTANCE_CONNECTION_NAME=$PROJECT_ID:$REGION:lab004-missing-instance" \
  --revision-suffix fault01 --no-traffic --tag fault
export FAULT_REV="$(gcloud run services describe lab004-booking --region="$REGION" --format='value(status.latestCreatedRevisionName)')"
gcloud run services describe lab004-booking --region="$REGION" --format=json > assets/evidence/T09-fault.json
export FAULT_URL="$(python3 -c 'import json; d=json.load(open("assets/evidence/T09-fault.json")); print(next(t["url"] for t in d["status"]["traffic"] if t.get("tag")=="fault"))')"
curl --max-time 20 -i "$FAULT_URL/livez"
curl --max-time 20 -i "$FAULT_URL/healthz"
curl --max-time 20 --fail-with-body "$SERVICE_URL/healthz"
```

**Expected:** fault/live200 แต่ fault/health503 database_unavailable; main ยัง health200 ไม่ promotefault การ DeployReady อย่างเดียวตรวจไม่พบ DBconfig ผิดเพราะ startup ตรวจ process หาก URL ยังไม่พร้อมให้ตรวจ revisionconditions ก่อน ไม่สลับ traffic เพื่อให้เรียกถึง

เปิด **Logging → Logs Explorer** เลือก Project นี้และใช้ filter:

```text
resource.type="cloud_run_revision"
resource.labels.service_name="lab004-booking"
jsonPayload.event="database_unavailable"
```

จด revision/request_id/time/error_type และจับคู่กับ HTTPresponse ไม่แนบ Authorization/Cookie/Secret payload หากไม่มี structuredfield ให้ดู stdoutpayload รูป JSON ตาม request ID เดียวกัน แยกสาเหตุจาก config ที่ตั้งผิด ไม่อ้างว่าเป็น networkoutage จริง

สร้าง revision แก้โดยคืน configuration ทั้งหมดผ่าน helper ใช้ validB ไม่ย้อน A ที่ถูกถอนแล้ว:

```bash
.venv/bin/python scripts/deploy-service.py \
  --project "$PROJECT_ID" --region "$REGION" --image "$IMAGE_PIN" \
  --auth-version "$AUTH_VERSION" --db-version "$B_VERSION" --login b \
  --app-version v2 --suffix v2-b02 --candidate --execute
export REV_RECOVERY="$(gcloud run services describe lab004-booking --region="$REGION" --format='value(status.latestReadyRevisionName)')"
gcloud run services describe lab004-booking --region="$REGION" --format=json > assets/evidence/T09-recovered.json
export RECOVERY_URL="$(python3 -c 'import json; d=json.load(open("assets/evidence/T09-recovered.json")); print(next(t["url"] for t in d["status"]["traffic"] if t.get("tag")=="candidate"))')"
.venv/bin/python scripts/probe.py --url "$RECOVERY_URL" --logins secrets/demo-logins.json --mode journey > assets/evidence/T09-recovery-journey.json
gcloud run services update-traffic lab004-booking --region="$REGION" --to-revisions="$REV_RECOVERY=100" --remove-tags=fault
gcloud run revisions describe "$FAULT_REV" --region="$REGION" --format='value(metadata.name)'
gcloud run revisions delete "$FAULT_REV" --region="$REGION"
```

**Expected:** recoveryjourney ผ่าน, mainhealth200, faulttag หายและ faultrevision ถูกลบ อย่าลบ REV_B เพราะยังเป็น fallback ที่ใช้ B ได้ หากมี fault ชื่อเดิมจากการลองก่อน ให้ตรวจ inventory และเลือก suffix ใหม่ ไม่ delete โดยไม่รู้ว่าเป็นตัวใด

**บันทึก T09:** IAMtestprincipal/status ___ / faultrevision ___ / HTTP live-health-main ___ / requestID+log สาเหตุ ___ / recoveryrevision+journey ___ / faultcleanup ___ / timeline ตรวจพบ-แก้-ยืนยัน ___

### Task 10 — Change Request: Concurrency 8 → 16 ภายใต้ Connection Budget เดิม

**โจทย์จากทีม:** อยากให้บริการรองรับคำขอพร้อมกันมากขึ้น แต่ห้ามเกิด overbooking หรือเพิ่ม DBpool ตามแบบไม่คำนวณ

ก่อนเปลี่ยนเขียนทางเลือก: เพิ่ม instance, เพิ่ม concurrency, เพิ่ม pool หรือปรับ query ต่างมีผลต่อ cost/latency/connection อย่างไร Lab นี้เลือกทดลอง concurrency8→16, pool4, Gunicorn1worker16threads, max-instances2 ต่อ revision เดิม ไม่เพิ่ม pool หรือ workers ระหว่าง rollout มีหลาย revision และ instance อาจเกินเป้าชั่วคราว จึงต้องเผื่อ connection มากกว่า 2×4 และไม่ใช้ 40(max_connections)จนไม่มี adminheadroom

**ทำที่ไหน:** Cloud Shell และ Monitoring ใน Sandbox เท่านั้น จำกัด **80 read requests / 16 workers / หนึ่งรอบต่อค่า** timeout10s ต่อ request ไม่มี retryloop ไม่สิ้นสุด Probelogin แต่ละ worker ตามลำดับก่อนวัด read เพื่อไม่ให้ passwordhash พร้อมกันกลบผล โหลดนี้ไม่ใช่ productionbenchmark หรือ stress จน DB เต็ม

```bash
export REV_BASELINE="$REV_RECOVERY"
.venv/bin/python scripts/probe.py --url "$SERVICE_URL" --logins secrets/demo-logins.json \
  --mode read-load --requests 80 --workers 16 > assets/evidence/T10-before-c8.json
gcloud run jobs execute lab004-inspect --region="$REGION" --wait
gcloud run jobs logs read lab004-inspect --region="$REGION" --limit=20
```

ใน Console เปิด **Cloud Run → lab004-booking → Metrics** ดู request count/latency/instancecount ในช่วงเวลาทดสอบ และ **Monitoring → Metrics Explorer → Cloud SQL Database → PostgreSQL backend connections** (metric `cloudsql.googleapis.com/database/postgresql/num_backends`) เลือก instance lab004-sql, region เดียวกัน เก็บช่วงเวลา/alignment/aggregation ให้เทียบกันได้ Metrics อาจมาช้า; snapshotinspect ไม่ใช่ peak ตลอดช่วง

```bash
.venv/bin/python scripts/deploy-service.py \
  --project "$PROJECT_ID" --region "$REGION" --image "$IMAGE_PIN" \
  --auth-version "$AUTH_VERSION" --db-version "$B_VERSION" --login b \
  --app-version v2 --concurrency 16 --suffix v2-b-c16 --candidate --execute
export REV_C16="$(gcloud run services describe lab004-booking --region="$REGION" --format='value(status.latestReadyRevisionName)')"
gcloud run services describe lab004-booking --region="$REGION" --format=json > assets/evidence/T10-candidate.json
export C16_URL="$(python3 -c 'import json; d=json.load(open("assets/evidence/T10-candidate.json")); print(next(t["url"] for t in d["status"]["traffic"] if t.get("tag")=="candidate"))')"
curl --max-time 20 --fail-with-body "$C16_URL/healthz"
.venv/bin/python scripts/probe.py --url "$C16_URL" --logins secrets/demo-logins.json --mode journey > assets/evidence/T10-candidate-journey.json
gcloud run services update-traffic lab004-booking --region="$REGION" --to-revisions="$REV_C16=100"
.venv/bin/python scripts/probe.py --url "$SERVICE_URL" --logins secrets/demo-logins.json \
  --mode read-load --requests 80 --workers 16 > assets/evidence/T10-after-c16.json
.venv/bin/python scripts/probe.py --url "$SERVICE_URL" --logins secrets/demo-logins.json --mode journey > assets/evidence/T10-journey.json
.venv/bin/python scripts/probe.py --url "$SERVICE_URL" --logins secrets/demo-logins.json --mode race > assets/evidence/T10-race.json
gcloud run jobs execute lab004-inspect --region="$REGION" --wait
gcloud run jobs logs read lab004-inspect --region="$REGION" --limit=20
```

ก่อน race ต้อง slot1 ว่าง capacity2 เช่น T06 หากมีรายการอื่นให้เจ้าของยกเลิกก่อน ไม่ clear ทั้งฐานข้อมูลเพราะจะทำลายหลักฐานข้อมูลคงอยู่

**Expected:** read80 ครั้งในแต่ละรอบได้ 200 ทั้งหมด, journey/race ผ่าน, invariant_violations=[] และ connection ยังมี headroom หาก 503/pooltimeout/latency สูงให้ถือเป็นผลที่ต้องวิเคราะห์ ไม่สรุปว่าความเร็วดีกว่าเพียงเพราะ Deploy ผ่าน ค่า p50/p95 เป็นตัวอย่างขนาดเล็ก รวม cold-start ได้ ไม่แทน SLO

ถ้า candidatehealth หรือ journey ไม่ผ่านก่อน promote ให้คง baseline หากเปลี่ยนแล้วมีผลเสียให้ backout:

```bash
gcloud run services update-traffic lab004-booking --region="$REGION" --to-revisions="$REV_BASELINE=100"
curl --max-time 20 --fail-with-body "$SERVICE_URL/healthz"
```

**บันทึก T10:**

| ตัวชี้วัด | ก่อน C8 (Actual) | หลัง C16 (Actual) |
|---|---|---|
| Revision / image digest | ___ | ___ |
| 200 / non-200 / sample count | ___ | ___ |
| p50 / p95 ms | ___ | ___ |
| DB connections: snapshot / observed metric peak+window | ___ | ___ |
| Invariant violations / race statuses | ___ | ___ |
| จำนวน instances / cold start observations | ___ | ___ |

ตัดสินใจเก็บ C16 หรือกลับ C8 ___ / เหตุผลจากข้อมูล ___ / สิ่งที่ยังสรุปไม่ได้ ___ / ผลหลัง backout ถ้าทำ ___

### Task 11 — สรุปหลักฐานและส่งมอบ Runbook

ผลต่อไปนี้เป็น **ช่องให้บันทึก Actual** ไม่ใช่ผล PASS ที่มีให้ล่วงหน้า เอกสาร/CI ทดสอบในฐานข้อมูลชั่วคราวไม่พิสูจน์ GCP IAM/DirectVPC/SQL/TLS จริง

| Requirement | หลักฐานที่ต้องชี้ได้ | Actual / สถานะ |
|---|---|---|
| R1 / journey | T05 Browser + T06 HTTP | ___ |
| R2 / app identity | T06 401/403/404 + role checks | ___ |
| R3 / transaction correctness | T06/T10 race + replay/cancel + DB invariant | ___ |
| R4 / revision persistence | T07 bookingreference ก่อน-หลัง-rollback | ___ |
| R5 / private + IAM | T01 no publicIP + T09A runtime403 + runtimeconfig | ___ |
| R6 / credential rotation | T08 Bjourney + A0connections/NOLOGIN + rollbackboundary | ___ |
| R7 / change | T10 config/results/decision | ___ |
| R8 / recovery + cleanup | T09 fault/log/recovery + T12 inventory | ___ |

**Case study ที่เขียนด้วยตนเอง:** ปัญหาของทีม ___ / ข้อจำกัด ___ / สถาปัตยกรรมและเหตุผล ___ / สิ่งที่ตนทำ ___ / ผลที่วัดได้พร้อมหลักฐาน ___ / incident และวิธีแยกสาเหตุ ___ / trade-off ของ change ___ / สิ่งที่จะปรับก่อน production ___

**Runbook สั้นสำหรับผู้รับช่วง:** mainURL ___ / active revision+DBlogin+secretversions (ไม่มี payload) ___ / health และ logquery ___ / ผู้ดูแล secret/billing ___ / revisionfallback ที่ credential ยัง valid ___ / เวลาหรือเงื่อนไข cleanup ___

ก่อนแชร์ลบ/redactpassword, cookie, CSRF, Authorization, principal ส่วนตัวและข้อมูลที่นโยบายห้ามเผย ควรเก็บ requestIDs/status/versions ที่ใช้พิสูจน์ ไม่ส่ง rawsecretbundle เป็นหลักฐาน

ข้อจำกัด production ที่ต้องอธิบาย: demoidentity ไม่ใช่ SSO, ยังไม่มี loginrate-limit/abuseprotection, SQLsingle-zone, sampleload จำกัด, ไม่มี destructivemigration ในการ rollback, ไม่อ้าง zero-downtime/HA/SLA หรือ peakcapacity จากผลชุดนี้

### Task 12 — Cleanup และวิธีสร้างกลับ

**คำเตือน:** ขั้นนี้ลบบริการ ข้อมูลจอง Secret versions และ images ที่ Terraform เป็นเจ้าของ ข้อมูลที่ลบอาจกู้ไม่ได้ อย่ารันใน Project ที่แชร์กับงานจริง ก่อนทำเก็บเฉพาะหลักฐานที่ redact แล้ว หากต้องเก็บข้อมูลจริงให้ทำ export/backup ที่อนุมัติก่อน ไม่ถือว่าไฟล์ evidence เป็น DBbackup

**ทำที่ไหน:** Cloud Shell, checkout/state เดิมจาก T01

ตรวจ target ก่อนลบ:

```bash
gcloud config get-value project
gcloud run services list --region="$REGION"
gcloud run jobs list --region="$REGION"
terraform -chdir=infra state list
gcloud sql instances describe lab004-sql --format='yaml(name,region,settings.userLabels)'
```

ถ้า Job ใดไม่เคยสร้าง ให้ตรวจว่า NOT_FOUND จริงและบันทึก ไม่ต้องสร้างขึ้นมาเพียงเพื่อลบ เมื่อยืนยัน Project/region/names ตรง Lab นี้ ให้ลบเฉพาะบริการและ Jobs ที่สร้างในคู่มือนี้ อ่าน prompt ก่อนยืนยัน ไม่ใช้--quiet เพื่อข้ามการตรวจ:

```bash
gcloud run services delete lab004-booking --region="$REGION"
gcloud run jobs delete lab004-bootstrap --region="$REGION"
gcloud run jobs delete lab004-inspect --region="$REGION"
gcloud run jobs delete lab004-access-check --region="$REGION"
terraform -chdir=infra plan -var="project_id=$PROJECT_ID" -var='allow_destroy=true' -out=unlock.tfplan
terraform -chdir=infra show -no-color unlock.tfplan
terraform -chdir=infra apply unlock.tfplan
terraform -chdir=infra plan -destroy -var="project_id=$PROJECT_ID" -var='allow_destroy=true' -out=cleanup.tfplan
terraform -chdir=infra show -no-color cleanup.tfplan
terraform -chdir=infra apply cleanup.tfplan
```

Planunlock ควรเปลี่ยน deletionprotection เท่านั้น/ตรง desiredstate ที่ตรวจไว้ หากมีการสร้างของใหม่หรือเปลี่ยนระบบอื่นให้หยุดก่อน Apply Plan-destroy ต้องมีเฉพาะ FoundationLab นี้ การลบ SQL ลบข้อมูลด้วย ไม่เปิด allow_destroy ไว้ระหว่างฝึกปกติ

หาก destroy ติด dependency หลังลบ Run/SQL ให้ตรวจ operations และ resource ที่ยังอ้าง VPC/PSA รอการปล่อย resource แล้ว plan ใหม่จาก state เดิม ไม่ force-deletepeering ของระบบอื่น ไม่ลบ state เพื่อซ่อน error APIs ตั้ง disable_on_destroy=false จึงยังเปิดอยู่โดยตั้งใจ การลบ Project ทั้งก้อนไม่ใช่ขั้นตอนของ Lab นี้

ตรวจ Console **Cloud Run / Cloud SQL / Secret Manager / Artifact Registry / VPC networks / VPC network peering** และ inventory ต่อไปนี้:

| Resource | หลัง Cleanup ต้องเป็น | Actual / pending owner |
|---|---|---|
| lab004-booking + revisions/tags | ไม่มี service ที่เรียกใช้งานได้ | ___ |
| bootstrap/inspect/access-check Jobs | ไม่มี Job ของ Lab | ___ |
| lab004-sql + bookingDB | instance ถูกลบ ไม่ใช่หยุดชั่วคราว | ___ |
| Secret lab004-auth/db-a/db-b/bootstrap-admin | ลบ containers/versions ที่สร้าง | ___ |
| Artifact Registry lab004-images | repo/images ถูกลบ | ___ |
| lab004-runtime/bootstrap SA + IAMmembers | ถูกลบตาม state | ___ |
| VPC/subnet/PSArange/peering | ไม่เหลือ dependency ของ Lab | ___ |
| retained/final backups หรือ exports ที่ทำเพิ่มเอง | ตรวจเจ้าของ/retention/ค่าใช้จ่ายแยก | ___ |

ดู BillingReports ภายหลังเพราะยอดอาจมาช้า ไม่อ้างว่าเสียค่าใช้จ่ายศูนย์ทันทีที่ destroyexit0 หากมี resourcepending ให้บันทึกชื่อ/error/เวลาตรวจซ้ำและผู้รับผิดชอบ **ยังไม่ปิด cleanup ว่าเสร็จ**

เมื่อไม่ต้องใช้ secretbundle แล้ว ให้ลบเฉพาะ directorysecrets ของ Lab ผ่าน CloudShellEditor หลังตรวจ path ไม่ลบทั้ง checkout/home และไม่เผยแพร่ไฟล์ลับพร้อม evidence การลบไฟล์ใน CloudShell ไม่ได้รับประกัน cryptographicerase; secret ที่เคยรั่วต้องถูก revoke/rotate ฝั่งบริการด้วย

**Rebuild:** ใช้ sourcecommit และ image/sourceversion ที่บันทึกไว้ใน checkout ใหม่ กลับ Task0 ตรวจ Sandbox ใหม่ → Task1init/plan/apply ด้วย allow_destroy=false → Task2 สร้าง secretbundle ใหม่ (ไม่คืน credential ที่ถอนแล้ว) → build/bootstrap/deploy/journey ตามลำดับ ข้อมูล seed ใหม่ไม่ใช่การ restorebookings เดิม หากต้องการข้อมูลเดิมต้องใช้แผน restore ที่ทดสอบแยก หากชื่อ SQL เดิมยังใช้ไม่ได้หลังลบ ให้รอเงื่อนไขของบริการหรือวางชื่อ instance ใหม่ให้สอดคล้องทุก config ก่อนเริ่ม ไม่แก้แค่ปลายทาง App

**บันทึก T12:** Project/targets ที่ยืนยัน ___ / destroyresult ___ / inventoryremaining ___ / backupretention ___ / billingfollow-up ___ / secretsremoved ___ / rebuildcommit และ entrypoint ___

## ไฟล์ประกอบและขอบเขตการตรวจ

ไฟล์ประกอบ: [App](app/main.py), [DB pool/connector](app/database.py), [UI](app/templates/index.html), [schema](db/schema.sql), [seed](db/seed.sql), [grants](db/grants.sql), [invariants](db/check-invariants.sql), [secret generator](scripts/create-secrets.py), [bootstrap](scripts/init-db.py), [tests](tests/test_booking.py), [Deploy helper](scripts/deploy-service.py), [HTTP probe](scripts/probe.py), [DB inspect](scripts/inspect-db.py), [Secret boundary check](scripts/check-secret-boundary.py), [Terraform](infra/main.tf)

App pool4/max_overflow0, pool wait3s, statement5s, lock3s ใช้ Gunicorn1worker/16threads ทำให้จำนวน pool ต่อ instance ชัด ไม่เพิ่ม workers โดยไม่คูณ connection budget Runtime DB logins booking_a/booking_b ไม่มี superuser/DDL/delete-ledger ส่วน admin bootstrap เป็น job แยก ไม่ใช้ credential เดียวกับ App

## แหล่งอ้างอิงขอบเขต

- [Cloud Run Direct VPC egress](https://docs.cloud.google.com/run/docs/configuring/vpc-direct-vpc)
- [Cloud SQL private services access](https://docs.cloud.google.com/sql/docs/postgres/configure-private-services-access)
- [Cloud Run Secret Manager integration](https://docs.cloud.google.com/run/docs/configuring/services/secrets)
