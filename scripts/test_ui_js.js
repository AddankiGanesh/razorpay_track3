const fs = require('fs');
const path = require('path');
const html = fs.readFileSync(path.join(__dirname, '../app/ui/app.html'), 'utf8');
const scriptMatch = html.match(/<script>\s*([\s\S]*?)<\/script>\s*<\/body>/);
if (!scriptMatch) {
  console.error('No inline script found');
  process.exit(1);
}
const script = scriptMatch[1];

const elements = {};
function makeEl(id) {
  const el = {
    id,
    className: '',
    classList: {
      _c: new Set(),
      toggle(k, v) { if (v) this._c.add(k); else this._c.delete(k); el.className = [...this._c].join(' '); },
      add(k) { this._c.add(k); el.className = [...this._c].join(' '); },
      contains(k) { return this._c.has(k); },
    },
    style: {},
    innerHTML: '',
    value: 'ganeshsuraj29@gmail.com',
    dataset: {},
    textContent: '',
    addEventListener() {},
    querySelector() { return null; },
    querySelectorAll() { return []; },
    appendChild() {},
    click() {},
  };
  elements[id] = el;
  return el;
}

const ids = [
  'toast', 'hinglish-toggle', 'mobile-nav', 'tab-dashboard', 'tab-scenarios', 'tab-cases', 'tab-checkout',
  'hero-kpis', 'metrics', 'recovery-plan', 'leak-funnel', 'leakage-report', 'counterfactual',
  'recovery-budget', 'escalation-queue', 'batch-metrics', 'all-scenarios', 'activity-list',
  'case-detail', 'case-detail-2', 'email', 'email2', 'checkout-pay', 'checkout-email', 'checkout-amount',
  'checkout-log', 'sync-status', 'case-count', 'donut-legend', 'chart-recovery-trend', 'chart-breakdown',
];
ids.forEach(makeEl);

global.document = {
  getElementById: (id) => elements[id] || null,
  querySelector: (sel) => {
    if (sel === '.sidebar') return { innerHTML: '<button class="nav-btn" data-tab="dashboard">Dash</button>' };
    return null;
  },
  querySelectorAll: () => [],
};
global.window = global;
global.localStorage = { getItem: () => null, setItem: () => {} };
global.history = { replaceState: () => {} };
global.location = { search: '' };
global.Chart = undefined;
global.fetch = async (url) => ({
  ok: true,
  status: 200,
  json: async () => {
    if (url.includes('intelligence')) return { recovery_plan: {}, events_analyzed: 0, pursue_count: 0, stopped_count: 0, total_at_risk_rupees: 0, total_recovered_rupees: 0, recovery_opportunity_rupees: 0 };
    if (url.includes('summary')) return { recovery_rate_percent: 0, interventions_sent: 0, stopped_by_rules: 0, delayed_for_downtime: 0 };
    if (url.includes('activity')) return { activity: [], razorpay_sync: null };
    if (url.includes('leak-funnel')) return { flows: {}, total_at_risk_rupees: 0 };
    if (url.includes('leakage')) return { ai_narrative: 'ok', events_count: 0, total_loss_rupees: 0, by_payment_method: [], by_hour_ist: [], recommended_interventions: [] };
    if (url.includes('counterfactual')) return { baseline_strategy: {}, smart_strategy: {}, incremental_recovery_rupees: 0, events_analyzed: 0 };
    if (url.includes('recovery-budget')) return { spent_rupees: 0, budget_rupees: 50000, allocation: {}, allocated_cases: 0, deferred_cases: 0, policy: {} };
    if (url.includes('escalations')) return { count: 0, queue: [] };
    if (url.includes('scenarios')) return { scenarios: [{ id: 'incorrect_otp', label: 'Wrong OTP', group: 'auth', amount_rupees: 499 }] };
    if (url.includes('batch-metrics')) return { by_category: {}, total_recovered_rupees: 0, total_at_risk_rupees: 0 };
    return {};
  },
});
global.setInterval = () => {};
global.confirm = () => true;

try {
  eval(script);
  console.log('Script executed OK');
  console.log('seedTrainingBatch', typeof seedTrainingBatch);
  console.log('fireAll', typeof fireAll);
} catch (e) {
  console.error('RUNTIME ERROR at init:', e.message);
  console.error(e.stack);
  process.exit(1);
}
