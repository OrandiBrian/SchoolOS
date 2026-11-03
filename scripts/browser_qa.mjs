import { spawn } from "node:child_process";
import { mkdtemp, mkdir, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";

const chromePath =
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const baseUrl = process.env.SCHOOLOS_QA_URL || "http://127.0.0.1:8765";
const outputDir = path.resolve("docs/agent-work/schoolos/screenshots");
const profileDir = await mkdtemp(path.join(tmpdir(), "schoolos-chrome-"));
const port = 10000 + Math.floor(Math.random() * 20000);
let chrome;
let socket;
let sequence = 0;
const pending = new Map();
const loadWaiters = [];

await mkdir(outputDir, { recursive: true });

try {
  chrome = spawn(
    chromePath,
    [
      "--headless=new",
      "--disable-gpu",
      "--no-first-run",
      "--no-default-browser-check",
      `--remote-debugging-port=${port}`,
      `--user-data-dir=${profileDir}`,
      "about:blank",
    ],
    { stdio: ["ignore", "ignore", "pipe"] },
  );

  await waitForDebugger(port);
  const response = await fetch(`http://127.0.0.1:${port}/json/new?about:blank`, {
    method: "PUT",
  });
  const target = await response.json();
  socket = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => {
    socket.addEventListener("open", resolve, { once: true });
    socket.addEventListener("error", reject, { once: true });
  });
  socket.addEventListener("message", handleMessage);

  await send("Page.enable");
  await send("Runtime.enable");
  await send("Network.enable");

  await setViewport(1440, 1000);
  await navigate(`${baseUrl}/login/`);
  const loginLoaded = waitForNavigation();
  await evaluate(`
    document.querySelector('[name="username"]').value = "demo.head";
    document.querySelector('[name="password"]').value = ${JSON.stringify(process.env.DEMO_PASSWORD || "demo-password-123")};
    document.querySelector("form").requestSubmit();
  `);
  await loginLoaded;

  const dashboard = await inspectPage();
  assert(dashboard.path === "/", `Unexpected login destination: ${dashboard.path}`);
  assert(
    dashboard.text.includes("Good day") || dashboard.text.includes("School summary"),
    "Dashboard content missing after login.",
  );
  assert(dashboard.cssLoaded, "Compiled Tailwind stylesheet did not load.");
  assert(dashboard.htmxLoaded, "Vendored HTMX runtime did not load.");
  assert(!dashboard.overflow, "Desktop dashboard has document-level horizontal overflow.");
  await screenshot("desktop-dashboard.png");

  await navigate(`${baseUrl}/learners/`);
  const learners = await inspectPage();
  assert(learners.text.includes("Amina Otieno"), "Demo learner missing from list.");
  assert(!learners.overflow, "Desktop learner list has document-level horizontal overflow.");
  await screenshot("desktop-learners.png");

  await setViewport(390, 844);
  await reload();
  const mobileLearners = await inspectPage();
  if (mobileLearners.width !== 390) console.error(await evaluate(`JSON.stringify([...document.querySelectorAll("body *")].filter(e=>e.getBoundingClientRect().right>391).map(e=>({tag:e.tagName,cls:e.className,right:e.getBoundingClientRect().right})).slice(0,20))`));
  assert(mobileLearners.width === 390, "Mobile page expanded beyond its requested viewport.");
  assert(!mobileLearners.overflow, "Mobile learner list has document-level horizontal overflow.");
  await screenshot("mobile-learners.png");

  await navigate(`${baseUrl}/learners/new/`);
  const mobileForm = await inspectPage();
  assert(mobileForm.text.includes("Register a learner"), "Mobile registration form missing.");
  assert(!mobileForm.overflow, "Mobile registration form has document-level horizontal overflow.");
  await screenshot("mobile-registration.png");


  let attendanceResult = null;
  if (process.env.SCHOOLOS_ATTENDANCE_QA === "1") {
    await navigate(`${baseUrl}/attendance/?date=2026-10-16`);
    const href = await evaluate(`document.querySelector('a[href*="/2026-10-16/"]').href`);
    await navigate(href);
    assert((await inspectPage()).text.includes("Unmarked"), "Attendance roster is missing.");
    await evaluate(`document.querySelectorAll('select[name^="mark_"]').forEach(el => { el.value = 'present'; el.dispatchEvent(new Event('change', {bubbles:true})); });`);
    await send('Network.emulateNetworkConditions', {offline:true, latency:0, downloadThroughput:0, uploadThroughput:0});
    await evaluate(`document.querySelector('button[value="draft"]').click()`);
    await waitUntil(`document.getElementById('save-state').textContent.includes('fetch') || document.getElementById('save-state').textContent.includes('confirmed')`);
    assert(await evaluate(`document.querySelector('select[name^="mark_"]').value === 'present'`), 'Failed save lost attendance marks.');
    await send('Network.emulateNetworkConditions', {offline:false, latency:0, downloadThroughput:-1, uploadThroughput:-1});
    let loaded = waitForNavigation();
    await evaluate(`document.querySelector('button[value="draft"]').click()`);
    await loaded;
    assert((await inspectPage()).text.includes('Draft saved'), 'Draft save failed.');
    loaded = waitForNavigation();
    await evaluate(`document.querySelector('button[value="submit"]').click()`);
    await loaded;
    assert((await inspectPage()).text.includes('Submitted'), 'Submission failed.');
    assert((await inspectPage()).width === 390, 'Attendance expanded mobile viewport.');
    await screenshot('mobile-attendance.png');
    await evaluate(`const mark = document.querySelector('select[name^="mark_"]'); mark.value = 'absent'; mark.dispatchEvent(new Event('change',{bubbles:true})); document.querySelector('[name="reason"]').value = 'Fictional browser QA correction';`);
    loaded = waitForNavigation();
    await evaluate(`document.querySelector('button[value="correct"]').click()`);
    await loaded;
    assert(await evaluate(`document.body.textContent.includes('Fictional browser QA correction')`), 'Correction history missing.');
    await setViewport(1440,1000);
    await navigate(`${baseUrl}/attendance/?date=2026-10-16`);
    await screenshot('desktop-attendance.png');
    attendanceResult = {draft:true, submitted:true, correction:true, networkFailurePreservesMarks:true};
  }

  const result = {
    attendanceResult,
    baseUrl,
    viewportChecks: {
      desktopDashboard: dashboard,
      desktopLearners: learners,
      mobileLearners,
      mobileRegistration: mobileForm,
    },
    screenshots: [
      "desktop-dashboard.png",
      "desktop-learners.png",
      "mobile-learners.png",
      "mobile-registration.png",
    ],
  };
  console.log(JSON.stringify(result, null, 2));
} finally {
  if (socket) socket.close();
  if (chrome) {
    if (chrome.exitCode === null && chrome.signalCode === null) {
      const exited = new Promise(resolve => chrome.once("exit", resolve));
      chrome.kill("SIGTERM");
      await Promise.race([exited, new Promise(resolve => setTimeout(resolve, 2000))]);
    }
  }
  await rm(profileDir, { recursive: true, force: true });
}

function handleMessage(event) {
  const message = JSON.parse(event.data);
  if (message.id && pending.has(message.id)) {
    const { resolve, reject } = pending.get(message.id);
    pending.delete(message.id);
    if (message.error) reject(new Error(message.error.message));
    else resolve(message.result);
    return;
  }
  if (message.method === "Page.loadEventFired") {
    while (loadWaiters.length) loadWaiters.shift()();
  }
}

function send(method, params = {}) {
  const id = ++sequence;
  socket.send(JSON.stringify({ id, method, params }));
  return new Promise((resolve, reject) => pending.set(id, { resolve, reject }));
}

function waitForNavigation() {
  return new Promise((resolve) => loadWaiters.push(resolve));
}

async function navigate(url) {
  const loaded = waitForNavigation();
  await send("Page.navigate", { url });
  await loaded;
}

async function reload() {
  const loaded = waitForNavigation();
  await send("Page.reload", { ignoreCache: true });
  await loaded;
}

async function setViewport(width, height) {
  await send("Emulation.setDeviceMetricsOverride", {
    width,
    height,
    deviceScaleFactor: 1,
    mobile: width < 700,
  });
}

async function evaluate(expression) {
  const result = await send("Runtime.evaluate", {
    expression,
    awaitPromise: true,
    returnByValue: true,
  });
  if (result.exceptionDetails) {
    throw new Error(result.exceptionDetails.text || "Browser evaluation failed.");
  }
  return result.result?.value;
}

async function inspectPage() {
  return evaluate(`({
    path: window.location.pathname,
    text: document.body.innerText,
    width: window.innerWidth,
    height: window.innerHeight,
    scrollWidth: document.documentElement.scrollWidth,
    overflow: document.documentElement.scrollWidth > window.innerWidth + 1,
    cssLoaded: [...document.styleSheets].some(sheet => sheet.href?.includes("/static/css/app.css")),
    htmxLoaded: typeof window.htmx !== "undefined",
    title: document.title
  })`);
}

async function screenshot(filename) {
  const result = await send("Page.captureScreenshot", {
    format: "png",
    captureBeyondViewport: false,
  });
  await writeFile(
    path.join(outputDir, filename),
    Buffer.from(result.data, "base64"),
  );
}

async function waitForDebugger(debugPort) {
  const deadline = Date.now() + 15_000;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(
        `http://127.0.0.1:${debugPort}/json/version`,
      );
      if (response.ok) return;
    } catch {
      // Chrome is still starting.
    }
    await new Promise((resolve) => setTimeout(resolve, 150));
  }
  throw new Error("Headless Chrome did not expose its debugging endpoint.");
}

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

async function waitUntil(expression) {
  const deadline = Date.now() + 10000;
  while (Date.now() < deadline) {
    if (await evaluate(expression)) return;
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  throw new Error("Browser condition timed out: " + expression);
}
