// 실데이터(JS) -> Python 백엔드용 seed CSV 변환
// 입력: data/order_list_2026_06.js (USED 이력), data/current_order_stock_2026_06.js (ORDER -> IN_STOCK 재고)
// 출력: data/seed_flexibag_inventory.csv (HTML MVP와 동일한 535 IN_STOCK + 8,443 USED 시리얼)
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const rootDir = path.resolve(path.dirname(__filename), "..");
const dataDir = path.join(rootDir, "data");

global.window = {};
await import(pathToFileURL(path.join(dataDir, "order_list_2026_06.js")));
const usedRows = window.orderListRows;
await import(pathToFileURL(path.join(dataDir, "current_order_stock_2026_06.js")));
const orderRows = window.currentOrderStockRows;

function csvEscape(value) {
  const text = String(value ?? "");
  return /[",\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

const seen = new Set();
const lines = ["serial_no,location_id,status,intake_date,used_date,current_order_id,note"];
let skippedDup = 0;

for (const row of orderRows) {
  if (seen.has(row.serial_no)) { skippedDup++; continue; }
  seen.add(row.serial_no);
  lines.push([
    row.serial_no, row.location_id, "IN_STOCK", row.intake_date || "", "", "", row.note || "",
  ].map(csvEscape).join(","));
}

for (const row of usedRows) {
  if (seen.has(row.serial_no)) { skippedDup++; continue; }
  seen.add(row.serial_no);
  lines.push([
    row.serial_no, row.location_id, "USED", row.intake_date || row.work_date || "", row.work_date || "", "", row.carrier || "",
  ].map(csvEscape).join(","));
}

const outPath = path.join(dataDir, "seed_flexibag_inventory.csv");
fs.writeFileSync(outPath, lines.join("\n") + "\n", "utf8");

console.log(JSON.stringify({
  inStockWritten: orderRows.length,
  usedWritten: usedRows.length,
  totalRows: lines.length - 1,
  skippedDuplicateSerials: skippedDup,
  outPath,
}, null, 2));
