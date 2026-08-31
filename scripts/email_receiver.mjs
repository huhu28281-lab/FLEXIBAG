import fs from "node:fs";
import path from "node:path";
import tls from "node:tls";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const rootDir = path.resolve(__dirname, "..");
const dataDir = path.join(rootDir, "data");
const envPath = path.join(rootDir, ".env.mail");
const emailsJsPath = path.join(dataDir, "incoming_email_intake.js");
const schedulesJsPath = path.join(dataDir, "incoming_schedules.js");
const processedPath = path.join(dataDir, "processed_email_uids.json");

function loadEnv(filePath) {
  if (!fs.existsSync(filePath)) {
    throw new Error(`Missing ${filePath}. Copy .env.mail.example to .env.mail and fill mailbox settings.`);
  }
  const env = {};
  for (const line of fs.readFileSync(filePath, "utf8").split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) continue;
    const index = trimmed.indexOf("=");
    if (index === -1) continue;
    env[trimmed.slice(0, index).trim()] = trimmed.slice(index + 1).trim();
  }
  return env;
}

function readJsArray(filePath, variableName) {
  if (!fs.existsSync(filePath)) return [];
  const text = fs.readFileSync(filePath, "utf8");
  const match = text.match(new RegExp(`window\\.${variableName}\\s*=\\s*([\\s\\S]*?);\\s*$`));
  if (!match) return [];
  return JSON.parse(match[1]);
}

function writeJsArray(filePath, variableName, rows) {
  fs.writeFileSync(filePath, `window.${variableName} = ${JSON.stringify(rows, null, 2)};\n`, "utf8");
}

function loadProcessed() {
  if (!fs.existsSync(processedPath)) return [];
  return JSON.parse(fs.readFileSync(processedPath, "utf8"));
}

function saveProcessed(rows) {
  fs.writeFileSync(processedPath, JSON.stringify([...new Set(rows)], null, 2), "utf8");
}

function makeId(prefix, seed = "") {
  const stamp = new Date().toISOString().replace(/[-:TZ.]/g, "").slice(0, 14);
  let hash = 0;
  for (const ch of seed) hash = ((hash << 5) - hash + ch.charCodeAt(0)) | 0;
  return `${prefix}-${stamp}-${Math.abs(hash).toString(16).slice(0, 6).toUpperCase().padStart(6, "0")}`;
}

function decodeMimeWord(value = "") {
  return value.replace(/=\?([^?]+)\?([BQbq])\?([^?]+)\?=/g, (_, charset, encoding, text) => {
    try {
      const bytes = encoding.toUpperCase() === "B"
        ? Buffer.from(text, "base64")
        : Buffer.from(text.replaceAll("_", " ").replace(/=([A-Fa-f0-9]{2})/g, (_, hex) => String.fromCharCode(parseInt(hex, 16))), "binary");
      return bytes.toString(charset.toLowerCase().includes("euc") ? "utf8" : "utf8");
    } catch {
      return text;
    }
  });
}

function parseHeaders(rawEmail) {
  const [rawHeaders] = rawEmail.split(/\r?\n\r?\n/, 1);
  const lines = rawHeaders.split(/\r?\n/);
  const unfolded = [];
  for (const line of lines) {
    if (/^[ \t]/.test(line) && unfolded.length) unfolded[unfolded.length - 1] += " " + line.trim();
    else unfolded.push(line);
  }
  const headers = {};
  for (const line of unfolded) {
    const index = line.indexOf(":");
    if (index === -1) continue;
    headers[line.slice(0, index).toLowerCase()] = decodeMimeWord(line.slice(index + 1).trim());
  }
  return headers;
}

function decodeQuotedPrintable(text) {
  return text
    .replace(/=\r?\n/g, "")
    .replace(/=([A-Fa-f0-9]{2})/g, (_, hex) => String.fromCharCode(parseInt(hex, 16)));
}

function stripHtml(value) {
  return value
    .replace(/<br\s*\/?>/gi, "\n")
    .replace(/<\/p>/gi, "\n")
    .replace(/<[^>]+>/g, " ")
    .replace(/&nbsp;/g, " ")
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/\s+\n/g, "\n")
    .replace(/[ \t]{2,}/g, " ")
    .trim();
}

function extractBody(rawEmail) {
  const body = rawEmail.split(/\r?\n\r?\n/).slice(1).join("\n\n");
  const headers = parseHeaders(rawEmail);
  const contentType = headers["content-type"] || "";
  if (!contentType.toLowerCase().includes("multipart/")) {
    const transfer = (headers["content-transfer-encoding"] || "").toLowerCase();
    let text = body;
    if (transfer.includes("quoted-printable")) text = decodeQuotedPrintable(text);
    if (transfer.includes("base64")) text = Buffer.from(text.replace(/\s/g, ""), "base64").toString("utf8");
    return contentType.toLowerCase().includes("html") ? stripHtml(text) : text.trim();
  }

  const boundaryMatch = contentType.match(/boundary="?([^";]+)"?/i);
  if (!boundaryMatch) return stripHtml(body);
  const boundary = boundaryMatch[1];
  const parts = body.split(`--${boundary}`);
  const candidates = [];
  for (const part of parts) {
    const [partHeaderText, ...bodyParts] = part.split(/\r?\n\r?\n/);
    if (!bodyParts.length) continue;
    const partBody = bodyParts.join("\n\n").replace(/\r?\n--$/, "");
    const fakeEmail = `${partHeaderText}\n\n${partBody}`;
    const partHeaders = parseHeaders(fakeEmail);
    const type = (partHeaders["content-type"] || "").toLowerCase();
    const transfer = (partHeaders["content-transfer-encoding"] || "").toLowerCase();
    let text = partBody;
    if (transfer.includes("quoted-printable")) text = decodeQuotedPrintable(text);
    if (transfer.includes("base64")) text = Buffer.from(text.replace(/\s/g, ""), "base64").toString("utf8");
    if (type.includes("text/plain")) candidates.unshift(text.trim());
    if (type.includes("text/html")) candidates.push(stripHtml(text));
  }
  return (candidates.find(Boolean) || stripHtml(body)).trim();
}

function locationFromText(text) {
  const upper = text.toUpperCase();
  if (upper.includes("ULSAN") || text.includes("울산")) return "ULS";
  if (upper.includes("DAESAN") || text.includes("대산")) return "DSN";
  if (upper.includes("GUNSAN") || text.includes("군산")) return "GSN";
  if (upper.includes("PYEONGTAEK") || text.includes("평택")) return "PTK";
  return "";
}

function extractDate(text) {
  const korean = text.match(/(?:(20\d{2})\s*년\s*)?(\d{1,2})\s*월\s*(\d{1,2})\s*일/);
  if (korean) return `${korean[1] || new Date().getFullYear()}-${String(korean[2]).padStart(2, "0")}-${String(korean[3]).padStart(2, "0")}`;
  const iso = text.match(/\b(20\d{2})[-/.](\d{1,2})[-/.](\d{1,2})\b/);
  if (iso) return `${iso[1]}-${String(iso[2]).padStart(2, "0")}-${String(iso[3]).padStart(2, "0")}`;
  const noYear = text.match(/(?:work\s*date|작업일|작업\s*날짜)\s*[:#-]?\s*(\d{1,2})[/.](\d{1,2})\b/i);
  if (noYear) return `${new Date().getFullYear()}-${String(noYear[1]).padStart(2, "0")}-${String(noYear[2]).padStart(2, "0")}`;
  return "";
}

function first(pattern, text) {
  const match = text.match(pattern);
  if (!match) return "";
  return match.slice(1).find(Boolean) || "";
}

function parseEmailToSchedule(subject, body) {
  const text = `${subject}\n${body}`;
  const compact = text.replace(/[ \t]+/g, " ");
  const cntr = compact.match(/\b((?:20|40)(?:DV|HC|HQ|GP|RF|FT))\b\s*(?:[*xX]\s*(\d+))?/i);
  const qty = compact.match(/\b(?:QNTY|QTY|QUANTITY|CNTR\s*QTY|수량)\b[^0-9]{0,12}(\d+)/i);
  const unitQty = compact.match(/\b(\d+)\s*(?:개|EA(?!\w))/i);
  const size = compact.match(/\b(22|24|25)\s*KL\b/i);
  const pol = first(/\bPOL\s*[:#-]?\s*([A-Z가-힣]+)/i, compact);
  const cntrQty = qty ? Number(qty[1]) : (cntr && cntr[2] ? Number(cntr[2]) : (unitQty ? Number(unitQty[1]) : 0));
  const parsed = {
    work_date: extractDate(compact),
    bkg_no: first(/\b(?:BKG|BOOKING(?:\s*NO\.?)?)\s*[:#-]?\s*([A-Z0-9-]{8,})/i, compact),
    po_no: first(/\b(?:PO|P\/O)(?![A-Za-z])\s*(?:NO\.?)?\s*[:#-]?\s*([A-Z0-9-]+)/i, compact),
    location_id: locationFromText(`${pol} ${text}`),
    pol: pol ? pol.toUpperCase() : "",
    pod: first(/\bPOD\s*[:#-]?\s*([A-Z가-힣]+)/i, compact).toUpperCase(),
    item: first(/\bITEM\s*[:#-]?\s*([^,\n]+)/i, text),
    flexibag_size: size ? `${size[1]}KL` : "",
    cntr_type: cntr ? cntr[1].toUpperCase() : "",
    cntr_qty: cntrQty,
    flexibag_qty: cntrQty,
    vessel_voy: first(/\bVESSEL(?:\/VOY)?\s*[:#-]?\s*([^,\n]+)/i, text),
    terminal: first(/\bTERMINAL\s*[:#-]?\s*([^,\n]+)/i, text),
    destination: first(/\bDESTINATION\s*[:#-]?\s*([^,\n]+)/i, text),
    warnings: []
  };
  if (!parsed.work_date) parsed.warnings.push("MISSING_WORK_DATE");
  if (!parsed.bkg_no) parsed.warnings.push("MISSING_BKG");
  if (!parsed.location_id) parsed.warnings.push("MISSING_LOCATION");
  if (!parsed.flexibag_qty) parsed.warnings.push("MISSING_QTY");
  parsed.confidence = parsed.warnings.length === 0 ? "high" : parsed.warnings.length <= 2 ? "medium" : "low";
  return parsed;
}

function isWorkRequestMail(subject, body) {
  const text = `${subject}\n${body}`.toUpperCase();
  const strong = /(BKG|BOOKING|CNTR|QNTY|QTY|POL|POD|FLEXI|FLEXIBAG|22KL|24KL|25KL|FITTING)/.test(text);
  const korean = /(핏팅|운송|작업|설치|울산|대산|군산|평택)/.test(`${subject}\n${body}`);
  return strong || korean;
}

class ImapClient {
  constructor(config) {
    this.config = config;
    this.tagNo = 1;
    this.buffer = "";
    this.socket = null;
  }

  connect() {
    return new Promise((resolve, reject) => {
      this.socket = tls.connect({
        host: this.config.IMAP_HOST,
        port: Number(this.config.IMAP_PORT || 993),
        servername: this.config.IMAP_HOST
      });
      this.socket.setEncoding("utf8");
      this.socket.on("data", (chunk) => { this.buffer += chunk; });
      this.socket.on("error", reject);
      this.socket.on("secureConnect", async () => {
        try {
          await this.waitFor(/\* OK/);
          resolve();
        } catch (error) {
          reject(error);
        }
      });
    });
  }

  async waitFor(regex) {
    const start = Date.now();
    while (Date.now() - start < 30000) {
      if (regex.test(this.buffer)) return this.buffer;
      await new Promise((resolve) => setTimeout(resolve, 50));
    }
    throw new Error(`IMAP timeout waiting for ${regex}`);
  }

  async command(command) {
    const tag = `A${String(this.tagNo++).padStart(4, "0")}`;
    this.buffer = "";
    this.socket.write(`${tag} ${command}\r\n`);
    const text = await this.waitFor(new RegExp(`${tag} (OK|NO|BAD)`));
    if (new RegExp(`${tag} (NO|BAD)`).test(text)) throw new Error(`IMAP command failed: ${command}\n${text}`);
    return text;
  }

  async login() {
    const user = quoteImap(this.config.IMAP_USER);
    const pass = quoteImap(this.config.IMAP_PASS);
    await this.command(`LOGIN ${user} ${pass}`);
  }

  async selectMailbox() {
    await this.command(`SELECT ${quoteMailbox(this.config.IMAP_MAILBOX || "INBOX")}`);
  }

  async searchUnseen() {
    const response = await this.command("UID SEARCH UNSEEN");
    const line = response.split(/\r?\n/).find((row) => row.startsWith("* SEARCH")) || "";
    return line.replace("* SEARCH", "").trim().split(/\s+/).filter(Boolean);
  }

  async fetchRaw(uid) {
    const tag = `A${String(this.tagNo++).padStart(4, "0")}`;
    this.buffer = "";
    this.socket.write(`${tag} UID FETCH ${uid} BODY.PEEK[]\r\n`);
    const text = await this.waitFor(new RegExp(`${tag} (OK|NO|BAD)`));
    const literal = text.match(new RegExp(`\\{(\\d+)\\}\\r?\\n([\\s\\S]*?)\\)\\r?\\n${tag} `));
    return literal ? literal[2] : text;
  }

  async markSeen(uid) {
    await this.command(`UID STORE ${uid} +FLAGS (\\Seen)`);
  }

  async logout() {
    try {
      await this.command("LOGOUT");
    } finally {
      this.socket?.end();
    }
  }
}

function quoteImap(value = "") {
  return `"${String(value).replace(/\\/g, "\\\\").replace(/"/g, '\\"')}"`;
}

function quoteMailbox(value = "INBOX") {
  return quoteImap(value);
}

function senderAllowed(headers, allowedSenders) {
  if (!allowedSenders.length) return true;
  const from = (headers.from || "").toLowerCase();
  return allowedSenders.some((item) => from.includes(item.toLowerCase()));
}

function mergeUnique(existingRows, newRows, keyName) {
  const map = new Map();
  for (const row of existingRows) map.set(row[keyName], row);
  for (const row of newRows) map.set(row[keyName], row);
  return [...map.values()].sort((a, b) => String(b.received_at || b.work_date).localeCompare(String(a.received_at || a.work_date)));
}

async function pollOnce() {
  const config = loadEnv(envPath);
  const allowedSenders = (config.ALLOWED_SENDERS || "").split(",").map((item) => item.trim()).filter(Boolean);
  const processed = loadProcessed();
  const processedSet = new Set(processed);
  const client = new ImapClient(config);
  const newEmailRows = [];
  const newScheduleRows = [];
  const newProcessed = [];

  await client.connect();
  try {
    await client.login();
    await client.selectMailbox();
    const uids = await client.searchUnseen();
    for (const uid of uids) {
      if (processedSet.has(uid)) continue;
      const rawEmail = await client.fetchRaw(uid);
      const headers = parseHeaders(rawEmail);
      if (!senderAllowed(headers, allowedSenders)) continue;
      const subject = headers.subject || "";
      const body = extractBody(rawEmail);
      const workRequest = isWorkRequestMail(subject, body);
      const parsed = workRequest ? parseEmailToSchedule(subject, body) : null;
      const emailId = makeId("EM", headers["message-id"] || uid);
      const status = !workRequest ? "IGNORED" : parsed.warnings.length ? "NEEDS_REVIEW" : "PARSED";
      newEmailRows.push({
        email_id: emailId,
        uid,
        message_id: headers["message-id"] || "",
        received_at: new Date().toLocaleString("sv-SE"),
        from_email: headers.from || "",
        to_emails: headers.to || "",
        cc_emails: headers.cc || "",
        subject,
        raw_body: body,
        parsed_json: parsed ? JSON.stringify(parsed) : "",
        parse_confidence: parsed?.confidence || "low",
        status,
        source: "IMAP"
      });
      if (workRequest) {
        newScheduleRows.push({
          schedule_id: makeId("SCH", `${parsed.bkg_no}-${parsed.work_date}-${uid}`),
          source_email_id: emailId,
          work_date: parsed.work_date || new Date().toISOString().slice(0, 10),
          bkg_no: parsed.bkg_no,
          po_no: parsed.po_no,
          location_id: parsed.location_id,
          pol: parsed.pol,
          pod: parsed.pod,
          item: parsed.item,
          flexibag_size: parsed.flexibag_size || "24KL",
          cntr_type: parsed.cntr_type,
          cntr_qty: parsed.cntr_qty,
          flexibag_qty: parsed.flexibag_qty,
          vessel_voy: parsed.vessel_voy,
          terminal: parsed.terminal,
          destination: parsed.destination,
          status: "PENDING_CONFIRMATION",
          confirmed_by: "",
          confirmed_at: ""
        });
      }
      newProcessed.push(uid);
      if ((config.MARK_SEEN || "").toLowerCase() === "true") await client.markSeen(uid);
    }
  } finally {
    await client.logout();
  }

  const emailRows = mergeUnique(readJsArray(emailsJsPath, "incomingEmailRows"), newEmailRows, "email_id");
  const scheduleRows = mergeUnique(readJsArray(schedulesJsPath, "incomingScheduleRows"), newScheduleRows, "schedule_id");
  writeJsArray(emailsJsPath, "incomingEmailRows", emailRows);
  writeJsArray(schedulesJsPath, "incomingScheduleRows", scheduleRows);
  saveProcessed([...processed, ...newProcessed]);
  console.log(JSON.stringify({
    received: newEmailRows.length,
    schedules: newScheduleRows.length,
    totalEmails: emailRows.length,
    totalSchedules: scheduleRows.length
  }, null, 2));
}

async function main() {
  const config = loadEnv(envPath);
  const pollSeconds = Math.max(Number(config.POLL_SECONDS || 180), 30);
  const once = process.argv.includes("--once");
  await pollOnce();
  if (once) return;
  setInterval(() => {
    pollOnce().catch((error) => {
      console.error(`[${new Date().toLocaleString("sv-SE")}]`, error.message);
    });
  }, pollSeconds * 1000);
}

main().catch((error) => {
  console.error(error.message);
  process.exit(1);
});

