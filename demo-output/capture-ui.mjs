import { chromium } from "playwright";

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1600, height: 900 }, deviceScaleFactor: 1 });

await page.goto("http://host.docker.internal:8180", { waitUntil: "networkidle" });
await page.getByText("Governed extraction results").waitFor();

const captures = [
  ["overview", "Overview"],
  ["process", "Process claims"],
  ["evidence", "Field evidence"],
  ["hitl", "HITL review"],
  ["flow", "OCR & LLM flow"],
  ["tuning", "Tuning & governance"],
  ["submission", "Submission"],
];

for (const [name, tab] of captures) {
  await page.getByRole("tab", { name: tab }).click();
  await page.waitForTimeout(500);
  await page.screenshot({ path: `/output/${name}.png`, fullPage: false });
}

await browser.close();
