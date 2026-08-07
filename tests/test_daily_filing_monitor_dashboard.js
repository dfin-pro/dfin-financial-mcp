'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const repositoryRoot = path.resolve(__dirname, '..');
const dashboardPath = path.join(
  repositoryRoot,
  'skills',
  'dfin-daily-filing-monitor',
  'dashboard.html'
);
const template = fs.readFileSync(dashboardPath, 'utf8');
const scripts = [...template.matchAll(/<script[^>]*>([\s\S]*?)<\/script>/g)];

assert.equal(scripts.length, 2);
assert.equal(template.includes('onclick='), false);

const data = {
  title: 'Test Monitor',
  ftype: '8-K',
  range: 'Aug 6, 2026',
  stats: [[1, 'Companies'], [1, 'Filing bundles']],
  filters: [['all', 'All (1)'], ['confirmed', 'Confirmed (1)']],
  cos: [{
    t: 'TEST.US',
    n: 'Test Company',
    s: 'NYSE · Software',
    p: '$10.00',
    pc: '$0.00 (0.00%)',
    pp: null,
    mc: '$1.0B',
    b: '—',
    r: [0, null, 1.25, -2.5, null],
    roe: '—',
    roic: '—',
    nd: '—',
    em: '—',
    pe: '—',
    eps: [],
    d: 'Makes testing products.',
    fs: [{
      id: 'bundle-1',
      ft: '8-K',
      fd: 'Aug 6',
      fl: 'javascript:alert(1)',
      tags: ['confirmed', 'appointments'],
      flag: false,
      ev: [['pill-in', 'APPOINTMENT', 'Person', 'Named CEO']],
      docs: 2
    }]
  }]
};
const root = {innerHTML: ''};
const dataNode = {textContent: JSON.stringify(data)};
const document = {
  getElementById(id) {
    if (id === 'dashboard-data') return dataNode;
    if (id === 'root') return root;
    return null;
  },
  querySelectorAll() {
    return [];
  }
};
const context = vm.createContext({document, URL, console});

vm.runInContext(scripts[1][1], context, {filename: dashboardPath});

const monitor = context.DFinFilingMonitor;

assert.equal(monitor.formatReturn(null).text, '—');
assert.equal(monitor.formatReturn(0).text, '0.0%');
assert.equal(monitor.formatReturn(-2.5).text, '-2.5%');
assert.equal(
  monitor.safeSecUrl('https://www.sec.gov/Archives/edgar/data/1/example.htm'),
  'https://www.sec.gov/Archives/edgar/data/1/example.htm'
);
assert.equal(monitor.safeSecUrl('javascript:alert(1)'), null);
assert.equal(
  monitor.safeSecUrl('https://user@www.sec.gov/Archives/edgar/data/1/example.htm'),
  null
);
assert.equal(
  monitor.safeSecUrl('https://www.sec.gov:444/Archives/edgar/data/1/example.htm'),
  null
);
assert.equal(root.innerHTML.includes('0.0%'), true);
assert.equal(root.innerHTML.includes('—'), true);
assert.equal(root.innerHTML.includes('filing-bundle'), true);
assert.equal(root.innerHTML.includes('Source unavailable'), true);
assert.equal(root.innerHTML.includes('javascript:'), false);
assert.equal(root.innerHTML.includes('onclick='), false);

const unavailableCard = monitor.renderCard({
  t: 'MISS.US',
  n: 'Missing Data Company',
  p: '—',
  mc: '—',
  b: '—',
  r: [null, null, null, null, null],
  v: '—',
  roe: '—',
  roic: '—',
  nd: '—',
  em: '—',
  pe: '—',
  eps: [],
  fs: [{id: 'bundle-missing', ft: '8-K', fd: 'Aug 6'}]
});
assert.equal(unavailableCard.includes('stock-row'), false);
assert.equal(unavailableCard.includes('fund-row'), false);

const epsOnlyCard = monitor.renderCard({
  t: 'EPS.US',
  n: 'EPS Company',
  roe: '—',
  roic: '—',
  nd: '—',
  em: '—',
  pe: '—',
  eps: [[-1, '2026-06-30']],
  fs: [{id: 'bundle-eps', ft: '8-K', fd: 'Aug 6'}]
});
assert.equal(epsOnlyCard.includes('eps-blk'), true);
assert.equal(epsOnlyCard.includes('>ROE<'), false);
assert.equal(epsOnlyCard.includes('ratio-vintage'), false);

console.log('daily filing monitor dashboard tests passed');
