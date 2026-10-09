// Runs the <script> of frontends/web/index.html with a stub DOM, fake clocks and timers and scripted fetch
// results, and prints one JSON line per step. Used by tests/test_web.py.
//   node tests/web_harness.js frontends/web/index.html
const fs = require('fs');
const code = fs.readFileSync(process.argv[2], 'utf8').match(/<script>([\s\S]*?)<\/script>/)[1];

const els = {};
const el = id => (els[id] ||= {innerHTML: '', textContent: '', hidden: false, lastElementChild: null});
const listeners = [];
global.document = {getElementById: el, querySelectorAll: () => [], visibilityState: 'visible',
  addEventListener: (type, fn) => type === 'visibilitychange' && listeners.push(fn)};
const tabReturns = () => { document.visibilityState = 'visible'; listeners.forEach(fn => fn()); };

const timers = [];  // fake setTimeout: the test fires them by delay
global.setTimeout = (fn, ms) => timers.push({fn, ms});
global.clearTimeout = id => { if (timers[id - 1]) timers[id - 1].fn = null; };
const fire = ms => { const t = timers.find(t => t.fn && t.ms === ms); if (t) { const fn = t.fn; t.fn = null; fn(); } };
const intervals = [];  // fake setInterval: the age display timer
global.setInterval = (fn, ms) => intervals.push({fn, ms});
const tickAge = () => intervals.forEach(t => t.fn());
let now = 0;  // ms, for both browser clocks
Date.now = () => now;
Object.defineProperty(globalThis, 'performance', {value: {now: () => now}, configurable: true});

const SNAP = {platform: 'Linux', model: 'Test', uptime: 60, power_mode: null, system: {os: 'Test OS'},
  cpu: [{id: 0, usage: 1, freq: null}], gpu: null, memory: {total: 8, used: 2, swap_total: 0, swap_used: 0},
  disk: {total: 10, used: 5}, temperature: {}, power: {}, fans: []};
const meta = (id, sequence, data_age_ms) => ({...SNAP, schema_version: 1, collectors: {core: {state: 'ok', reason: null}},
  sample: {instance_id: id, sequence, data_age_ms, age_ms: data_age_ms - 250, duration_ms: 250}});
const reply = (status, body) => ({ok: status >= 200 && status < 300, status,
  statusText: status === 503 ? 'Service Unavailable' : 'OK', json: () => Promise.resolve(body)});
const ok = body => () => Promise.resolve(reply(200, body));
const hang = signal => new Promise((_, reject) => signal && signal.addEventListener('abort',
  () => reject(Object.assign(new Error('aborted'), {name: 'AbortError'}))));
let release;  // answers a held request when the test says so; it ignores abort, like an answer already on its way
const held = body => () => new Promise(resolve => { release = () => resolve(reply(200, body)); });

const answers = [];  // what the next requests get, in order
let fetches = 0;
const obsAnswers = [];  // what /api/observations requests get, in order; a 404 (older server) when none is queued
let obsFetches = 0;
global.fetch = (url, opts) => {
  if (url === 'api/observations') { obsFetches++; return (obsAnswers.shift() || (() => Promise.resolve(reply(404, {}))))(); }
  fetches++; return answers.shift()((opts || {}).signal);
};
const settle = async () => { for (let i = 0; i < 4; i++) await new Promise(resolve => setImmediate(resolve)); };
const report = step => console.log(JSON.stringify({
  step, err: el('err').textContent, age: el('age').textContent, shows_data: el('cpu').innerHTML.includes('CPU0'),
  refresh_scheduled: timers.filter(t => t.fn && (t.ms === 1000 || t.ms === 0)).length,  // next update, normal or at once
  age_timers: intervals.length, fetches, cpu: el('cpu').innerHTML, coll: el('coll').textContent,
  net: el('net').innerHTML, dio: el('dio').innerHTML, sto: el('sto').innerHTML, obs_fetches: obsFetches,
}));
const next = async (answer, step) => { answers.push(answer); now += 1000; fire(1000); await settle(); if (step) report(step); };

(async () => {
  // an older server without sample metadata, through every kind of failure; its observations answer once, then 404
  obsAnswers.push(ok({schema_version: 1, groups: {storage: {state: 'stale', interval_ms: 30000,
    observation: {id: 3, data_age_ms: 95000, stale: true}, data: {
      filesystems: [{device: 'nvme0n1p1', major: 259, minor: 1, fstype: 'ext4', source: '/dev/nvme0n1p1', total_bytes: 4 * 2 ** 30,
                     used_bytes: 2 ** 30, available_bytes: 3 * 2 ** 30, mount_points: [{path: '/mnt/<b>x</b>', read_only: true},
                     ...Array.from({length: 60}, (_, i) => ({path: '/bind/' + i, read_only: false}))]},
                    {device: null, major: 0, minor: 40, fstype: 'btrfs', source: '/dev/sdb', total_bytes: null,
                     used_bytes: null, available_bytes: null, mount_points: [{path: '/data', read_only: false}]}],
      partitions: [{name: 'nvme0n1p1', disk: 'nvme0n1', size_bytes: 4 * 2 ** 30, mount_points: ['/']},
                   {name: 'nvme0n1p2', disk: 'nvme0n1', size_bytes: 2 ** 27, mount_points: []}]}}}}));
  answers.push(ok(SNAP));
  eval(code);  // the page script ends with tick()
  await settle(); report('ok');
  await next(() => Promise.resolve(reply(503, {error: 'no current data'})), '503');
  await next(hang);
  now += 5000; fire(5000); await settle(); report('hang');  // request timeout
  await next(() => Promise.reject(new TypeError('Failed to fetch')), 'down');
  await next(() => Promise.resolve({ok: true, status: 200, statusText: 'OK',
    json: () => Promise.reject(new SyntaxError("Unexpected token '<'"))}), 'garbage');
  await next(ok(SNAP), 'recovered');

  // a server with sample metadata: the age is the sample's, not the time since the last answer
  await next(ok(meta('a', 5, 2000)), 'sample');
  await next(ok(meta('a', 5, 3000)), 'same_sample');  // polled again, same sample: no reset to 0
  await next(() => Promise.resolve(reply(503, {error: 'no current data', sample: {sequence: 5}})), 'sample_503');
  await next(hang);
  now += 2000; tickAge(); report('sample_hang_waiting');  // the age moves while the request hangs
  now += 3000; fire(5000); await settle(); report('sample_hang');
  await next(ok({...SNAP, schema_version: 1, sample: {instance_id: 'a', sequence: 'x', data_age_ms: null}}), 'bad_metadata');
  await next(ok(meta('b', 1, 100)), 'new_instance');  // restarted server: new instance, sequence 1
  await next(ok(meta('b', 2, 1400)), 'new_sequence');

  // back to the tab: no answer is trusted until a new one arrives, and never two requests at once
  now += 600000;  // browser asleep for 10 min, the refresh timer did not run
  answers.push(held(meta('b', 600, 300)));
  tabReturns(); report('tab_return_checking');
  release(); await settle(); report('tab_return_verified');
  // a request started before the tab was hidden, answered after it came back: its 300 ms is 10 min old
  await next(held(meta('b', 601, 300)));
  now += 600000;
  tabReturns(); report('tab_return_while_requesting');  // that request is cancelled, not trusted
  release(); await settle(); report('old_answer_ignored');  // arrives anyway: dropped, a new request is due
  answers.push(ok(meta('b', 601, 900)));  // the new request may well get the same sample
  fire(0); await settle(); report('tab_return_rechecked');

  // the check after a return fails: still not current
  await next(hang);
  now += 600000;
  tabReturns();  // the old request rejects with AbortError, which is not reported as a timeout
  await settle(); report('old_request_aborted');
  answers.push(() => Promise.resolve(reply(503, {error: 'no current data'})));
  fire(0); await settle(); report('tab_return_check_503');
  answers.push(hang);
  tabReturns(); now += 5000; fire(5000); await settle(); report('tab_return_check_timeout');

  // the service compares CPU readings: its first sample has none, and some cores can be missing later
  const sampling = unavailable => ({mode: 'interval', window_ms: unavailable.length ? null : 1000, unavailable});
  await next(ok({...meta('c', 1, 100), cpu: [], cpu_sampling: sampling([{id: 0, reason: 'warmup'}, {id: 1, reason: 'warmup'}])}), 'cpu_warmup');
  await next(ok({...meta('c', 2, 100), cpu_sampling: sampling([{id: 2, reason: 'warmup'}, {id: 3, reason: 'counter_regressed'}])}), 'cpu_partial');
  await next(ok({...meta('c', 3, 100), cpu_sampling: sampling([{id: 4, reason: '<img src=x>'}])}), 'cpu_odd_reason');

  // optional collectors: a note only for groups that could not read everything; absent ones are not a warning
  const grp = (state, reason = null) => ({state, reason, issues: [], issues_truncated: 0});
  await next(ok({...meta('c', 4, 100), collectors: {core: grp('ok'), temperature: grp('partial', 'some_unreadable'),
    gpu: grp('error', 'io_error'), fans: grp('unavailable', 'not_detected'), '<b>x</b>': grp('error')}}), 'collection_bad');
  await next(() => Promise.reject(new TypeError('Failed to fetch')), 'collection_bad_then_down');
  await next(ok({...meta('c', 5, 100), collectors: {core: grp('ok'), temperature: grp('ok'), gpu: grp('unavailable')}}), 'collection_ok');
  await next(ok({...meta('c', 6, 100), collectors: 'odd'}), 'collection_odd');

  // the read-based data age: shown as the server gives it, not as age + duration
  const readBased = meta('c', 7, 2400);
  readBased.sample = {...readBased.sample, age_ms: 200, duration_ms: 300, cycle_age_ms: 3500, data_age_basis: 'oldest_current_read_start'};
  await next(ok(readBased), 'read_based_age');

  // network and disk counters: the server's rates, a reason instead of 0, names never parsed as HTML
  const c0 = {errors: 0, dropped: 0};
  const iface = (name, rates, reason = null, rx = c0, tx = c0) => ({name, ifindex: 2, rx: {bytes: 1, packets: 1, ...rx},
    tx: {bytes: 1, packets: 1, ...tx}, rates, window_ms: rates ? 1000 : null, reason});
  const disk = (name, rates, reason = null, in_flight = 0) => ({name, major: 8, minor: 0, read: {}, write: {}, in_flight,
    io_time_ms: 1, rates, window_ms: rates ? 1000 : null, reason});
  await next(ok({...meta('c', 8, 100),
    network: {scope: {kind: 'process_network_namespace', id: 'netns1:x'}, provider: 'proc_net_dev', read: null, interfaces: [
      iface('eth0', {rx_bytes_per_s: 1536, tx_bytes_per_s: 0, rx_packets_per_s: 2, tx_packets_per_s: 0}, null, {errors: 3, dropped: 0}),
      iface('<img src=x onerror=alert(1)>', null, 'warmup'), iface('wlan0', null, 'some_new_reason')]},
    disk_io: {scope: {kind: 'host_block_devices'}, provider: 'proc_diskstats', read: null, disks: [
      disk('nvme0n1', {read_bytes_per_s: 3 * 2 ** 20, write_bytes_per_s: 512, reads_per_s: 4, writes_per_s: 0.5, io_time_ratio: 0.034}, null, 2),
      disk('sda', null, 'counter_regressed')]}}), 'counters');
  await next(ok(meta('c', 9, 100)), 'counters_absent');  // turned off, or an older server
  await next(ok({...meta('c', 10, 100), network: {interfaces: 'odd'}, disk_io: null}), 'counters_odd');
})();
