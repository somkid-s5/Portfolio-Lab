# GCP Labs — Progress

สถานะ Guide กับผล Cloud แยกกัน ไม่ใช้ PASS จากการตรวจเอกสารแทนการทดสอบจริง

| Lab | Solution | Guide status | Cloud verification | PR / checkpoint |
|---|---|---|---|---|
| 01 | [เว็บหลาย Zone หลัง Load Balancer](LAB-001-multi-zone-web/README.md) | Guide-ready | Not run | [PR #1](https://github.com/somkid-s5/Portfolio-Lab/pull/1) |
| 02 | [ระบบ Inventory ภายในองค์กรแบบ Private](LAB-002-private-inventory/README.md) | Guide-ready | Not run | [PR #1](https://github.com/somkid-s5/Portfolio-Lab/pull/1) |
| 03 | [เว็บไซต์เอกสารสาธารณะผ่าน CDN และ HTTPS](LAB-003-public-docs-cdn/README.md) | Guide-ready | Not run | [PR #1](https://github.com/somkid-s5/Portfolio-Lab/pull/1) |
| 04 | [ระบบจองบริการบน Serverless และ Private Database](LAB-004-serverless-booking/README.md) | Guide-ready | Not run | [PR #1](https://github.com/somkid-s5/Portfolio-Lab/pull/1) |
| 05 | [ระบบสั่งซื้อสามชั้นบน VM](LAB-005-three-tier-orders/README.md) | Guide-ready | Not run | [PR #1](https://github.com/somkid-s5/Portfolio-Lab/pull/1) |
| 06 | [ระบบรับไฟล์ยอดขายและสร้างรายงานส่วนตัว](LAB-006-private-file-processing/README.md) | Guide-ready | Not run | [PR #1](https://github.com/somkid-s5/Portfolio-Lab/pull/1) |
| 07 | [ระบบรับคำสั่งซื้อและประมวลผลงานผ่าน Queue](LAB-007-queued-order-processing/README.md) | Authoring | Not run | [PR #1](https://github.com/somkid-s5/Portfolio-Lab/pull/1) |
| 08 | ระบบรายงานตามเวลาและงาน Batch รายวัน | Planned | Not run | — |
| 09 | ระบบส่ง Webhook ให้ระบบคู่ค้า | Planned | Not run | — |
| 10 | ระบบ Catalog ที่ใช้ Cache ลดภาระ Database | Planned | Not run | — |
| 11 | ระบบบริการบน GKE ที่ Deploy และขยายได้ | Planned | Not run | — |
| 12 | ระบบ Microservices ที่ติดตามปัญหาข้ามบริการได้ | Planned | Not run | — |
| 13 | ระบบประมวลผลข้อมูลนำเข้าแบบขนาน | Planned | Not run | — |
| 14 | แพลตฟอร์มส่งมอบ App สำหรับทีมพัฒนา | Planned | Not run | — |
| 15 | ระบบสำนักงานสาขาเชื่อมบริการ Private บน Cloud | Planned | Not run | — |
| 16 | ย้ายระบบ Legacy พร้อมข้อมูลขึ้น Cloud | Planned | Not run | — |
| 17 | ระบบจัดเก็บข้อมูลพร้อมแผนกู้คืนที่ทดสอบได้ | Planned | Not run | — |
| 18 | แพลตฟอร์มสร้าง Environment ให้ทีมใหม่ | Planned | Not run | — |
| 19 | ระบบเฝ้าระวังและรับ Incident สำหรับทีมบริการ | Planned | Not run | — |
| 20 | แพลตฟอร์มจองและสร้างรายงานแบบรับมอบงานได้ | Planned | Not run | — |

Guide status: Planned → Brief → Design → Authoring → Review → Guide-ready

Cloud verification: Not run → In progress → Verified / Failed / Blocked (ต้องมีหลักฐานจริง)

## Current checkpoint

M1 / Lab 01: Guide-ready — คู่มือครบ Tasks 0–10/8B, normal/fault/recovery/load/access/change/backout/cleanup/rebuild, code และภาพก่อน/หลังเปลี่ยน อ่านกลับจาก GitHub แล้ว

[CI run 39809864366](https://github.com/somkid-s5/Portfolio-Lab/actions/runs/39809864366) ของ commit `3a5f312c21355f9254f1deee776ca26c4d4dbcf4`: shell syntax, Python compile, 10 tests และ render SVG สองแบบผ่าน ตรวจภาพ baseline/after-change ที่ 960px แล้ว PNG ถูกบันทึกใน assets พร้อม SVG editable และเครดิตไอคอน

ขอบเขต: ไม่ได้สร้าง GCP resources, ไม่ได้ทดสอบ IAP/firewall/LB health จริง หรือ apt/systemd ใน GCE ผล cloud ทุก Lab ยัง Not run ไม่ใช้ CI เป็นหลักฐาน Cloud-verified

M2 / Lab 02: Design และ Build materials — บันทึก access matrix, app contract, PostgreSQL schema/seed/invariants และ real-DB integration tests แล้ว กำลังตรวจ cloud CI ก่อนเขียน Tasks คู่มือเต็ม

Lab 02 materials checkpoint: [CI 39810811347 / job lab002](https://github.com/somkid-s5/Portfolio-Lab/actions/runs/39810811347) รัน App สอง process กับ PostgreSQL 15 จริงและผ่าน 7 integration tests: shared data, auth/validation, retry/conflict, concurrent overdraw, concurrent duplicate key, non-destructive seed และ health/search ใช้ฐานข้อมูล CI ชั่วคราว ไม่ใช่ผล Deploy GCP; secret-generator/installer tests เพิ่มเติมยังอยู่ระหว่างตรวจ

Lab 02: [CI 39811584409](https://github.com/somkid-s5/Portfolio-Lab/actions/runs/39811584409) ผ่าน runtime-role และ learner probe tests กับ PostgreSQL 15 รวม 10 tests (Inventory 9 + secrets 1), App สอง process ใช้ inventory_app ที่ไม่มี superuser/DDL/delete-ledger และตรวจ no-overwrite/no-token-leak ของ probe แล้ว README มี Tasks 0–5; ยังต้องเติม LB/DNS/tests/ops/change/cleanup/diagram ก่อน Review

Lab 02 / Review: README ครบ Tasks 0–12 พร้อม App/schema/least-privilege grants/secrets/probe และ Diagram สองมุมมอง [CI 39813178436 job lab002](https://github.com/somkid-s5/Portfolio-Lab/actions/runs/39813178436) ผ่าน 15 tests, installer shell syntax และ SVG render ภาพตรวจที่ 960px แล้ว พบ DNS association line เบียด label จึงขยับและรอภาพใหม่ก่อนปิด Review; ยังไม่มี GCP provisioning หรือผลจริง T00–T12

Lab 02: Guide-ready หลัง [CI 39813493443](https://github.com/somkid-s5/Portfolio-Lab/actions/runs/39813493443) / commit 11c260e ผ่าน 15 tests และ render สองภาพ ตรวจภาพรอบแก้แล้ว เก็บ PNG/SVG พร้อม attribution คู่มือครบทั้ง build/test/operate/change/evidence/cleanup/rebuild ขั้นถัดไป Lab 03 Brief ก่อน Tasks ทุก Lab ยัง Cloud Not run

Lab 03 / Design + Materials: เลือก EXTERNAL_MANAGED backend bucket ตามคู่มือ official global setup มี v1/v2/bad release fixtures, deterministic builder, SHA256 manifests, dry-run publisher (assets/archive generation0 ก่อน root generation fence), rollback remote integrity checks และ bounded HTTP probe; กำลังตรวจ CI ยังไม่ใช่ Guide-ready และไม่มี cloud writes

Lab 03 / Authoring: README ครบ Tasks 0–11 (DNS/TLS/CDN/content tests/v2 publish/bad-release rollback/HTML TTL15 change/public-read boundary/cleanup), มี URL map renderer และ code tests เพิ่มเติม ยังรอ CI jobs ที่อยู่ queued ตาม handle จริง ไม่ rerun ซ้ำเพียงเพราะรอ และยังเหลือ Diagram/Review ก่อน Guide-ready

Lab 03 / Review: คู่มือ Tasks 0–11, release materials และ SVG delivery/release-flow พร้อม attribution อยู่บน branch แล้ว ยังต้องยืนยัน tests และดู rendered previews จาก CI ก่อน Guide-ready; CI รอบ 39815687613 ยืนยันว่า queued ณ ตอนตรวจ ไม่ได้ terminal จึงไม่ถือว่ารันทดสอบล้มเหลวหรือผ่าน และไม่เริ่ม Lab 04 ก่อนปิด Lab 03

Lab 03 review refinement: เพิ่ม --reuse-assets สำหรับ partial publish โดย verify remote CSS ก่อน archive/root uploads มี tests ตรวจหยุดเมื่อ hash ไม่ตรง GitHub run 39816163024 ยังคง Queued ตามทั้ง API และหน้าเว็บ; GitHub Status วันที่ 22 ต.ค. 2026 รายงาน Actions degraded (https://www.githubstatus.com/) เป็นข้อมูลประกอบ ไม่ใช่หลักฐานว่า test ผ่าน หลีกเลี่ยง local fallback เพราะ runtime ที่ตรวจพบเป็น win32 บน laptop

Lab 03: Guide-ready — [CI 39816792474](https://github.com/somkid-s5/Portfolio-Lab/actions/runs/39816792474) source ae9335c ผ่าน 18 tests, render สองภาพ และตรวจจาก cloud log PNG ที่ 960px แล้ว เก็บ PNG/SVG/attribution บน GitHubครบ ไม่เรียก cloud provisioning/DNS จริง เริ่ม Lab 04 Brief ถัดไป

Lab 04 / Design + Materials: เพิ่ม Booking UI/API พร้อม CSRF/signed secure session/role/ownership, capacity + idempotency + cancel ledger, PostgreSQL16 schema/seed/grants, Cloud SQL connector private-IP pool4, secret generator/bootstrap และ Dockerfile CIกำลังตรวจ ยังไม่ใช่Guide-readyและไม่มี GCP provisioning

Lab 04 materials checkpoint: [CI 39818762521 / lab004](https://github.com/somkid-s5/Portfolio-Lab/actions/runs/39818762521) source dfd14c5 — Booking tests กับ PostgreSQL16, browser JS syntax และ Docker image build ผ่าน ตรวจรายละเอียด logs แล้ว ยังไม่รวม Cloud Run/SQL/IAM networking จริง และยังต้องทำ deployment materials/Guide/Diagram ก่อน Guide-ready

Lab 04 foundation checkpoint: เพิ่ม Terraform สำหรับ VPC/Direct VPC subnet/PSA, PostgreSQL16 Enterprise private-only, Artifact Registry, runtime/bootstrap identities และ secret containers แบบไม่ใส่ค่าลับใน Terraform state; เพิ่ม bootstrap-admin JSON และตรวจ no-overwrite ทั้ง bundle กำลังตรวจ cloud CI ด้วย init/validate เท่านั้น ยังไม่มี GCP plan/apply หรือผล Cloud-verified

Lab 04 / Authoring: [CI 39820536459 / lab004](https://github.com/somkid-s5/Portfolio-Lab/actions/runs/39820536459) source ae64609 ผ่าน PostgreSQL16 tests/Docker build/Terraform init+validate ตรวจ logs แล้ว เพิ่ม dry-run deploy helper (digest + numeric secret versions + explicit runtime/network/limits), IAM API prerequisites และ README Tasks0–5 ถึง Browser journey; ยังต้องเติม tests/ops/rotation/change/cleanup/Diagram ก่อน Review ไม่มี GCP provisioning

Lab 04 / Business + Operations authoring: เพิ่ม HTTP journey/3-user capacity race/bounded read-load probe พร้อม real-HTTP integration test และ inspect-db snapshot/invariant checks/retire-A guard มีคู่มือ Tasks6–8 สำหรับ business negative tests, DB review, revision promotion/rollback และ A→B credential rotation รอ CI ตรวจ codeชุดนี้ ยังเหลือ fault/change/cleanup/Diagram และไม่มีผล GCP จริง

Lab 04 / Full guide draft: README ครบ Tasks0–12 รวม runtime→admin secret denial check, no-traffic dependency fault/recovery, bounded concurrency8→16 experiment, evidence/case-study และ cleanup/rebuild เพิ่มการแยก login ออกจาก read-load และจำกัดworkers16/requests200; [CI 39822476778](https://github.com/somkid-s5/Portfolio-Lab/actions/runs/39822476778) ผ่านชุดก่อนหน้าที่แก้ connector API failure เป็น sanitized503 แล้ว รอ CI ชุดใหม่/Diagram/Review ก่อน Guide-ready ไม่มี GCP writes

Lab 04: Guide-ready — [publication CI 39824671111](https://github.com/somkid-s5/Portfolio-Lab/actions/runs/39824671111) source395043b ผ่าน20 tests, README29 Bash blocks/relative links, browser JS, Docker image build, Terraform init/validate และ2SVG renders ตรวจภาพ960pxและอ่านกลับSVG/README/attributionจากGitHubแล้ว คู่มือTasks0–12ครอบคลุมR1–R8พร้อมcode/probes/evidence/cleanup/rebuild; GCP networking/IAM/SecretAPI/Run/SQLHAไม่ได้รันจริง (Lab04SQLเป็นZONAL) ทุกLabยังCloud Not run เริ่มBrief Lab05ถัดไป

Lab 05 / Brief: กำหนดOrder UI/Web/API/SQLHA solution, R1–R8, private two-zone MIGs, globalHTTPSedge + internal passthroughL4, transactional stock/idempotency ledger, rollout/failover/change scenarios และcost/domain/access prerequisitesแล้ว ยังต้องทำDesignก่อนMaterials/Tasks ไม่มีGCP provisioning

Lab 05 / Design + transaction materials: ระบุresource/ports/SA firewall matrix, PSA/connector3307, two-zone rollout surge2, health/failoverและconnectionbudgetแล้ว เพิ่มOrder domain/schema/seed/grants/invariants พร้อม9testsกับPostgreSQL16และ2independent pools; รอcloud CI ยังต้องต่อHTTP/UI/installer/IaC/Guide/Diagram ไม่ใช่Guide-readyหรือCloud-verified

Lab 05 / API materials verification: [CI 39828395846](https://github.com/somkid-s5/Portfolio-Lab/actions/runs/39828395846) sourceff7aac7 ผ่าน15testsกับPostgreSQL16 รวมHTTPsession/CSRF/owner/role/reconnect, Nginxconfig และJSsyntaxแล้ว เพิ่มจริง browser→Nginx→API→DB CI testสำหรับlost-responseหลังcommit/reload/same-key retry และUIpreview กำลังตรวจรอบใหม่ ยังไม่ใช่ผลGCP/SQLHAหรือGuide-ready

Lab 05 / Browser verified materials: [CI 39829020509](https://github.com/somkid-s5/Portfolio-Lab/actions/runs/39829020509) sourcefe433a6 ผ่าน16tests รวมChromeจริง→Nginx→API→PostgreSQL, lost-responseหลังcommit/reload/keyเดิม/orderเดียว และcancelคืนstock ตรวจUIpreviewแล้ว เป็นCIไม่ใช่GCP เพิ่มprivate secret generator/atomic bootstrap/error sanitization และแยกbootstrap fixtureก่อนApp tests กำลังตรวจรอบใหม่ ยังเหลือinstaller/artifact/IaC/Guide/Diagram

Lab 05 / Bootstrap checkpoint: [CI 39830356415](https://github.com/somkid-s5/Portfolio-Lab/actions/runs/39830356415) source146bb2e ผ่าน18tests + separate real bootstrap check (failed schema rolls back role, complete seed/grants/login, rerun refuses password reset) ตรวจและเก็บfull-page UI screenshot/provenanceจากChromeบนGitHubแล้ว ไม่ใช่GCP verification; เพิ่มLab04bootstrap error guard/testเพื่อไม่พิมพ์SQLที่อาจมีpassword กำลังตรวจรอบใหม่ ไม่มีGCP writes

Lab 05 / Release materials: เพิ่มpinned Git commit allowlist builder แยกWeb/API USTAR+gzip, manifest/SHA256/content-addressed object names และbounded verifier/unpackerที่ตรวจทุกmemberก่อนเขียนdestinationใหม่ มีtestsสำหรับdirty worktree/tracked secret exclusion, reproducibility, existing target, hash mismatch, path traversal, links, duplicate members และsize bounds กำลังตรวจCI ยังเหลือVM installer/artifact upload/IaC/Guide/Diagram ไม่มีGCP writes

Lab 05 / Verified release + installer draft: [CI 39832514972](https://github.com/somkid-s5/Portfolio-Lab/actions/runs/39832514972) source715b504 ผ่าน25testsและseparate bootstrap check แล้ว เพิ่มVM installerที่ตรวจattached identity/numeric secret versions/hash ก่อนติดตั้ง แยกWebที่ไม่อ่านSecret, APIกับbootstrap, private config files และmanaged service พร้อมcontract tests; ชุดinstallerยังรอCI และยังไม่ได้ทดสอบapt/systemd/metadata/IAMบนGCE ต้องทำstartup wiring/artifact upload/IaC/Guide/Diagramต่อก่อนGuide-ready

Lab 05 / Startup wiring draft: เพิ่มDebian startup scriptที่อ่านเฉพาะdeployment-controlled metadata bundle (release.py + vm-install.py), จำกัดขนาด/ตรวจsyntax/ปฏิเสธredirect และเขียนในprivate ephemeral directoryก่อนเรียกinstallerแบบbounded timeout พร้อมtestsที่ไม่เรียกmetadataหรือรันroot installerจริง CIชุดก่อน39835259739ยังin_progressตอนตรวจ; tests startupชุดใหม่ยังไม่ยืนยันผล ต้องต่อTerraform metadata binding/artifact publisherและfull installer sandbox testsก่อนGuide-ready

Lab 05 / Release upload planner: เพิ่มpublish-release.pyที่ตรวจstrict manifest/ทั้งสองarchive/identity/size/hash/pathก่อนพิมพ์คำสั่งcreate-only gcloud storage cp --if-generation-match=0 พร้อมtestsสำหรับtamper/path/bucket/symlink ไม่มีnetwork callหรือuploadจริง; อ้างอิง https://docs.cloud.google.com/storage/docs/request-preconditions และ https://docs.cloud.google.com/sdk/gcloud/reference/storage/cp ชุดCI39835517249ยังpendingตอนตรวจ ยังเหลือIaC/full installer execution sandbox/Guide/Diagram และไม่ใช่Guide-ready

Lab 05 / Installer sandbox coverage: เพิ่ม4testsที่เรียกinstallจริงกับarchiveจากไฟล์Appจริงและfilesystemชั่วคราว แต่fake metadata/Secret/apt/venv/systemctl/liveness ตรวจWebไม่มีSecretและrerunไม่สร้างpycache, APIรับเฉพาะruntime/authและmode640/600, initรับadmin+runtimeโดยไม่สร้างdaemon, corrupted bundleหยุดก่อนเขียน/ติดตั้ง ชุดใหม่ยังรอCI ไม่ใช่GCE installation verification; Terraform/Guide/Diagramยังไม่ครบ

Lab 05 / Installer+startup+publisher CI: [CI39835965438](https://github.com/somkid-s5/Portfolio-Lab/actions/runs/39835965438) sourceca6ab04 joblab005สำเร็จ รวมrealDB/bootstrap/browserและinstaller filesystem sandbox (metadata/apt/systemctlเป็นfake) เพิ่มTerraform foundationสำหรับVPC2subnets/NAT/PSA/privateSQL16EnterpriseREGIONAL2zones/SA4ตัว/scopedSecrets/privateartifactbucket/firewallmatrix พร้อมCIinit+validateไม่มีcredentials ชุดTerraformยังรอผล ไม่ได้plan/applyหรือสร้างGCP; ยังต้องทำworkloads/bootstrapVM/LBs/Guide/Diagram

Lab 05 / Workloads Terraform draft: เพิ่มrootแยกสำหรับprivate Web/API templates+regionalMIGsสองzones, pinnedDebianimage/releasehash/numericSecrets, bootstrapmetadata wiring, process-onlyhealth/autoheal, surge2/unavailable0, internalpassthroughTCP8080และglobalEXTERNAL_MANAGEDHTTPS พร้อมCIinit/validateไม่มีcredentials FoundationCI39836392565ยังin_progressตอนตรวจ ยังต้องเพิ่มone-time bootstrapVM/diagnostic,ตรวจprovider schemaและguide/evidence/Diagram ไม่มีplan/applyหรือGCP provisioning

Lab 05 / Bootstrap and diagnostic Terraform: เพิ่มone-time privateinitializer rootใช้bootstrapSA/numericadmin+DBversions/verifiedAPIarchive และdiagnostic VMแบบopt-inใช้SAไม่มีSecret/SQL grants แยกlab005-infra CIตรวจ3rootsโดยไม่รอApppackages ไม่มีplan/apply; CI39836686676ยังin_progressตอนตรวจ ชุดIaCใหม่ยังรอvalidateและยังต้องทำGuide/ops probes/Diagramก่อนGuide-ready

Lab 05 / IaC schema repair + bounded evidence probe: CI39836942611 lab005-infraยืนยันfoundation/bootstrapvalidateผ่าน แต่workloadsล้มเพราะmin_ready_secไม่มีในgoogle6.50 ย้ายเฉพาะregionalMIGไปgoogle-beta6.50เพื่อคงready30sไม่ลดrequirement เพิ่มread-onlyHTTPprobeจำกัดrequests200/workers8/interval>=0.1s/timeout5s/body64KiB ไม่followredirect/ไม่logcookieCSRFbody พร้อมreal-loopbackHTTPtests ชุดแก้รอCI ยังไม่ใช่Cloud-verified และGuide/Diagramยังไม่ครบ

Lab 05 / Guide authoring Tasks0–2: เพิ่มขั้นCloudShell persistentcheckout/state/budget/domain/IAM, foundationplanreview/apply/Consolechecks และverifiedreleasebuild/uploadplanning พร้อมExpected/diagnosis/inlineevidence ไม่บันทึกผลGCPจริง ยังต้องเติมTasksSecret/bootstrap/workloads/business/operations/change/cleanup/DiagramและตรวจCIของbetaMIG/probeก่อนGuide-ready

Lab 05 / Guide Tasks3–4: เพิ่มprivateSecretbundle+flagsfileสำหรับSQLadminpasswordไม่อยู่argv, numericSecretversionupload/IAMreview, pinnedOSimage/APIhash, initializerplan/startuplog/diagnosis/evidenceและลบเฉพาะinitializerroot เพิ่มtestตรวจflagsตรงadminpassword CI39837712789 lab005-infraยืนยันทั้ง3rootsvalidateผ่านหลังใช้google-betaMIG; App/probeชุดก่อนยังin_progressตอนตรวจ ชุดguide/generatorใหม่นี้รอCI ไม่มีGCPprovisioning ยังต้องworkloads/journey/ops/change/cleanup/Diagram

Lab 05 / Guide Tasks5–6 + verified CI: [CI39838026127](https://github.com/somkid-s5/Portfolio-Lab/actions/runs/39838026127) sourcea20d1cbทุกjobผ่าน รวม43App/materialtestsและ3Terraformrootsvalidate เพิ่มworkloadplanreview/SA+IP+MIGhealthchecks/DNS+TLSdiagnosis/HTTPSprobe และBrowserjourney+owner/operator/anonymousnegativeพร้อมrecordtable คู่มือยังไม่ครบbusinessrace/reconciliation/ops/change/cleanup/Diagram ไม่มีGCPprovisioningหรือCloudPASS

Lab 05 / Read-only reconciliation materials: เพิ่มinspect-db.pyใช้REPEATABLE READ/READ ONLY snapshot ตรวจstock/order totals/itemledgerพร้อมaggregatecountsและroleconnections ไม่แสดงowner/idempotency/password เพิ่มไว้ในAPIreleaseallowlistและrealPostgreSQLtestที่ตรวจbaseline→intentionalstockmismatch→restore ชุดใหม่รอCI; CI39919383183ของguideชุดก่อนสำเร็จ ไม่ใช่GCPverification ยังต้องbusinessHTTPtests/ops/change/cleanup/Diagram

Lab 05 / Durable HTTP journey + Task7A: CI39925476057ของread-onlyinspectorชุดก่อนผ่าน เพิ่มjourney.pyที่บันทึกfixedcart/idempotencykeymode600ก่อนwritesและresumejournalเดิม ตรวจreplay/conflict/CSRF/owner/role/cancelreplay จำกัด20calls/clientและtimeout5sไม่logsecrets พร้อมrealHTTP→Flask→PGtestรันjourney2รอบแล้วตรวจorderเดียว/stockคืน/ledgercancelครั้งเดียว คู่มือเชื่อมruntimeUIDsystemd-runinspectorกับsnapshot/evidence ชุดใหม่นี้รอCI ยังเหลือconcurrentHTTP/race/ops/change/cleanup/Diagram ไม่มีGCPwrites

Lab 05 / Concurrent HTTP stock race draft: เพิ่มstock-race.py6sessions/6persistedkeys/USB1ต่อorder, barrier/timeout/requestboundsและterminalresultcacheที่ไม่ส่งrejectedkeysซ้ำหลังคืนstock พร้อมrealHTTP→PGtestคาด4confirmed/2conflictและresumeก่อนcancelไม่เพิ่มorder คู่มือTask7Bเชื่อมstock/ledger/evidenceและcancelเฉพาะUUIDทดลอง CI39925990557ยังin_progressขั้นaptตอนตรวจ จึงยังไม่อ้างผลใหม่; ปรับCIcancel-in-progress=falseให้jobที่รันอยู่จบได้ระหว่างcheckpointใหม่ ไม่มีGCPwrites ยังเหลือaccess/ops/change/cleanup/Diagram

Lab 05 / Access boundary materials + Task8: เพิ่มattachedidentity+cloud-platformscope+numericversionSecretdenialchecker ไม่readsuccessfulpayload/ไม่logtokenและไม่ถือ404/scope/networkerrorเป็นPASS พร้อมmocktransporttests คู่มือWebpositiveVIP/Secretnegative/APIadminnegative/diagnosticSAnegative+effectivepolicycontrol/cleanup diagnostic ยังรอCIสำหรับชุดใหม่ run39926421936pendingตอนตรวจ ไม่มีGCPwrites ยังเหลือfault/rollout/failover/change/cleanup/Diagram

Lab 05 / Fault and recovery guide Tasks9/9B/10: เพิ่มAPI/Websingle-servicefaultทีละเครื่อง, boundedprobewindows/ID+health+repairtimeline/manualbackout และplannedSQLHAfailoveroperation+same-journalresume+DBreconciliation แยกpublicWeb/livezจากAPIlocalhost/livezไม่อ้างzoneoutage/zeroDT/productionRTO ยังไม่รันGCPจริง CI39926421936ของraceชุดก่อนยังin_progressตอนตรวจ; accessชุด39926805461pending ยังเหลือrollout/change/cleanup/Diagram/review

Lab 05 / Rollout+capacity guide Tasks11–12: เพิ่มAPI-onlystartupfaultflagdefaultfalseและinstallerrefusalก่อนartifact/Secretพร้อมsandboxtest คู่มือcompatiblev2/oldhashbackout/badtemplateboundedobservation/falseflagrecovery และcapacity2→4→2พร้อมpool/surgebudget/boundedbeforeafter/evidence ชุดใหม่รอCI ไม่ได้GCPprovisioning; run39925990557journeyชุดก่อนสำเร็จ ส่วนrace/accessยังรอผลตามhandle เหลือcleanup/casestudy/Diagram/fullreview

Lab 05 / Full guide draft Tasks13–14: เพิ่มR1–R8evidencematrix/casestudy, reviewedrootdestroyorder/DNSก่อนreleaseIP/privateartifactgenerationcleanup/SQLprotectiongate/cloudinventory/retainedbackup-softdelete-costchecks และrebuildไม่อ้างrestore เพิ่มbucketversioningให้ตรงDesignพร้อมforce_destroy=false ชุดใหม่นี้รอCI; คู่มือTasks0–14ยังต้องDiagram/fullreviewก่อนGuide-ready ไม่มีGCPwrites

Lab 05 / Diagram generation checkpoint: เพิ่มofficiallegacyicon SVG generatorสำหรับtopologyและrelease/recovery แยกglobaledge/regionalVPCsubnets/producerSQLHA พร้อมWeb/APIverticalfan-outและCIrender960px/recordiconhashes ชุดก่อนCI39928132010สำเร็จ; SVG/PNGชุดใหม่ยังต้องตรวจrenderและcommitassets/provenanceก่อนGuide-ready ไม่มีGCPwrites

Lab 05 / Diagram visual review round1: CI39928693783สร้างofficialcompute/LB/SQLiconsจากarchiveจริงและrender2ภาพ960pxแล้ว ตรวจภาพพบoperationnoteยาวเกินกรอบและTLSlabelชิดproducerboundary จึงย่อnote/ย้ายlabelและรอrenderซ้ำก่อนcommitPNG/SVG ยังไม่Guide-ready ไม่มีGCPprovisioning


Lab 05 / Reviewed diagram assets: บันทึก SVG/PNG ทั้ง topology และ release/recovery พร้อม official icon provenance และฝังใน README แล้ว ตรวจภาพที่ความกว้าง 960px หลังแก้ข้อความล้นและตำแหน่ง TLS label; CI run 39928910636 ผ่านครบทั้ง 7 jobs รวม Orders 49 tests, browser check และ Terraform validation สาม roots แก้ข้อความสถานะเก่าในคู่มือให้ตรงกับ Tasks 0–14 ที่มีแล้ว ยัง Authoring ระหว่าง full-guide review; Cloud verification Not run ไม่มี GCP provisioning


Lab 05 / Network guide review: เติม Task8 Web→SQL ด้วยคำสั่งเลือก PRIVATE address/ตรวจ PSA range, อ่าน egress deny rule, ทดสอบ TCP3307 จาก Web และเทียบ /healthz ของ API พร้อม effective-policy evidence เพิ่ม lightweight guide-only CI job ให้ตรวจ Bash/link/sections โดยไม่ต้องรอ apt/browser; run39929963331 ยัง lab005 in_progress ตอนตรวจ ไม่อ้างผลชุดใหม่ผ่าน และไม่มี GCP provisioning


Lab 05 / Guide static review: เพิ่ม CI tests สำหรับ Bash ทั้ง 45 blocks (parse เท่านั้น ไม่ execute), relative links และ Task/acceptance sections เพื่อป้องกันคำสั่งผิด syntax หรือไฟล์ประกอบหายหลังแก้คู่มือ รอผล GitHub Actions รอบนี้ก่อนยืนยันผล ยังต้องตรวจเนื้อหา workflow ด้วยคน; ไม่มี GCP writes และยังไม่เปลี่ยนเป็น Guide-ready



Lab 05 / Operational guide review: เพิ่มคำสั่ง probe จริงสำหรับ Web fault และ capacity before/after พร้อม private output/noclobber/exit-code/summary/incomplete-window interpretation และจุดเทียบ SQL connections/CPU ตามเวลาเดียวกัน README มี Bash49blocksแล้ว ไม่ให้ผู้เรียนเดา flags จากคำบรรยาย; sourceก่อนหน้ายังรอCI39929963331 job120335498899ที่ติดตั้งNginxอยู่ ไม่ยกCIเป็นผลGCPและยังไม่Guide-ready


Lab 05: Guide-ready — review ถึง source cd125100a884b17e641e28a625230f80dec3ed95 แล้ว: CI39929963331 ผ่าน52tests (49App/tooling +3guide checks), separate bootstrap และ browser→Nginx→API→PostgreSQLจริง; เอกสารที่เติมภายหลังตรวจด้วย CI39930610563 joblab005-guide ผ่าน49Bashblocks/relative links/Tasksections และ joblab005-infra validateทั้ง3rootsผ่าน (App/codeไม่เปลี่ยนจากชุดที่ผ่าน) SVG/PNG2ภาพตรวจ960pxและpublishedพร้อมiconprovenance คู่มือTasks0–14/7A/7B/9BครบR1–R8 มีactual/evidence/backout/cleanup/rebuildและขอบเขตผลตรวจชัดเจน ยังไม่มีGCP provisioning/HAfailover/IAMnetwork/apt-systemdจริง ทุกLabCloud Not run ขั้นถัดไป Lab06Brief; publicationCIของcommitสถานะใหม่ยังต้องติดตามต่อ ไม่ถือว่าGoal20Labเสร็จ


Lab06 / Brief: กำหนดprivate CSV upload/report solution R1–R8, candidateRun portal/worker+Storage+Eventarc+Firestore, owner/bearer capabilityขอบเขต, inputgenerationbinding/duplicateevents/lease-fencing/output-metadata-gaprecovery,1→5MiBchangeและcost/access/cleanup assumptions ตรวจเอกสารofficialแล้ว ยังต้องDesignก่อนMaterials/Tasks ไม่ใช่Guide-ready ไม่มีGCPwrites


Lab06 / Design: ปิดresource/identity/API/state contracts: namedFirestorelab006-files, CloudRunIAMworker, exactkey+boundedPOSTpolicy/keylesssignBlob, generationbinding/120slease/fencing/5attempts+boundedmanualepochs, deterministiccreate-onlyoutputและverify-reuseก่อนFirestorepublish, expiryเทียบTTL/lifecycle, testmatrix/emulatorและ1→5MiBchangeแล้ว ยังไม่มีMaterialsหรือผลGCPจริง ขั้นถัดไปparser/fixtures/Firestoretransactionsก่อนTasks


Lab06 / CSV domain materials: เพิ่มboundedreader/parser/canonicalsummaryและsyntheticvalid+duplicate fixtures/expectedsummary พร้อม10testsครอบคลุมUTF8/BOM/CRLF/quoted/multiline, schema, identifiers, integerbounds, rows/bytes, largerfilechangeและdeterminism; เพิ่มstdlib-onlyGitHubCIjob ยังรอผล ไม่ใช่Guide-ready และยังต้องFirestoretransaction/emulator/worker/HTTP/UI/IaC/Guide/Diagram ไม่มีGCPwrites


Lab06 / State transition materials: เพิ่มpuregenerationclaim/120slease/fencing/terminalexpiry/strictoutputbinding/retrybudget5และmanualepochs2พร้อม9tests แยกจากFirestoretransactionverification; แก้deadlineinterpretationให้ใช้objectfinalizedtimeไม่ใช่deliverytime เพื่อไม่rejecteventที่มาช้าแต่uploadทัน ชุดCSV CI39932134751ตรวจตามhandleจริง; stateชุดใหม่นี้ยังรอCI และต้องต่อFirestoreemulatorก่อนอ้างconcurrency ไม่มีGCPwrites


Lab06 / Firestore repository draft: เพิ่มSDKtransactionadapterสำหรับclaim/finish/release/operatorretryและownerread พร้อม4integrationtestsและGitHubjobที่เริ่มofficialFirestoreemulatorแบบloopback/namedDB/demo-project/anonymouscredential ไม่มีGCPauth/provisioning ชุดใหม่รอCI ยังต้องjobcreate-idempotency-quota/list/historyและworker/Storage/UI/IaC/Guide/Diagramก่อนGuide-ready


Lab06 / Verified first Firestore transactions + create draft: CI39932700165 lab006-domainและlab006-firestoreสำเร็จ (19puretestsและ4emulatorintegrationtests); เพิ่มcreate/idempotency/quota5active-20dailytransactionพร้อม4emulatortestsใหม่ race/replay/terminalslot/dailyreset/deletedreferencefailclosed รอCIชุดใหม่ ยังไม่Guide-ready ไม่มีGCPwrites


Lab06 / Worker orchestration draft: CI39932999988สำเร็จทั้งworkflowของcreate/quota (8Firestoretests+19puretests) เพิ่มprocessor/durableoncefaultmarkerและ4emulator-backedworker testsสำหรับoutput-metadatagaprecovery/singlelogicaloutput/rejectedfile/integrityfailure/ignoreunknowngeneration ชุดใหม่รอCI Storageยังเป็นtestdoubleในชุดนี้ ต้องต่อGCSadapter/HTTP/UI/IaC/Guide/Diagram ไม่ใช่Guide-ready ไม่มีGCPwrites


Lab06 / GCS adapter draft: เพิ่มpinnedgeneration boundedrawreads/no-decompressionและcreate-onlyCRC32Coutput/verify-existingbytes+hash+metadata พร้อม7SDKautospec/mocktransporttestsและCIstep ชุดworkerก่อนCI39933281841ยังตรวจตามhandle ไม่อ้างGCSจริง ชุดใหม่นี้รอCI ยังต้องsignedaccess/CloudEvent/HTTP/UI/IaC/Guide/Diagram ไม่มีGCPwrites


Lab06 / CloudEvent parser draft: CI39933281841 workerชุดก่อนผ่านpure+12Firestoreintegrationtests เพิ่มstrictbinaryCloudEventparser+5testsสำหรับenvelope/source/bucket/key/generation/timeCreated/duplicateJSON/bodybounds พร้อมCIstep ไม่มีการตามURLในevent; GCSชุด39933551789ยังlab006-firestorein_progressตอนตรวจ ชุดใหม่ยังรอCI ไม่อ้างIAMหรือGCPdeliveryจริง


Lab06 / Worker HTTP draft: CI39933551789 lab006-domain/firestoreสำเร็จรวม7GCScontracttests เพิ่มFlaskreceiver/boundedCloudEventdispatch/safe503-vs204/requestIDlogs/livez-healthzและruntimefactoryเลือกnamedDB+refuseemulators พร้อม6HTTPtestclienttests/CIstep ชุดใหม่รอCI ยังไม่พิสูจน์CloudRunIAMหรือStorageeventdeliveryจริง เหลือsignedaccess/portal/UI/IaC/Guide/Diagram ไม่มีGCPwrites


Lab06 / Signed access draft: เพิ่มowner/state/deadlinecheckedV4POSTpolicy(size/exactkey/MIME)และgeneration-pinnedshortGETพร้อม5realSDK/dummysignaturetests ไม่เรียกIAMsignBlob/GCSจริง ต้องต่อruntimecredentialssupplierและportalHTTP ชุดใหม่รอCI ไม่มีGCPwrites ไม่ใช่Guide-ready


Lab06 / Portal API draft: เพิ่มsession/CSRF/login/logout/jobcreate/read/ownercheckedcapabilityroutesและ6Flasktestsพร้อมCI ชุดsignedaccess39934400587ยังpendingตอนตรวจ ไม่claimผ่าน ต้องต่อruntimewiring/list/operator/UI/browserintegration/IaC/Guide/Diagram ไม่มีGCPwrites ไม่ใช่Guide-ready


Lab06 / Bounded owner listing: CI39934400587+39934698336 lab006jobsสำเร็จ เพิ่มFirestoreownerfilteredpagination(limit20/docIDcursor)+PortalGETlist/publicfieldprojectionพร้อม2testsใหม่ (emulator+HTTP) รอCIชุดนี้ ยังต้องoperatorretry/runtimewiring/UI/browser/IaC/Guide/Diagram ไม่มีGCPwrites


Lab06 / Operator inspection draft: เพิ่มboundedoperatorlist/detailและsafehistoryprojection; transactionstatechangesเก็บbounded100entryhistoryพร้อมtruncatedflag ไม่มีtoken/payload เพิ่ม3tests(emulator2/HTTP1) รอCIชุดใหม่ ก่อนเริ่มmanualretrydispatch/runtime/UI ยังไม่มีGCPwrites ไม่ใช่Guide-ready


Lab06 / Idempotent manual-retry preparation: เพิ่มoperator-requesthash→epoch transaction, 2epochbudget, stale-epochdispatchguardและimmutableinputfinalizedtime พร้อม2emulatorraces/replaytests ชุดใหม่รอCI; operatorinspectionชุด39935199632ยังติดตามhandleเดิม ไม่อ้างHTTPdispatchสำเร็จ ไม่มีGCPwrites


Lab06 / Manual retry HTTP draft: เพิ่มoperatorCSRFprepare→boundedIDtokenworkerdispatch→storedgeneration/epochguard เส้นทางส่งresponseหายเก็บepochเดิมและตอบunconfirmedไม่อ้างbusinessfailure พร้อม3HTTP/transporttests ชุดใหม่รอCI ยังต้องruntimecredentialwiring/UI/browser/IaC/Guide/Diagram ไม่มีGCPwrites


Lab06 / Portal runtime draft: เพิ่มprivatebundle(hash/sessionkeyแยกdemologins), strictboundedauthreader, attachedmetadataOAuth/IDtokensและruntimewiringเข้ากับJobs/Access/Dispatcher พร้อม5tests/CIstep ปฏิเสธkeyfileและemulatorในCloudRunruntime ชุดใหม่รอCIยังต้องUI/browser/IaC/Guide/Diagram ไม่มีGCPwrites


Lab06 / Portal UI draft: เพิ่มThaiUpload/status/download/operatorUI+boundedpoll+durablependingfilefingerprint/key+explicitnewretryepoch, CSP-compatibleexternalJS/CSS และindexroute/sessionlimits พร้อมJSsyntaxCI ยังรอbrowserintegration/renderreview; runtimeCI39936078257pendingตอนตรวจ ชุดdispatch39935686271lab006jobsผ่านแล้ว ไม่มีGCPwrites ไม่ใช่Guide-ready


Lab06 / Real browser test draft: runtimeCI39936078257 lab006jobsผ่านแล้ว เพิ่มChrome→HTTPSportal→Firestoreemulatorlost-create-response/reload/samekey/uploaddouble/Processor/summarytestและPNGartifact step พร้อมSelenium/fontdependencies ยังรอCI/renderreview ไม่อ้างGCS/IAMจริง เหลือIaC/Guide/Diagram/fullreview ไม่มีGCPwrites


Lab06 / Container materials draft: เพิ่มnonrootsharedimage/validatedrole-portentrypoint/threadbudgets/explicitcopy+dockerignoreและ3testsพร้อมcloudDockerbuild/import/privatefileexclusioncheck ไม่deploy Browser110run39936909967ยังpendingตามhandle ตอนตรวจชุดก่อน108ครบsuccess รอBrowserและcontainerCIก่อนclaimผล ไม่มีGCPwrites


Lab06 / Browser verified checkpoint: CI39936909967 lab006-firestoreสำเร็จ ตรวจlogsยืนยัน7GCS/5signed/8workerHTTP/9portalHTTP/5runtime/17FirestoretestsและrealChromejourneypass; เก็บPNG+provenanceบนGitHub เป็นCIloopback+emulator/Storagedouble ไม่ใช่GCP ตรวจภาพพบterminalbannerยังwaitingและdetailถูกviewportตัด จึงแก้banner/เพิ่มcaptureheightรอรอบใหม่ Container111run39937220454ยังpendingไม่มีjobsตอนตรวจ ไม่rerunหรือclaimผ่าน ไม่มีGCPwrites


Lab06 / Foundation IaC draft: เพิ่มprivatebuckets/lifecycle2d-softdelete7d/namedFirestoreTTL+destructiongates/5SAs/database-scopedIAM/customget-create-signroles/authcontainer/AR/Eventarcprerequisites พร้อมTerraformcloudCIไม่ใช้credentials ชุดใหม่รอvalidateยังไม่ใช่GCPplan/apply ต้องต่อworkloads/trigger/CORSphase+Guide/Diagram ไม่มีGCPwrites


Lab06 / Workloads IaC draft: CI39937892197ครบsuccess เพิ่มdigestpinnedCloudRunPortal/worker+numericSecretmount/specificworkerinvokers/Eventarctype-bucketfilter+path,limits/probes/deletiongates/faultdefaultfalse ปรับCIvalidateทั้ง2roots ยังไม่GCPplan/apply ไม่มีGCPwrites เหลือtools/Guide/Diagram/fullreviewและภาพรอบแก้ก่อนGuide-ready


Lab06 / Guide Tasks0–4 draft: เพิ่มพาทำCloudShellpersistentworkspace/cost-access-state→foundationreview/apply→privateauth/numericSecret→Dockerpush/digest→CloudRun/Eventarc/CORSและpositive-negativeHTTPchecks พร้อมExpected/Actual/stopcriteria/troubleshootingข้างงาน เพิ่มBashparse/relative-link/authoredtaskCItests ไม่executecloudcommands ชุดworkloadsCI39957408102ยังin_progressตอนตรวจ เหลือbusiness/ops/change/evidence/cleanup/Diagram/fullreviewก่อนGuide-ready ไม่มีGCPwrites


Lab06 / Business guide Tasks5–6: เพิ่มBrowserupload/download/reportcomparison, ambiguousresponse/samekeyresolution, fixturevalidation/terminalack, owner/role/anonymous/CSRFnegativechecks พร้อมActual/Storagegenerationevidence; เพิ่มboundedverify-reporttool+3testsและinvalidheader/quantityfixtures ชุดใหม่รอCI ยังค้างStorage-levelsize/MIMEtool/accessfault/change/cleanup/Diagram/fullreview ไม่อ้างCloudPASS ไม่มีGCPwrites


Lab06 / Bounded learner client draft: เพิ่มverifiedHTTPS/no-redirect/cookie-CSRF Portalclient+30call/10s/64KiBresponse/4KiBrequestboundsและprivatefileguard พร้อม3realHTTPloopbacktests เตรียมต่อStorageboundaryrunner ไม่claimpolicyenforcement ชุดใหม่รอCI ส่วนGuideชุด39958510836pendingตอนตรวจ ไม่มีGCPwrites


Lab06 / Storage boundary runner + Task7: CI39958914286ทุกlab006jobผ่าน แต่wholeworkflowfailที่Lab04secret-bundle subprocessrefusal timeout5s (ไม่ใช่logicassertion); ปรับเฉพาะsecretprocess testdeadlineเป็น30sโดยคงhash/permissions/nooverwriteassertions เพิ่มjournal-bound positive/oversize/MIME POSTrunner+4transport/contracttestsและGuideที่ไม่ถือHTTPerror/exit0เป็นPASS ชุดใหม่รอCI ไม่ยิงGCSจริงจากagent ยังเหลือops/change/cleanup/Diagram/fullreview


Lab06 / Recovery guide Tasks8–9: เพิ่มfault-before-readflagdefaultfalseเพื่อทดลองexhaust5attempts/failedbudgetและmanualepochrecoveryของgenerationเดิม พร้อมemulatorintegrationtest; workerlogsเพิ่มsafeprocessor-reason เพิ่มGuideoutput-metadatagap/503retry/outputgenerationverificationและoperatorretry/backout10minboundedwindows แยกsyntheticfaultจากจริง ชุดใหม่รอCI ยังเหลือexpiry/change/cleanup/Diagram/fullreview ไม่มีGCPwrites


Lab06 / Change guide Task10: เพิ่มdeterministicfixturegenerator(exact1/5MiB, byte-only/row-onlychange, over50krows/over5MiB)+3tests และพาทำbaseline→large→backout พร้อมold-jobcontractproof/metricsbudget/quotacount/evidence รอCIใหม่ ยังเหลือexpiry/evidence/cleanup/Diagram/fullreviewก่อนGuide-ready ไม่มีGCPwrites


Lab06 / Full guide draft Tasks11–13: เพิ่มcapability60s/300s/App24h/TTL48h/lifecycle-softdeleteแยกหลักฐานและNotrunเมื่อไม่รอจริง, R1–R8casestudy/evidence matrix, revieweddestructiongates/transport-objects-database-imageinventory/retainedcosts/privatefiles/rebuildlimits ไม่มีClock/DBtimefabrication ขยายguideCIตรวจTasks0–13/Bash23blocks/ConsoleJSsyntax ชุดใหม่รอCI ยังเหลือDiagram/consolidation/fullreviewก่อนGuide-ready ไม่มีGCPwrites


Lab06 / Full-guide CI verified + diagram authoring: CI39991195096 ของ source6bd5cffee995c873502ce82f98ca0dc0076b92b8 completed success ทั้งworkflow รวม Lab006domain/firestore-browser/container/infra และLab04timeoutregressionที่แก้แล้ว ไม่มีGCPprovisioning; แก้คู่มือไม่อ้างwall-clockdeadline45sที่โค้ดยังไม่enforceและไม่อ้างupload-deadlinereconcilerที่ไม่มี เพิ่มcloud-onlydiagramgenerator/CIสำหรับtopology+recovery ใช้officialarchiveพร้อมper-iconhashหรือgenericที่ติดป้ายชัด ยังต้องrender/ตรวจภาพ/บันทึกSVG-PNG/consolidateคู่มือ/fullreviewก่อนGuide-ready


Lab06 / Guide consolidation: รวมmaterialschangelogเป็นแผนที่ไฟล์และคำอธิบายพฤติกรรมปัจจุบัน แยกCIproofจากCloudActual เก็บcontract/quota/recovery/security/retentionและTasks0–13ไว้ครบ ลบคำอ้างยังไม่มีApp/รอCIเก่าที่ขัดกับผล39991195096 เพิ่มguidecheckไม่ให้ย้อนเป็นauthoringhistory Diagramรอบ124renderผ่านแต่พบเส้นstateทับheadingจึงแก้source3a560e05และรอrun126 ไม่publishภาพที่ยังไม่ตรงsource/ไม่Guide-readyก่อนreviewครบ ไม่มีGCPwrites


Lab06 / Replay and validation coverage: เพิ่ม authenticated replay ≤3 requests (same ID twice + new ID/same generation), source metadata pinned/fromStorageจริง, no-token-output และ Task8B แยกHTTPackจากbusinessresult/IAMtemporaryscope; เพิ่มprotocol-roundtrip testผ่านreceiverparserจริงและinvalidUTF8fixturegeneration+Task6+testเพื่อให้R3ทำได้จริง อัปเดตR4evidencematrix เพิ่มnetworktimeout/retryเฉพาะaptของLab005สำหรับCIรอบหน้า หลังrun127jobinstallค้างจริง ไม่cancel/rerunlivejob ชุดใหม่รอCI/ภาพสุดท้ายและreviewก่อนGuide-ready ไม่มีGCPwrites


Lab06 / Diagram publication: run129 CI39993882867 job120554175358 render topology+recoveryจากsourceffc7f89b5dfbbdefcf05f501c3385d5a9149a210สำเร็จ ตรวจภาพ960pxแล้วเส้นstateไม่ทับheading/Firestorelabel ขอบเขตproject-regionไม่มีVPCเทียมและdirectuploadแยกจากevent บันทึกSVG/PNG2ภาพ+officialiconpath/SHA/attributionลงassetsและembedREADME งานreplayชุดก่อนผ่านlab006-domainในrun129 ส่วนroundtrip/UTF8fixtureเพิ่มล่าสุดรอrun130 CI39994451947ก่อนclaimครบ ยังAuthoring/CloudNotrun ไม่มีGCPwrites


Lab06: Guide-ready — review ครบ R1–R8 และ Tasks0–13/8B: direct signed POST/private incoming+results, namedFirestore transactions/quota/lease-fencing, deterministic create-or-verify output, recovery/operator retry, validation/Storage bounds/expiry/change/backout/evidence/cleanup/rebuild พร้อมเครื่องมือและ fixtures จริง CI39994451947 source58b8f719b6a881c40936fd95c88c6c1733dec19f completed success ทั้งworkflow: 52domain/state/tooling/guide +53SDK/HTTP/runtime/emulator/browser =105tests, containerbuild/import/nonroot/exclusionและTerraformสองrootsผ่าน CI39994675895ของpublication61baf2d940bb6571009bb2f8b1ae9dbf5ccd9e6b joblab006-domainผ่านหลังเพิ่มภาพ/links (25Bash/7JS); runtimecodeไม่เปลี่ยน ภาพSVG/PNGสองชุดreview960pxและpublishedพร้อมofficialiconpath/hash/attributionแล้ว ปรับการเว้นวรรคเฉพาะร้อยแก้วโดยfencedcommandsไม่เปลี่ยน ยังไม่มีGCPapply/IAM/signBlob/GCS/Eventarc/performance/retentionจริง ทุกLabCloud Notrun รอpublicationCIของสถานะใหม่ต่อ ขั้นถัดไป Lab07Brief ไม่ถือว่าGoal20Labเสร็จ


Lab07 / Brief: เริ่มหลังLab06Guide-ready กำหนดOrderQueueDesk R1–R9: DBorder+transactionaloutboxแก้dualwritegap, authenticatedPubSubpush, PostgreSQLreservationledger/idempotency/stockrace, transient-vs-businessrejection-vs-poison/DLQ, canonicalredrive/unknownoutcome, owner/IAM/DBseparation และ1→3workercapacityพร้อมconnectionbudget ตรวจofficialPubSubpush/exactlyonce-pullonly/deadletterapproxpermissions/RunSQLprivateIPแล้ว ยังต้องDesignก่อนMaterials/Tasks ไม่มีApp/Diagram/GCPผลสำเร็จ ไม่Guide-ready


Lab07 / Design: ปิดresource/identity/API/schema/outbox/stocktransaction/ack-DLQ-redriveและcapacitycontracts เลือกRun3services+SchedulerOIDC/PubSubpush-DLT/PG16privateIP+PythonconnectorTLS+DBroles/Secretversions; no-network-underSQLlocks, dispatcherleasefencing120s/budget/attempts, canonicalevent/orderbinding, SQLatomicreservation+ledger, unknownpublish/commit-before-ackrecovery, boundedoperatorcanonicalreplayและconnectionbudget1→3workers พร้อมCI/test/taskorder/cleanupboundaries ยังไม่มีMaterials/schema/App/DiagramหรือGCPผลจริง ขั้นถัดไปdomain/SQLtests ไม่Guide-ready


Lab07 / Domain materials: เพิ่มstrictorder/event/wrappedpushparser, sortedrequestfingerprint/owner-keyhash/server-pricebinding, bounds/duplicateJSON/NaN/base64/aliasconflict และsyntheticcatalog/orderfixture พร้อม10testsกับcloud-onlyCI job ตรวจofficialpushตัวอย่างพบmessage_id/publish_timealiasesจึงรองรับแบบconsistentก่อนเขียนworker ชุดใหม่รอCI ไม่ถือdomainเป็นSQLrace/Queueverification Lab06publicationCI39995374068 completed successแล้ว ไม่มีGCPwrites ขั้นถัดไปSQLschema/roles/realPGtests


Lab07 / SQL materials draft: เพิ่มPGschema/seed/constraints+NOLOGINleastprivilegeroles, DBAPIOrders repositoryสำหรับatomiccreate+outbox/advisorykeylockและrowlockedall-or-nothingstock+immutableledger/dedup/integrity/ownerread ใช้pg8000 1.31.5ตรงdriverที่จะใช้กับconnector เพิ่ม12realPG16integrationtests+cloudCIloopbackguard ครอบคลุมrace/rollback/commit-before-ack/grants/price-snapshot ชุดใหม่รอCIยังไม่อ้างผ่าน และยังต้องdispatcher/workerHTTP/runtime/bootstrap/UI/IaC/Guide/Diagram ไม่มีGCPwrites


Lab07 / Domain CI repair: run135 CI39997198051 job120566760448 พบdeepJSONtestไม่rejectเพราะruntimejsonรับ2000nestedcontainersได้ แก้parserให้ตรวจcontainerdepth≤8แบบiterativeไม่พึ่งPythonrecursionlimit และเพิ่มexact8/9boundarytestโดยคงmalformed/deepinputcasesเดิม รวม11domaintests ชุดใหม่รอCI SQLชุด5074f4fเพิ่ม12testsยังรอrun136 ไม่อ้างผ่าน/ไม่มีGCPwrites


Lab07 / PG harness repair: run136 CI39998517007 job120568813797สร้างschema/rolesสำเร็จแต่ทั้ง12testsยังไม่ถึงbusinessassertions เพราะtestadminhelperส่งNoneให้pg8000.executeซึ่งdriverต้องการsequence แก้เป็นtupleparametersเดิม (emptytupleเมื่อไม่มีparams) ไม่เปลี่ยนSQLlogic/ลดassertions ยังรอCIยืนยันผลจริง Domainfailureของrun136เป็นsourceเก่าก่อนexplicitdepthrepair0da997a8 ไม่restartliveworkflow ไม่มีGCPwrites


CI network bound: run136ยังliveที่lab006-firestore/InstallThaiFontsตามjobsAPI หลังเกิดaptwaitingซ้ำ เพิ่มnetwork30s/retry2และwholecommand180sให้aptupdate/installที่ยังไม่มีboundสำหรับรอบหน้า ไม่ตัดbrowser/diagrams/assertionsและไม่cancel/restartliveworkflow Lab007repairedSQL/domainยังรอคิวตามhandle39998969114 ไม่มีGCPwrites


Lab07 / First SQL verified + outbox draft: CI39999204524 source10bace2db521edd3a1cc2be87eaf0b9ad86e4dca jobs120571400843/120571400868ผ่าน11domain+12realPG16tests อ่านlogsยืนยันrace/rollback/grants/price/bindingแล้ว (wholeworkflowยังติดตามแยก) เพิ่มOutboxshortclaimSKIPLOCKED/120slease-tokenfencing/finish/release/10attemptbudget/canonicalintegrityquarantine และ6PGtestsใหม่ รวมSQL18ชุดใหม่รอCI ยังไม่มีactualPubSubpublisher/Cloudผลจริง


Lab07 / Outbox verified + publisher draft: run140 CI40000048463 source50884b294e0ea478812e1570dcc0e44617b490ed completed success ทั้งworkflow อ่านjob120573981066ยืนยัน18realPGtestsรวมclaim/fencing/unconfirmedpublish/budget/integrity และ11domainผ่าน เพิ่มsyncGAPICsinglepublish(retryNone/RPC5s), boundedDispatcher20claims/cooperative40s/no-tight-retry/finishunknownไม่releaseทับ พร้อม8unit+5SDKcontract+4PGintegrationใหม่ (SQL22) รอCI ไม่เรียกPubSub/GCPจริง ไม่มีprovisioning


Lab07 / Publisher verified + HTTP draft: run141 CI40001402332 sourceb674318dad81e808c97cc97f20ef442efa98b23b jobs120578122380/120578122460ผ่าน11domain+8dispatcher+5SDK+22PG=46tests อ่านlogsยืนยันsingleRPC/retryNone/timeout5/noSQLlock/unknownpublish-finishrecoveryแล้ว ไม่ใช่PubSubจริง เพิ่มworker+dispatcherFlaskfactories/body-routing/ack204-vs400/503/safeJSONlogs/serverRequestID/livez-vsDBhealth พร้อม10HTTPtests+1PGhealth (SQL23) รอCI ยังต้องruntime/Portal/operator/bootstrap/IaC/Guide/Diagram ไม่มีGCPwrites
