// Run with node scripts/check-route-labels.cjs after installing web dependencies.
const fs = require('node:fs');
const ts = require('typescript');
const assert = require('node:assert/strict');
for (const extension of ['.ts', '.tsx']) {
  require.extensions[extension] = (module, filename) => module._compile(
    ts.transpileModule(fs.readFileSync(filename, 'utf8'), {compilerOptions: {
      module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true,
    }, fileName: filename}).outputText, filename);
}
const React = require('react');
const {renderToStaticMarkup} = require('react-dom/server');
const RouteCard = require('../components/RouteCard.tsx').default;
const route = {id:'test',label:'fastest',risk_score:80,risk_band:'dangerous',distance_m:135000,duration_s:6000,
  geometry:{type:'LineString',coordinates:[[-93,30,10],[-92,30,10]]},
  risk_breakdown:{flood_exposure:50,low_lying:25,gauge_proximity:0,approach_margin:5,total:80},
  flagged_segments:[{geometry:{type:'LineString',coordinates:[[-93,30],[-92,30]]},length_m:1000,source:'nws',evidence:'warning_area',event:'Flood Warning',severity:'severe',flood_zone_id:'nws-test'}],
  warnings:[],elevation_profile:[],avoidance_verified:false,avoidance_requested:false};
const html = renderToStaticMarkup(React.createElement(RouteCard,{route,selected:true,recommended:true,quickest:6000,onSelect:()=>{}}));
assert.ok(!html.includes('Recommended'));
assert.ok(!html.includes('through active floodwater'));
assert.ok(!html.includes('Crosses active floodwater'));
assert.ok(html.includes('not confirmed floodwater'));
assert.ok(html.includes('Information only'));
console.log('Route card regression passed: Dangerous is not recommended, NWS overlap is not confirmed floodwater.');

const mile = 1609.344;
const exposureRoute = {...route, distance_m:35.1*mile, risk_band:'caution',risk_score:35,
  warning_exposure_m:35.1*mile, warning_exposure_percent:100,
  warning_severity_m:{severe:15*mile,moderate:20.1*mile},
  flagged_segments:[{...route.flagged_segments[0],length_m:35.1*mile},{...route.flagged_segments[0],length_m:15*mile}]};
const exposureHtml = renderToStaticMarkup(React.createElement(RouteCard,{route:exposureRoute,selected:false,recommended:true,quickest:6000,onSelect:()=>{}}));
assert.ok(exposureHtml.includes('35.1 mi'));
assert.ok(!exposureHtml.includes('50.1 mi'));
assert.ok(exposureHtml.includes('100.0%'));
assert.ok(exposureHtml.includes('overlaps counted once'));
assert.ok(exposureHtml.includes('severe') && exposureHtml.includes('moderate'));
assert.ok(exposureHtml.includes('Lower exposure') && !exposureHtml.includes('Recommended'));
const clearHtml = renderToStaticMarkup(React.createElement(RouteCard,{route:{...exposureRoute,warning_exposure_m:0,warning_avoidance_achieved:true,warning_severity_m:{},flagged_segments:[]},selected:false,recommended:true,quickest:6000,onSelect:()=>{}}));
assert.ok(clearHtml.includes('Road safety is not guaranteed'));
console.log('Unique exposure regression passed: 35.1 miles, 100%, severity breakdown, no overlapping 50.1-mile sum.');
