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
