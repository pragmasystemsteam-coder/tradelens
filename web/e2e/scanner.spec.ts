import { expect, type Page, test } from "@playwright/test";

import { METHODOLOGY } from "../src/lib/methodology";

// E2E-2 "Scanner to chart" (Detailed Design 7.7, task 2.9) plus the review-focus checks:
// reconnect refetches, disclaimer and footer, TradingView attribution, chart painted
// under 2 s, methodology anchors, Free locks and the 375 px layout.

const password = process.env.E2E_PASSWORD ?? "";
const proEmail = process.env.E2E_PRO_EMAIL ?? "pro@e2e.test";
const freeEmail = process.env.E2E_FREE_EMAIL ?? "free@e2e.test";

async function signIn(page: Page, email: string) {
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/scanner$/);
  await expect(page.getByTestId("scanner-list")).toBeVisible();
}

async function tipAnchors(page: Page): Promise<string[]> {
  return page
    .locator("a.tip")
    .evaluateAll((els) => els.map((e) => e.getAttribute("data-anchor") ?? ""));
}

test("E2E-2: filter Bullish 1H score 60+, open the first row, see the zone and disclaimer", async ({
  page,
}) => {
  await signIn(page, proEmail);
  await page.getByRole("tab", { name: "Bullish" }).click();
  await page.locator('select[name="timeframe"]').selectOption("1h");
  const filtered = page.waitForResponse((r) => r.url().includes("min_score=60") && r.ok());
  await page.locator('input[name="min_score"]').fill("60");
  await filtered;

  const rows = page.getByTestId("setup-row");
  await expect(rows.first()).toBeVisible();
  const scores = await page.getByTestId("row-combined").allInnerTexts();
  expect(scores.length).toBeGreaterThan(0);
  for (const s of scores) expect(Number(s)).toBeGreaterThanOrEqual(60);
  await expect(rows.first()).toContainText("Bullish");

  // Disclaimer directly under the filters (FR-MTF-10).
  const disclaimer = page.locator(".scanner-page > [data-testid=disclaimer]");
  await expect(disclaimer).toContainText("not a probability of profit");

  const id = await rows.first().getAttribute("data-setup-id");
  const started = Date.now();
  await rows.first().click();
  await expect(page).toHaveURL(new RegExp(`/chart/[A-Z_]+/1h\\?setup=${id}`));
  const chart = page.locator(".chart-area [data-testid=chart]");
  await expect(chart).toHaveAttribute("data-painted", "true");
  expect(Date.now() - started, "chart painted under 2 s (NFR-03)").toBeLessThan(2000);

  await expect(chart).toHaveAttribute("data-highlighted-zone", /[0-9a-f]{32}/);
  const panel = page.getByTestId("setup-panel");
  await expect(panel.getByTestId("zone-highlight")).toBeVisible();
  await expect(panel.getByTestId("disclaimer")).toBeVisible();
  // D-ATTR: one attribution, the Lightweight Charts logo inside the chart (links to TradingView).
  await expect(chart.locator('a[href*="tradingview.com"]')).toBeVisible();
  await expect(page.getByText("Charts by TradingView", { exact: true })).toHaveCount(0);
  await expect(page.locator(".chart-area [data-testid=trend-strip] li.trend")).toHaveCount(5);

  const footer = page.getByTestId("footer");
  for (const name of ["Terms", "Privacy", "Methodology"]) {
    await expect(footer.getByRole("link", { name })).toBeVisible();
  }
  await expect(footer).toContainText("Analytics only");
});

test("test_reconnect_refetches", async ({ page }) => {
  let attempts = 0;
  await page.route("**/api/v1/stream**", (route) =>
    attempts++ < 1 ? route.abort() : route.continue(),
  );
  const firstLoad = page.waitForRequest((r) => r.url().includes("/api/v1/setups"));
  await page.goto("/login");
  await page.getByLabel("Email").fill(proEmail);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await firstLoad;
  // The first stream attempt failed; when EventSource reconnects, the scanner refetches.
  const refetch = await page.waitForRequest((r) => r.url().includes("/api/v1/setups"), {
    timeout: 15_000,
  });
  expect(refetch.url()).toContain("/api/v1/setups");
  expect(attempts).toBeGreaterThanOrEqual(2);
  await expect(page.getByTestId("reconnecting")).toHaveCount(0);
});

test("test_methodology_anchors_exist", async ({ page }) => {
  await signIn(page, proEmail);
  const anchors = new Set(await tipAnchors(page));
  await page.locator(".scanner-page [data-testid=setup-row]").first().click();
  await expect(page.getByTestId("setup-panel")).toBeVisible();
  for (const a of await tipAnchors(page)) anchors.add(a);
  expect(anchors.size).toBeGreaterThan(5);
  await page.goto("/methodology");
  for (const id of new Set([...anchors, ...METHODOLOGY.map((m) => m.id)])) {
    await expect(page.locator(`section[id="${id}"]`), `methodology anchor #${id}`).toHaveCount(1);
  }
});

test("Free: commodities locked, C factors and higher-timeframe zones show Pro", async ({
  page,
}) => {
  await signIn(page, freeEmail);
  await expect(page.getByTestId("asset-metal")).toBeDisabled();
  await expect(page.getByTestId("asset-metal").getByTestId("lock-badge")).toBeVisible();
  await page.getByTestId("setup-row").first().click();
  await expect(page.getByTestId("factors")).toContainText("Pro");
  await expect(page.getByText("shows higher-timeframe zones")).toBeVisible();
  await page.goto("/chart/XAU_USD/1h");
  await expect(page.getByTestId("chart-locked")).toBeVisible();
});

test("usable at 375 px", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await signIn(page, freeEmail);
  await expect(page.getByTestId("bottom-tabs")).toBeVisible();
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - window.innerWidth,
  );
  expect(overflow, "no horizontal scroll at 375 px").toBeLessThanOrEqual(0);
  await page.getByTestId("setup-row").first().click();
  await expect(page.locator(".chart-area [data-testid=chart]")).toHaveAttribute(
    "data-painted",
    "true",
  );
  const chartOverflow = await page.evaluate(
    () => document.documentElement.scrollWidth - window.innerWidth,
  );
  expect(chartOverflow, "no horizontal scroll on the chart at 375 px").toBeLessThanOrEqual(0);
});
