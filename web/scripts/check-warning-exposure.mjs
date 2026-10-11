// Browser UI regression with explicit API fixtures, not a live avoidance test.
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
const require = createRequire(import.meta.url);
const {chromium} = require(process.env.ORION_PLAYWRIGHT || 'playwright');
const browser = await chromium.launch({channel:'msedge',headless:true});
try {
  const page = await browser.newPage();
  let phase='exposed';
  const mile=1609.344;
  const exposed={id:'exposed',label:'fastest',risk_score:40,risk_band:'caution',distance_m:35.1*mile,duration_s:3600,
    geometry:{type:'LineString',coordinates:[[-93.37,30.23],[-92.02,30.22]]},
    risk_breakdown:{flood_exposure:35,low_lying:0,gauge_proximity:0,approach_margin:5,total:40},
    warning_exposure_m:35.1*mile,warning_exposure_percent:100,warning_severity_m:{severe:15*mile,moderate:20.1*mile},
    hazard_exposure_m:0,initial_warning_exit_m:10*mile,warning_reentries:1,warning_avoidance_achieved:false,
    flagged_segments:[{geometry:{type:'LineString',coordinates:[[-93.37,30.23],[-92.02,30.22]]},length_m:35.1*mile,source:'nws',evidence:'warning_area',event:'Flood Warning',severity:'moderate',flood_zone_id:'fixture-1'},
      {geometry:{type:'LineString',coordinates:[[-93.2,30.23],[-92.9,30.22]]},length_m:15*mile,source:'nws',evidence:'warning_area',event:'Flood Warning',severity:'severe',flood_zone_id:'fixture-2'}],
    warnings:[],elevation_profile:[],avoidance_verified:false,avoidance_requested:true};
  const clear={...exposed,id:'clear',label:'alternative',risk_score:0,risk_band:'safe',distance_m:45*mile,duration_s:4500,
    warning_exposure_m:0,warning_exposure_percent:0,warning_severity_m:{},warning_reentries:0,initial_warning_exit_m:0,
    warning_avoidance_achieved:true,flagged_segments:[],avoidance_verified:true};
  await page.route('**/api/**',async route=>{
    const url=new URL(route.request().url());
    if(url.pathname.endsWith('/geocode')) return route.fulfill({json:[{name:url.searchParams.get('q'),lat:30.23,lon:-93.37,region:'Louisiana'}]});
    if(url.pathname.endsWith('/routes')) return route.fulfill({json:{request_id:'00000000-0000-0000-0000-000000000001',generated_at:new Date().toISOString(),
      routes:phase==='clear'?[clear,exposed]:[exposed],recommended_id:phase==='clear'?'clear':null,
      warnings:phase==='clear'?[]:['No lower-exposure route found. Travel safety cannot be confirmed.'],snap_proposals:[],accepted_snaps:[]}});
    return route.fulfill({json:[]});
  });
  await page.goto(process.env.ORION_TEST_URL || 'http://127.0.0.1:3003');
  const fields=page.getByPlaceholder('Search an address or place');
  for(const [i,name] of ['City of Sulphur','Lafayette'].entries()){
    await fields.nth(i).fill(name);
    await page.getByRole('button',{name,exact:true}).click();
  }
  await page.getByRole('button',{name:'Find the safest route'}).click();
  await page.getByText('No lower-exposure route found. Travel safety cannot be confirmed.',{exact:true}).waitFor();
  assert.equal(await page.getByText(/50\.1 mi/).count(),0);
  await page.getByText(/35\.1 mi inside NWS warning areas \(100\.0%/).waitFor();
  assert.equal(await page.getByText('Recommended',{exact:true}).count(),0);
  phase='clear';
  await page.getByRole('button',{name:'Find the safest route'}).click();
  await page.getByText('Complete avoidance of current NWS warning polygons verified. Road safety is not guaranteed.',{exact:true}).waitFor();
  const selected=page.locator('button[aria-pressed="true"]').filter({hasText:'Alternative'});
  assert.equal(await selected.count(),1);
  console.log('Warning exposure browser fixtures passed: unique distance, severity, cautious language, zero-overlap selection. No live avoidance claim.');
} finally { await browser.close(); }
