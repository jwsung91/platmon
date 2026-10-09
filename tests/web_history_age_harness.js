const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
let now = 0;
const elements = {}, intervals = [];
const context = vm.createContext({AbortController, performance: {now: () => now}, console,
  document: {visibilityState: 'visible', getElementById: id => elements[id] ||= {innerHTML:'',textContent:''},
    querySelectorAll: () => [], addEventListener() {}},
  setInterval: fn => intervals.push(fn), setTimeout() {}, clearTimeout() {},
  fetch: async url => url.startsWith('api/history') ? {ok:true, status:200, json:async() => ({retention_s:600,
    series:{'memory/used_bytes':[[1,2000,1024]]}})} : {ok:false,status:404}});
(async () => {
  vm.runInContext(fs.readFileSync(process.argv[2], 'utf8').match(/<script>([\s\S]*?)<\/script>/)[1], context);
  await new Promise(setImmediate);
  assert(elements.hist.innerHTML.includes('latest point 2 s ago'));
  now = 4000; intervals.forEach(fn => fn()); await new Promise(setImmediate);
  assert(elements.hist.innerHTML.includes('latest point 6 s ago'), elements.hist.innerHTML);
  context.document.visibilityState = 'hidden';
  now = 5000; intervals.forEach(fn => fn()); await new Promise(setImmediate);
  assert(elements.hist.innerHTML.includes('latest point 6 s ago'), 'hidden tabs skip graph rendering');
  context.document.visibilityState = 'visible';
  now = 6000; intervals.forEach(fn => fn()); await new Promise(setImmediate);
  assert(elements.hist.innerHTML.includes('latest point 8 s ago'));
  console.log('cached history age advances without another response: passed');
})().catch(e => {console.error(e); process.exitCode = 1;});
