# GCP Solution Labs

[แผน 20 Solution Labs สำหรับ Cloud Engineer](ROADMAP.md)

หนึ่ง Lab คือหนึ่ง Solution ที่จบทั้งสร้างและดูแลในเรื่องเดียว ใช้คู่มือ README เดียว พร้อมไฟล์ App/Script ที่จำเป็น แต่ละ Lab มีจุดเริ่มต้นครบในตัว ไม่ต้องกระโดดไปสร้างระบบจาก Lab อื่น

ทำตามลำดับ: ภาพใหญ่ 20 โจทย์ → Lab brief ทีละเรื่อง → ออกแบบ Tasks → เขียน Guide → ลงมือ ตรวจผลและปิดงาน → Lab ถัดไป

ตัวอย่างรูปแบบคู่มือ: [Lab Test 2](../test/lab-test-2/README.md)

สถานะปัจจุบัน: [Lab 01](LAB-001-multi-zone-web/README.md) ถึง [Lab 11 — GKE Quote Engine](LAB-011-gke-quote-engine/README.md) อยู่ระดับ Guide-ready. Lab 11 ผ่าน [CI #315](https://github.com/somkid-s5/Portfolio-Lab/actions/runs/40092884085) ครบ 39/39 jobs; CI ตรวจ App/Integration, Terraform, manifests, 20 Tasks, evidence fields, Bash syntax, links และ diagram/design. Lab 12–20 ยัง Planned ตาม [Progress](PROGRESS.md). ไม่มีการ provision GCP; Cloud verification ยังคง Not run.
