// Local UI verification only: fictitious data, no connection to the real backend.
const http = require('node:http');
const at = '2026-10-12T02:00:00';
let persona = {
  revision: 3,
  fields: { investment_experience: 'intermediate', risk_preference: 'conservative', investment_horizon_months: 36,
    investment_goals: ['长期积累', '为三年后的购房做准备'], excluded_fund_types: ['qdii'], response_language: 'zh-CN', response_detail: 'balanced' },
  provenance: {},
  pending_proposals: [{ id: 'preview-proposal', base_revision: 3, changes: { response_detail: 'detailed' },
    evidence: '以后分析基金时，希望你详细解释数据和判断依据，请记住。', source_session_id: 'preview', source_message_id: 'preview', status: 'PENDING', created_at: at }],
};
for (const key of Object.keys(persona.fields)) persona.provenance[key] = { source: 'user_edit', confirmed_at: at, revision: 3 };
let history = [
  { revision: 3, changes: { investment_goals: persona.fields.investment_goals, investment_horizon_months: 36 }, source: 'user_edit', created_at: at },
  { revision: 2, changes: { risk_preference: 'conservative' }, source: 'user_confirmed_proposal', created_at: '2026-10-11T06:30:00' },
  { revision: 1, changes: { response_language: 'zh-CN', response_detail: 'balanced' }, source: 'user_edit', created_at: '2026-10-10T08:10:00' },
];
let failNextWrite = false;
http.createServer(async (req, res) => {
  res.setHeader('Access-Control-Allow-Origin', 'http://localhost:3107');
  res.setHeader('Access-Control-Allow-Headers', 'Authorization,Content-Type');
  res.setHeader('Access-Control-Allow-Methods', 'GET,POST,PATCH,DELETE,OPTIONS');
  res.setHeader('Content-Type', 'application/json; charset=utf-8');
  if (req.method === 'OPTIONS') { res.writeHead(204); res.end(); return; }
  const url = new URL(req.url, 'http://localhost');
  let body = ''; for await (const chunk of req) body += chunk;
  const input = body.startsWith('{') ? JSON.parse(body) : {};
  let status = 200, value = {};
  if (url.pathname === '/api/v1/auth/login') value = { access_token: 'preview-token', refresh_token: null, token_type: 'bearer' };
  else if (url.pathname === '/api/v1/auth/me') value = { id: 999999, email: 'preview@example.invalid', username: '设计预览', created_at: at };
  else if (url.pathname === '/api/v1/agent/user-profile/history') value = history.slice(0, Number(url.searchParams.get('limit') || 10));
  else if (url.pathname === '/api/v1/agent/user-profile') {
    if (req.method === 'PATCH' || req.method === 'DELETE') {
      if (failNextWrite) { failNextWrite = false; status = 503; value = { detail: '预览：服务暂时不可用，请稍后重试' }; }
      else if (input.expected_revision !== persona.revision) { status = 409; value = { detail: '画像已变化，请重新读取后编辑' }; }
      else {
        persona.revision++; persona.pending_proposals = [];
        if (req.method === 'DELETE') { persona.fields = {}; persona.provenance = {}; history = []; }
        else {
          for (const [key, v] of Object.entries(input.changes)) {
            if (v === null) { delete persona.fields[key]; delete persona.provenance[key]; }
            else { persona.fields[key] = v; persona.provenance[key] = { source: 'user_edit', confirmed_at: at, revision: persona.revision }; }
          }
          history.unshift({ revision: persona.revision, changes: input.changes, source: 'user_edit', created_at: at });
        }
        value = persona;
      }
    } else value = persona;
  } else if (url.pathname.endsWith('/decision')) {
    if (input.expected_revision !== persona.revision) { status = 409; value = { detail: '画像已变化，请重新读取后编辑' }; }
    else {
      if (input.decision === 'accept') {
        const changes = persona.pending_proposals[0]?.changes || {}; persona.revision++;
        Object.assign(persona.fields, changes);
        for (const key of Object.keys(changes)) persona.provenance[key] = { source: 'user_confirmed_proposal', confirmed_at: at, revision: persona.revision };
        history.unshift({ revision: persona.revision, changes, source: 'user_confirmed_proposal', created_at: at });
      }
      persona.pending_proposals = []; value = persona;
    }
  } else if (url.pathname === '/__preview/advance') { persona.revision++; value = { revision: persona.revision }; }
  else if (url.pathname === '/__preview/fail-next-write') { failNextWrite = true; }
  else { status = 404; value = { detail: 'preview_endpoint_not_supported' }; }
  console.log(`${req.method.toLowerCase()} ${url.pathname} ${status}`);
  res.writeHead(status); res.end(JSON.stringify(value));
}).listen(8019, '127.0.0.1', () => console.log('persona_preview_api_ready'));
