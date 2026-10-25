const slotRoot = document.getElementById("slots");
const bookingStatus = document.getElementById("booking-status");
const reportStatus = document.getElementById("report-status");
const reportRoot = document.getElementById("reports");
const connectionStatus = document.getElementById("connection-status");

function showStatus(node, message, failed) {
  node.textContent = message || "";
  node.classList.toggle("error", Boolean(failed));
}
function keyFor(action) {
  if (window.crypto && window.crypto.randomUUID) return action + "-" + window.crypto.randomUUID();
  return action + "-" + Date.now() + "-" + Math.random().toString(16).slice(2);
}
async function callApi(path, options) {
  const response = await fetch(path, Object.assign({ credentials: "same-origin" }, options || {}));
  const contentType = response.headers.get("content-type") || "";
  const body = contentType.includes("application/json") ? await response.json() : await response.text();
  if (!response.ok) {
    const message = body && body.error ? body.error : "request_failed_" + response.status;
    throw new Error(message + " · request " + (response.headers.get("X-Request-ID") || "unknown"));
  }
  return body;
}
function slotRow(slot) {
  const row = document.createElement("article"); row.className = "slot-row";
  const detail = document.createElement("div");
  const name = document.createElement("div"); name.className = "slot-name"; name.textContent = slot.label;
  const meta = document.createElement("div"); meta.className = "slot-meta";
  meta.textContent = new Date(slot.starts_at).toLocaleString("th-TH", { timeZone: "UTC" }) + " UTC";
  detail.append(name, meta);
  const capacity = document.createElement("span"); capacity.className = "capacity";
  capacity.textContent = slot.booked + " / " + slot.capacity + " ที่นั่ง";
  const button = document.createElement("button"); button.className = "button primary"; button.type = "button";
  button.textContent = "จอง"; button.disabled = slot.booked >= slot.capacity;
  button.addEventListener("click", async () => {
    button.disabled = true; showStatus(bookingStatus, "กำลังบันทึกการจอง…", false);
    try {
      const result = await callApi("/api/bookings", {
        method: "POST",
        headers: { "Content-Type": "application/json", "Idempotency-Key": keyFor("booking") },
        body: JSON.stringify({ slot_id: slot.slot_id })
      });
      showStatus(bookingStatus, "จองสำเร็จ · booking " + result.booking.booking_id, false);
      await loadSlots();
    } catch (error) { showStatus(bookingStatus, error.message, true); await loadSlots(); }
  });
  row.append(detail, capacity, button); return row;
}
async function loadSlots() {
  slotRoot.replaceChildren();
  try {
    const result = await callApi("/api/slots");
    if (!result.slots.length) { slotRoot.textContent = "ยังไม่มีช่วงเวลาให้จอง"; return; }
    result.slots.forEach((slot) => slotRoot.append(slotRow(slot)));
    connectionStatus.textContent = "API และฐานข้อมูลพร้อมใช้งาน · " + result.slots.length + " ช่วงเวลา";
  } catch (error) {
    slotRoot.textContent = "โหลดข้อมูลไม่สำเร็จ: " + error.message;
    connectionStatus.textContent = "ตรวจสอบการเชื่อมต่อ API และ Cloud SQL";
  }
}
function reportRow(reportId, status, reportDate) {
  const row = document.createElement("article"); row.className = "report-row";
  const badge = document.createElement("span"); badge.className = "badge" + (status === "ready" ? "" : " pending");
  badge.textContent = status;
  const name = document.createElement("div"); name.className = "report-name";
  name.textContent = reportDate + " · " + reportId.slice(0, 8);
  row.append(badge, name);
  if (status === "ready") {
    const link = document.createElement("a"); link.href = "/api/reports/" + encodeURIComponent(reportId) + "/download";
    link.textContent = "ดาวน์โหลด CSV"; row.append(link);
  }
  reportRoot.prepend(row);
}
document.getElementById("refresh").addEventListener("click", loadSlots);
document.getElementById("report-date").value = new Date().toISOString().slice(0, 10);
document.getElementById("report-form").addEventListener("submit", async (event) => {
  event.preventDefault(); const input = document.getElementById("report-date");
  showStatus(reportStatus, "ส่งคำขอสร้างรายงาน…", false);
  try {
    const accepted = await callApi("/api/reports", {
      method: "POST",
      headers: { "Content-Type": "application/json", "Idempotency-Key": keyFor("report") },
      body: JSON.stringify({ report_date: input.value })
    });
    showStatus(reportStatus, "รับคำขอแล้ว · report " + accepted.report_id + " · กำลังรอ Worker", false);
    reportRow(accepted.report_id, accepted.status, input.value);
    let attempts = 0;
    const timer = window.setInterval(async () => {
      attempts += 1;
      try {
        const current = await callApi("/api/reports/" + encodeURIComponent(accepted.report_id));
        const record = current.report; reportRow(record.report_id, record.status, record.report_date);
        if (record.status === "ready" || record.status === "failed" || attempts >= 30) {
          window.clearInterval(timer);
          showStatus(reportStatus, record.status === "ready" ? "รายงานพร้อมดาวน์โหลดแล้ว" :
            "รายงานยังไม่พร้อม · ตรวจสถานะและ Logs Explorer ตามคู่มือ", record.status !== "ready");
        }
      } catch (error) { window.clearInterval(timer); showStatus(reportStatus, error.message, true); }
    }, 2000);
  } catch (error) { showStatus(reportStatus, error.message, true); }
});
loadSlots();
