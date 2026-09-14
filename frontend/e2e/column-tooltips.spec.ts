import { expect, loginWithFixture, test } from './fixtures';

test('options columns expose keyboard and tap help even in the empty state', async ({ page }) => {
  await loginWithFixture(page);
  await page.goto('/options');
  const help = page.getByRole('button', { name: 'About Strike column' });
  await expect(help).toBeVisible();
  await help.focus();
  await expect(page.getByRole('tooltip')).toContainText('exercise price');
  await page.locator('h1').click();
  await help.click();
  await expect(page.getByRole('tooltip')).toBeVisible();
  await expect(page.getByRole('link', { name: 'Learn more' })).toHaveAttribute('href', '/glossary#strike');
  await page.getByRole('link', { name: 'Learn more' }).focus();
  await expect(page.getByRole('tooltip')).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.getByRole('tooltip')).toBeHidden();
});

test('scan history result columns use canonical help', async ({ page }) => {
  await loginWithFixture(page);
  await page.goto('/history');
  await page.getByText('Nifty 50').click();
  await expect(page.getByRole('button', { name: 'About Symbol column' }).first()).toBeVisible();
  await expect(page.getByRole('button', { name: 'About Fortress Score column' }).first()).toBeVisible();
});

test('column help does not sort the table, while the label still does', async ({ page }) => {
  await loginWithFixture(page);
  await page.goto('/options');
  const header = page.locator('th').filter({ hasText: 'Strike' }).first();
  const help = header.getByRole('button', { name: 'About Strike column' });
  await help.click();
  await expect(header).not.toHaveClass(/sorted/);
  await header.getByRole('button', { name: /Sort by Strike/ }).click();
  await expect(header).toHaveClass(/sorted/);
});
