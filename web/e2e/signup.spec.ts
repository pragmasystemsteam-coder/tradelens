import { expect, type Page, test } from "@playwright/test";

// E2E-1 "Sign up and trial" (Detailed Design 7.7, task 3.2), run against the development
// stack of scripts/e2e.py: sign up from the landing page, open the link through the
// development-only button (no mailbox), sign in, see the Pro trial and a Pro feature.

const PASSWORD = "signup e2e passphrase";

function freshEmail(tag: string): string {
  return `qa-${tag}-${Date.now()}@e2e.test`;
}

async function signUp(page: Page, email: string) {
  await page.goto("/");
  await page.getByRole("link", { name: "Start free" }).first().click();
  await expect(page).toHaveURL(/\/signup$/);
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
  await page.getByRole("button", { name: "Swing" }).click();
  await expect(page.locator('select[name="timezone"]')).not.toHaveValue("");
  const create = page.getByRole("button", { name: "Create account" });
  await expect(create).toBeDisabled(); // terms not accepted yet
  await page.getByLabel(/I accept the/).check();
  await create.click();
  await expect(page.getByTestId("check-email")).toContainText(email);
}

async function signIn(page: Page, email: string) {
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
}

test("E2E-1: sign up, verify with the dev link, sign in, Pro trial is on", async ({ page }) => {
  const email = freshEmail("signup");
  await signUp(page, email);

  await page.getByRole("button", { name: "Dev: open the verification link" }).click();
  await expect(page).toHaveURL(/\/verify-email\?token=/);
  await expect(page.getByTestId("trial-started")).toContainText(
    "Your 15-day Pro trial has started",
  );
  await page.getByTestId("verify-done").getByRole("link", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/login$/);

  await signIn(page, email);
  await expect(page).toHaveURL(/\/scanner$/);
  await expect(page.getByTestId("plan-chip")).toContainText(/1[45] days left/);
  // Pro features: commodities open and the gold chart is not locked.
  await expect(page.getByTestId("asset-metal")).toBeEnabled();
  await page.goto("/chart/XAU_USD/1h");
  await expect(page.locator(".chart-area [data-testid=chart]")).toBeVisible();
  await expect(page.getByTestId("chart-locked")).toHaveCount(0);

  await page.goto("/account/profile");
  await expect(page.getByTestId("trial-banner")).toContainText("Pro trial ends");
  await expect(page.locator('select[name="timezone"]')).not.toHaveValue("");
});

test("unverified sign-in offers a new link", async ({ page }) => {
  const email = freshEmail("unverified");
  await signUp(page, email);
  await signIn(page, email);
  await expect(page.locator("#login-error")).toContainText("Verify your email first");
  await page.getByRole("button", { name: "Send the verification link again" }).click();
  await expect(page.getByTestId("unverified")).toContainText("We sent a new link");
});

test("a used verification link offers a new one", async ({ page }) => {
  await page.goto("/verify-email?token=not-a-real-token");
  await expect(page.getByRole("heading", { level: 1 })).toContainText(
    "expired or was already used",
  );
  await expect(page.getByRole("button", { name: "Send a new link" })).toBeVisible();
});

test("forgot password answers the same for any email", async ({ page }) => {
  await page.goto("/login");
  await page.getByRole("link", { name: "Forgot your password?" }).click();
  await page.getByLabel("Email").fill(freshEmail("nobody"));
  await page.getByRole("button", { name: "Send the link" }).click();
  await expect(page.getByTestId("forgot-sent")).toContainText("If an account uses");
});
