import assert from 'node:assert/strict';
import test from 'node:test';

import {classifyAuthProfile, parseProfiles, runAgentBrowser} from './designer-load-auth.mjs';

test('parseProfiles accepts the bounded Auth Vault list shape', () => {
  assert.deepEqual(
    parseProfiles(
      JSON.stringify({success: true, data: {profiles: [{name: 'designer-load'}]}}),
    ),
    [{name: 'designer-load'}],
  );
});

test('parseProfiles rejects an unsuccessful or malformed Vault response', () => {
  assert.throws(
    () => parseProfiles(JSON.stringify({success: false, data: {profiles: []}})),
    /invalid Auth Vault response/,
  );
  assert.throws(
    () => parseProfiles(JSON.stringify({success: true, data: {profiles: 'nope'}})),
    /invalid Auth Vault response/,
  );
  assert.throws(
    () => parseProfiles(JSON.stringify({success: true, data: {profiles: [null]}})),
    /invalid Auth Vault response/,
  );
});

test('classifyAuthProfile returns only bounded readiness states', () => {
  assert.equal(
    classifyAuthProfile([{name: 'webflow-designer'}], 'webflow-designer'),
    'auth_profile_ready',
  );
  assert.equal(
    classifyAuthProfile([{name: 'other'}], 'webflow-designer'),
    'auth_profile_missing',
  );
  assert.throws(
    () => classifyAuthProfile([{name: 'webflow-designer'}], ''),
    /invalid Auth Vault profile readiness input/,
  );
  assert.throws(
    () => classifyAuthProfile([null], 'webflow-designer'),
    /invalid Auth Vault profile readiness input/,
  );
});

test('failed Vault operations reconcile and retry once after recovery', () => {
  const calls = [];
  const responses = [
    {status: 1, stdout: '', error: undefined},
    {status: 0, stdout: JSON.stringify({status: 'recovered'}), error: undefined},
    {status: 0, stdout: JSON.stringify({success: true}), error: undefined},
  ];
  const result = runAgentBrowser(['auth', 'list'], {
    profile: '/tmp/dedicated-profile',
    spawnSync(command, args, options) {
      calls.push({command, args, options});
      return responses.shift();
    },
  });

  assert.equal(result.status, 0);
  assert.deepEqual(
    calls.map(({command}) => command),
    ['agent-browser', 'python3', 'agent-browser'],
  );
  assert.equal(calls[1].args.at(-1), '--confirm');
  assert.equal(calls[0].options.maxBuffer, 1024 * 1024);
});

test('failed Vault operations are not retried when profile ownership is blocked', () => {
  const calls = [];
  const result = runAgentBrowser(['auth', 'list'], {
    profile: '/tmp/dedicated-profile',
    spawnSync(command) {
      calls.push(command);
      return command === 'agent-browser'
        ? {status: 1, stdout: '', error: undefined}
        : {status: 1, stdout: JSON.stringify({status: 'blocked'}), error: undefined};
    },
  });

  assert.equal(result.status, 1);
  assert.deepEqual(calls, ['agent-browser', 'python3']);
});
