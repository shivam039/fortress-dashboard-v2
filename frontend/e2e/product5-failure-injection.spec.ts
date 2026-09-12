import { test, expect, loginWithFixture } from './fixtures';

test('Scan History API 500 shows a clear retry state', async ({ page, fatalCheck }) => {
  await page.route('**/api/history/timestamps', async route => {
    await route.fulfill({ status: 500, contentType: 'application/json', body: JSON.stringify({ detail: 'fixture failure' }) });
  });
  await loginWithFixture(page);
  await page.getByRole('link', { name: /Scan History/ }).click();
  await expect(page.getByText(/couldn't be loaded/i)).toBeVisible();
  await expect(page.getByRole('button', { name: /Retry/ })).toBeVisible();
  await expect(page.getByText(/fixture failure/)).toBeVisible();
  fatalCheck();
});
