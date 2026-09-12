import { test, expect } from './fixtures';

test('options workspace has honest empty state and legacy scanner boundary', async ({ page, fatalCheck }) => {
  await page.goto('/options');
  await expect(page.getByRole('heading', { name: '⚡ Options' })).toBeVisible();
  await expect(page.getByText('No options chain loaded yet.')).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Legacy Strategy Scanner' })).toBeVisible();
  await expect(page.getByText(/not a recommendation or risk model/)).toBeVisible();
  await expect(page.getByText('No prior options snapshots available.')).toBeVisible();
  fatalCheck();
});
