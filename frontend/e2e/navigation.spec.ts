import AxeBuilder from '@axe-core/playwright';
import { test, expect, loginWithFixture } from './fixtures';

const destinations = [
  ['Dashboard', '/dashboard', /Dashboard/],
  ['Stock Screener', '/screener', /Stock Screener/],
  ['MF Lab', '/mf-lab', /Mutual Fund Lab/],
  ['REITs & InvITs', '/reit-invits', /REITs & InvITs/],
  ['US Investing', '/us-investing', /US Investing/],
  ['Orders', '/orders', /Orders/],
  ['Picks Tracker', '/picks', /Picks Tracker/],
  ['Paper Trading', '/paper-trading', /Paper Trading/],
  ['Commodities', '/commodities', /Commodities/],
  ['Options', '/options', /Options/],
  ['Scan History', '/history', /Scan History/],
  ['Profile', '/profile', /Profile & Settings/],
] as const;

test('every first-class internal navigation link resolves and renders', async ({ page, fatalCheck }) => {
  await loginWithFixture(page);
  for (const [label, path, heading] of destinations) {
    await page.getByRole('link', { name: new RegExp(label) }).click();
    await expect(page).toHaveURL(new RegExp(`${path.replace('/', '\\/')}(?:\\?.*)?$`));
    await expect(page.getByRole('heading', { name: heading })).toBeVisible();
    await expect(page.locator('body')).not.toContainText(/404|Application error|Unhandled Runtime Error/i);
  }
  fatalCheck();
});

test('dashboard structure and key authenticated pages pass accessibility sanity', async ({ page }) => {
  await loginWithFixture(page);
  for (const path of ['/dashboard', '/screener', '/history', '/paper-trading']) {
    await page.goto(path);
    await expect(page.locator('.page-title')).toBeVisible();
    const result = await new AxeBuilder({ page }).analyze();
    expect(result.violations.filter(v => ['serious', 'critical'].includes(v.impact || '')), path).toEqual([]);
  }
});
