import { expect, type Page, test } from "@playwright/test";

// Chart workspace: chart style, drawing a trend line (kept after reload), layouts, loading a
// setup from the side panel without a page change, full screen and Esc; Free stays at 1 chart.

const password = process.env.E2E_PASSWORD ?? "";
const proEmail = process.env.E2E_PRO_EMAIL ?? "pro@e2e.test";
const freeEmail = process.env.E2E_FREE_EMAIL ?? "free@e2e.test";

async function openWorkspace(page: Page, email: string) {
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/scanner$/);
  await page.locator(".scanner-page [data-testid=setup-row]").first().click();
  await expect(page.getByTestId("workspace")).toBeVisible();
  const chart = page.locator("[data-testid=panel][data-active=true] [data-testid=chart]");
  await expect(chart).toHaveAttribute("data-painted", "true");
  return chart;
}

test("workspace: style, draw, layout, side panel, full screen", async ({ page }) => {
  const chart = await openWorkspace(page, proEmail);
  const ws = page.getByTestId("workspace");

  // The forming candle (display only) is drawn and marked, when the current period has one:
  // none in the first minutes of an hour or while the market is closed.
  const forming = await page.evaluate(async () => {
    const m = window.location.pathname.match(/\/chart\/([A-Z_]+)\/(\w+)/);
    if (!m) return null;
    const r = await fetch(`/api/v1/charts/${m[1]}/${m[2]}`, { credentials: "include" });
    return (await r.json()).forming;
  });
  if (forming) {
    await expect(chart).toHaveAttribute("data-forming", "true");
    const label = page.getByTestId("forming-label");
    await expect(label).toBeVisible();
    await expect(label).toHaveAttribute(
      "title",
      "Forming candle: not final, never used for setups",
    );
  } else {
    test.info().annotations.push({ type: "note", description: "no forming candle right now" });
  }

  await page.getByRole("button", { name: /^Chart style/ }).click();
  await page.getByRole("menuitemradio", { name: "Line" }).click();
  await expect(chart).toHaveAttribute("data-style", "line");

  await page.getByRole("button", { name: "Trend line (T)" }).click();
  const box = await chart.boundingBox();
  if (!box) throw new Error("chart has no box");
  await page.mouse.click(box.x + box.width * 0.3, box.y + box.height * 0.35);
  await page.mouse.click(box.x + box.width * 0.6, box.y + box.height * 0.6);
  await expect(chart).toHaveAttribute("data-drawings", "1");
  await expect(page.getByRole("button", { name: "Select and move (V)" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );

  await page.reload();
  await expect(chart).toHaveAttribute("data-painted", "true");
  await expect(chart).toHaveAttribute("data-drawings", "1");
  await expect(chart).toHaveAttribute("data-style", "line");

  await page.getByRole("button", { name: /^Layout/ }).click();
  await page.getByRole("menuitemradio", { name: "2 side by side" }).click();
  await expect(page.getByTestId("panel")).toHaveCount(2);
  await expect(ws).toHaveAttribute("data-layout", "2h");

  // Loading a setup from the side panel changes the active chart, not the page.
  await page.evaluate(() => ((window as unknown as { __stay: number }).__stay = 1));
  const side = page.getByTestId("side-panel");
  await side.getByRole("tab", { name: "Setups" }).click();
  const active = page.locator("[data-testid=panel][data-active=true]");
  const before = (await active.getAttribute("data-instrument")) ?? "";
  const rows = side.getByTestId("setup-row");
  await expect(rows.first()).toBeVisible();
  const n = await rows.count();
  let picked = false;
  for (let i = 0; i < n; i++) {
    const row = rows.nth(i);
    if ((await row.textContent())?.includes(before.replace("_", "/"))) continue;
    await row.click();
    picked = true;
    break;
  }
  expect(picked, "a setup on another instrument").toBe(true);
  await expect(active).not.toHaveAttribute("data-instrument", before);
  await expect(page).toHaveURL(/\/chart\/[A-Z_]+\/(5m|15m|1h|4h|1d)\?setup=/);
  expect(await page.evaluate(() => (window as unknown as { __stay?: number }).__stay)).toBe(1);
  await expect(side.getByTestId("setup-panel")).toBeVisible();

  await page.getByTestId("fullscreen-button").click();
  await expect(ws).toHaveAttribute("data-fullscreen", "panel");
  await page.keyboard.press("Escape");
  await expect(ws).not.toHaveAttribute("data-fullscreen", /.+/);
});

test("Free: the workspace stays at one chart", async ({ page }) => {
  await openWorkspace(page, freeEmail);
  await page.getByRole("button", { name: /^Layout/ }).click();
  await expect(page.getByRole("menuitemradio", { name: /2 side by side/ })).toHaveAttribute(
    "aria-disabled",
    "true",
  );
  await expect(page.getByRole("menuitemradio", { name: /4 charts/ })).toHaveAttribute(
    "aria-disabled",
    "true",
  );
  await expect(page.getByTestId("panel")).toHaveCount(1);
});

test("Charts in the navigation opens the workspace on a chosen instrument", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("Email").fill(proEmail);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/scanner$/);
  await page
    .getByRole("navigation", { name: "Main" })
    .getByRole("link", { name: "Charts" })
    .click();
  await expect(page).toHaveURL(/\/chart\/[A-Z_]+\/(5m|15m|1h|4h|1d)$/);
  const panel = page.locator("[data-testid=panel][data-active=true]");
  await expect(panel.getByTestId("chart")).toHaveAttribute("data-painted", "true");
  await panel.getByLabel(/Instrument for chart 1/).selectOption("GBP_USD");
  await expect(panel).toHaveAttribute("data-instrument", "GBP_USD");
  await expect(page).toHaveURL(/\/chart\/GBP_USD\//);
  await expect(
    page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Charts" }),
  ).toHaveAttribute("aria-current", "page");

  // CR-006: one instrument in the side scanner shows its analysis; chosen patterns filter
  // the list (Any/All) and the chart; an analysis item scrolls the chart to it.
  const side = page.getByTestId("side-panel");
  if (!(await side.isVisible()))
    await page.getByRole("button", { name: /side panel|Show setups/ }).click();
  await side.getByRole("tab", { name: "Setups" }).click();
  await side.getByRole("button", { name: /^Filters/ }).click();
  await side.locator('select[name="instrument"]').selectOption("EUR_USD");
  await expect(side.getByTestId("analysis")).toBeVisible();
  const chips = side.getByTestId("pattern-filter");
  const anyReq = page.waitForRequest(
    (r) => r.url().includes("/api/v1/setups") && r.url().includes("pattern=fvg"),
  );
  await chips.locator('[data-pattern="fvg"]').click();
  await anyReq;
  await chips.locator('[data-pattern="bos"]').click();
  await expect(chips.locator('[data-pattern="bos"]')).toHaveAttribute("aria-pressed", "true");
  const chart = page.locator("[data-testid=panel][data-active=true] [data-testid=chart]");
  await expect(chart).toHaveAttribute("data-filtered", "");
  const allReq = page.waitForRequest(
    (r) => r.url().includes("/api/v1/setups") && r.url().includes("match=all"),
  );
  await chips.getByRole("button", { name: "All", exact: true }).click();
  await allReq;
  const item = side.getByTestId("analysis-item").first();
  if (await item.count()) {
    await item.click();
    await expect(chart).toHaveAttribute("data-focused", /\d{4}-\d{2}-\d{2}T/);
  }
});
