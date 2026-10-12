import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import ts from 'typescript';

const source = readFileSync(new URL('../src/utils/formatRevenue.ts', import.meta.url), 'utf8');
const { outputText } = ts.transpileModule(source, {
  compilerOptions: { target: ts.ScriptTarget.ES2020, module: ts.ModuleKind.ES2020 },
});
const { formatRevenue } = await import(`data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`);
const jwtSource = readFileSync(new URL('../src/utils/jwtUtils.ts', import.meta.url), 'utf8')
  .replaceAll('import.meta.env.DEV', 'false');
const jwtModule = ts.transpileModule(jwtSource, {
  compilerOptions: { target: ts.ScriptTarget.ES2020, module: ts.ModuleKind.ES2020 },
});
const { extractTenantFromSession, decodeJWTPayload } = await import(
  `data:text/javascript;base64,${Buffer.from(jwtModule.outputText).toString('base64')}`
);

const tokenFor = claims => `header.${Buffer.from(JSON.stringify(claims)).toString('base64url')}.signature`;

test('preserves exact cents without binary arithmetic', () => {
  for (const amount of ['1.01', '2.68', '0.00', '-0.01', '-1.01', '1000.00', '9007199254740993.01']) {
    const [whole, cents] = amount.replace(/^-/, '').split('.');
    const expected = `${amount.startsWith('-') ? '-' : ''}${BigInt(whole).toLocaleString()}.${cents}`;
    assert.equal(formatRevenue(amount), expected);
  }
});

test('rejects unrounded or malformed API amounts instead of silently rounding', () => {
  for (const amount of ['1.005', '1', 'NaN', '', '1e3', '1.2']) {
    assert.throws(() => formatRevenue(amount), /Invalid revenue amount/);
  }
});

test('both account tenants are read from server-controlled app metadata', () => {
  for (const tenant of ['tenant-a', 'tenant-b']) {
    assert.equal(extractTenantFromSession({ access_token: tokenFor({
      app_metadata: { tenant_id: tenant }, user_metadata: { tenant_id: 'foreign-tenant' },
    }) }), tenant);
  }
  assert.equal(extractTenantFromSession({ access_token: tokenFor({
    tenant_id: 'tenant-a',
  }) }), 'tenant-a');
  assert.equal(extractTenantFromSession({ access_token: tokenFor({
    user_metadata: { tenant_id: 'tenant-a' },
  }) }), null);
});

test('JWT display claims support UTF-8 and base64url encoding', () => {
  const claims = { app_metadata: { tenant_id: 'tenant-b' }, name: 'Océan ☀' };
  assert.deepEqual(decodeJWTPayload(tokenFor(claims)), claims);
});

test('missing session cannot fall back to another tenant', () => {
  assert.equal(extractTenantFromSession(null), null);
  assert.equal(extractTenantFromSession({}), null);
});
