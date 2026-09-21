/**
 * Download the running backend's OpenAPI document into openapi.json.
 *
 * Type generation runs from `npm run generate:api`, which pipes this snapshot
 * through openapi-typescript so the client types cannot drift from the API
 * (MVP spec 10).
 *
 * Usage: npm run generate:api            (expects http://localhost:8000)
 *        API_BASE_URL=http://192.168.1.10:8000 npm run generate:api
 */

import { writeFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const base = (process.env.API_BASE_URL ?? 'http://localhost:8000').replace(/\/$/, '');

const response = await fetch(`${base}/api/v1/openapi.json`);
if (!response.ok) {
  console.error(`无法获取 OpenAPI：${response.status}（后端是否已启动？）`);
  process.exit(1);
}

const spec = await response.json();
writeFileSync(path.join(root, 'openapi.json'), `${JSON.stringify(spec, null, 2)}
`);
console.log(`已下载 ${base}/api/v1/openapi.json`);
