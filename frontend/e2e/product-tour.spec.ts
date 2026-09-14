import { test, expect, loginWithFixture } from './fixtures';

test('product tour supports next, back, skip, finish, and restart', async ({ page, fatalCheck }) => {
  await loginWithFixture(page);

  await page.getByRole('button', { name: 'Help and product tour' }).click();
  await page.getByRole('button', { name: 'Take a Tour' }).click();
  await expect(page.getByRole('dialog', { name: 'Fortress product tour' })).toBeVisible();
  await expect(page.getByText('Your Fortress overview')).toBeVisible();

  await page.getByRole('button', { name: 'Next' }).click();
  await expect(page.getByText('Find and inspect stock signals')).toBeVisible();
  await page.getByRole('button', { name: 'Back' }).click();
  await expect(page.getByText('Your Fortress overview')).toBeVisible();
  await page.getByRole('button', { name: 'Skip tour' }).click();
  await expect(page.getByRole('dialog', { name: 'Fortress product tour' })).toBeHidden();

  await expect.poll(() => page.evaluate(() => localStorage.getItem('fortress-product-tour-complete'))).toBe('true');

  await page.getByRole('button', { name: 'Help and product tour' }).click();
  await page.getByRole('button', { name: 'Restart Tour' }).click();
  for (let step = 0; step < 9; step += 1) {
    await page.getByRole('button', { name: 'Next' }).click();
  }
  await page.getByRole('button', { name: 'Finish' }).click();
  await expect(page.getByRole('dialog', { name: 'Fortress product tour' })).toBeHidden();
  await expect.poll(() => page.evaluate(() => localStorage.getItem('fortress-product-tour-complete'))).toBe('true');

  await page.reload();
  await expect(page.getByRole('dialog', { name: 'Fortress product tour' })).toBeHidden();
  await page.getByRole('button', { name: 'Help and product tour' }).click();
  await expect(page.getByRole('button', { name: 'Restart Tour' })).toBeVisible();
  fatalCheck();
});

test('product tour is keyboard-dismissible and tolerates a missing target', async ({ page }) => {
  await loginWithFixture(page);
  await page.getByRole('button', { name: 'Help and product tour' }).click();
  await page.getByRole('button', { name: 'Take a Tour' }).click();

  await page.evaluate(() => document.querySelector('[data-tour="screener"]')?.remove());
  await page.getByRole('button', { name: 'Next' }).click();
  await expect(page.getByText('Find and inspect stock signals')).toBeVisible();
  await page.getByRole('button', { name: 'Help and product tour' }).focus();
  await page.keyboard.press('Tab');
  await expect(page.getByRole('button', { name: 'Skip tour' })).toBeFocused();
  await page.keyboard.press('Escape');
  await expect(page.getByRole('dialog', { name: 'Fortress product tour' })).toBeHidden();
  await expect(page.getByRole('button', { name: 'Help and product tour' })).toBeFocused();
});
