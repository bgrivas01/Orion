import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
const require = createRequire(import.meta.url);
const {chromium} = require(process.env.ORION_PLAYWRIGHT || 'playwright');
const browser = await chromium.launch({channel:'msedge',headless:true});
try {
  const page = await browser.newPage();
  const calls = [];
  const original = {lat:30.21,lon:-93.14};
  const proposed = {lat:30.2105,lon:-93.14};
  await page.route('**/api/**',async route=>{
    const url = new URL(route.request().url());
    if (url.pathname.endsWith('/geocode')) return route.fulfill({json:[{name:url.searchParams.get('q'),...original,region:'Louisiana'}]});
    if (url.pathname.endsWith('/routes')) {
      const body=route.request().postDataJSON(); calls.push(body);
      return route.fulfill({json:{request_id:'00000000-0000-0000-0000-000000000001',generated_at:new Date().toISOString(),routes:[],warnings:[],
        snap_proposals:body.accepted_snaps?.length ? [] : [{endpoint:'destination',original,proposed,distance_m:55.6,confirmation_required:true,access_verified:false}],accepted_snaps:body.accepted_snaps??[]}});
    }
    return route.fulfill({json:[]});
  });
  await page.goto(process.env.ORION_TEST_URL || 'http://127.0.0.1:3003');
  const fields = page.getByPlaceholder('Search an address or place');
  await fields.nth(0).fill('Sulphur High School');
  await page.getByRole('button',{name:'Sulphur High School',exact:true}).click();
  await fields.nth(1).fill('Chennault Airport');
  await page.getByRole('button',{name:'Chennault Airport',exact:true}).click();
  await page.getByRole('button',{name:'Find the safest route'}).click();
  const panel=page.getByRole('region',{name:'Confirm nearby road'});
  await panel.waitFor();
  assert.equal(calls.length,1);
  assert.equal(await panel.getByRole('button',{name:'Accept',exact:true}).isEnabled(),false);
  await panel.getByRole('button',{name:'Cancel',exact:true}).click();
  assert.equal(calls.length,1);
  assert.equal(await panel.count(),0);
  await page.getByRole('button',{name:'Find the safest route'}).click();
  await panel.waitFor();
  await panel.getByRole('checkbox').check();
  await panel.getByRole('button',{name:'Accept',exact:true}).click();
  await panel.waitFor({state:'hidden'});
  assert.equal(calls.length,3);
  assert.deepEqual(calls[2].destination,proposed);
  assert.deepEqual(calls[2].accepted_snaps[0].original,original);
  assert.equal(calls[2].accepted_snaps[0].public_access_confirmed,true);
  assert.equal(await fields.nth(1).inputValue(),'Chennault Airport');
  await fields.nth(1).fill('Different entrance');
  assert.equal(await page.getByRole('button',{name:'Find the safest route'}).isEnabled(),false);
  console.log('Snapping browser checks passed: confirmation gate, Cancel, Accept, preserved original, selection invalidation.');
} finally { await browser.close(); }
