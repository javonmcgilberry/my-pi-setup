#!/usr/bin/env node

import * as childProcess from 'node:child_process';
import {lstatSync, realpathSync} from 'node:fs';
import {chmod, mkdir, readFile, rename, writeFile} from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import process from 'node:process';
import {fileURLToPath, pathToFileURL} from 'node:url';

const BROWSER_ENGINE = 'chrome-for-testing';
const DEFAULT_CONFIG = '.auto/designer-load.config.local.json';
const PROFILE_ROOT = path.join(
  os.homedir(),
  '.config',
  'webflow-designer-agent-browser',
  'profiles',
);
const PROFILE_RECOVERY_SCRIPT = fileURLToPath(
  new URL('./reconcile-chrome-profile.py', import.meta.url),
);

function parseJsonOutput(stdout, message) {
  try {
    return JSON.parse(stdout);
  } catch {
    throw new Error(message);
  }
}

export function parseProfiles(stdout) {
  const result = parseJsonOutput(
    stdout,
    'agent-browser returned an invalid Auth Vault response',
  );
  if (
    !result.success ||
    !Array.isArray(result.data?.profiles) ||
    result.data.profiles.some(
      (profile) => !profile || typeof profile.name !== 'string' || !profile.name,
    )
  ) {
    throw new Error('agent-browser returned an invalid Auth Vault response');
  }
  return result.data.profiles;
}

export function classifyAuthProfile(profiles, expectedName) {
  if (
    !Array.isArray(profiles) ||
    profiles.some(
      (profile) => !profile || typeof profile.name !== 'string' || !profile.name,
    ) ||
    typeof expectedName !== 'string' ||
    !expectedName
  ) {
    throw new Error('invalid Auth Vault profile readiness input');
  }
  return profiles.some((profile) => profile.name === expectedName)
    ? 'auth_profile_ready'
    : 'auth_profile_missing';
}

function profileFromConfig(config) {
  if (!config || typeof config !== 'object' || Array.isArray(config)) {
    throw new Error('benchmark config must be a JSON object');
  }
  if (config.browserEngine !== BROWSER_ENGINE) {
    throw new Error('benchmark config must use Chrome for Testing');
  }
  if (typeof config.loginProfile !== 'string' || !config.loginProfile.trim()) {
    throw new Error('benchmark config is missing loginProfile');
  }
  if (typeof config.profileSelector !== 'string' || !config.profileSelector.trim()) {
    throw new Error('benchmark config is missing profileSelector');
  }
  const profile = path.resolve(config.profileSelector);
  if (!profile.startsWith(`${PROFILE_ROOT}${path.sep}`)) {
    throw new Error('benchmark profile must be inside the dedicated profile root');
  }
  try {
    if (lstatSync(profile).isSymbolicLink()) {
      throw new Error('benchmark profile must not be a symbolic link');
    }
  } catch (error) {
    if (error?.code !== 'ENOENT') throw error;
  }
  return {name: config.loginProfile, profile};
}

async function readConfig(configPath) {
  try {
    return JSON.parse(await readFile(configPath, 'utf8'));
  } catch {
    throw new Error(`could not read benchmark config: ${configPath}`);
  }
}

function recoverySucceeded(stdout) {
  try {
    const result = JSON.parse(stdout);
    return result.status === 'clean' || result.status === 'recovered';
  } catch {
    return false;
  }
}

export function runAgentBrowser(
  args,
  {profile, spawnSync = childProcess.spawnSync, ...options} = {},
) {
  const commandOptions = {
    encoding: 'utf8',
    maxBuffer: 1024 * 1024,
    ...options,
  };
  const initial = spawnSync(
    'agent-browser',
    ['--json', ...args],
    commandOptions,
  );
  if (!profile || (!initial.error && initial.status === 0)) return initial;

  const recovery = spawnSync(
    'python3',
    [PROFILE_RECOVERY_SCRIPT, 'reconcile', '--profile', profile, '--confirm'],
    {
      encoding: 'utf8',
      maxBuffer: 256 * 1024,
      timeout: 15_000,
    },
  );
  if (recovery.status !== 0 || !recoverySucceeded(recovery.stdout)) return initial;
  return spawnSync(
    'agent-browser',
    ['--json', ...args],
    commandOptions,
  );
}

export async function status(configPath) {
  const config = await readConfig(configPath);
  const profile = profileFromConfig(config);
  const completed = runAgentBrowser(['auth', 'list'], {profile: profile.profile});
  if (completed.error || completed.status !== 0) {
    throw new Error('could not inspect the agent-browser Auth Vault');
  }
  const profiles = parseProfiles(completed.stdout);
  const classification = classifyAuthProfile(profiles, profile.name);
  process.stdout.write(
    `${JSON.stringify({
      ok: true,
      configured: true,
      classification,
    })}\n`,
  );
}

function readInput(prompt, {hidden = false} = {}) {
  if (!process.stdin.isTTY || !process.stdin.setRawMode) {
    throw new Error('setup must run in an interactive terminal');
  }
  return new Promise((resolve, reject) => {
    let value = '';
    const finish = (error) => {
      process.stdin.off('data', onData);
      process.stdin.setRawMode(false);
      process.stdin.pause();
      process.stdout.write('\n');
      if (error) reject(error);
      else resolve(value.trim());
    };
    const onData = (chunk) => {
      for (const character of chunk.toString()) {
        if (character === '\u0003') return finish(new Error('setup cancelled'));
        if (character === '\r' || character === '\n') return finish();
        if (character === '\u007f') {
          if (value.length > 0) {
            value = value.slice(0, -1);
            if (!hidden) process.stdout.write('\b \b');
          }
        } else {
          value += character;
          if (!hidden) process.stdout.write(character);
        }
      }
    };
    process.stdout.write(prompt);
    process.stdin.setRawMode(true);
    process.stdin.resume();
    process.stdin.on('data', onData);
  });
}

export async function setup(configPath) {
  if (!process.stdin.isTTY) throw new Error('setup must run in an interactive terminal');
  const config = await readConfig(configPath);
  const profile = profileFromConfig(config);
  const loginUrl = config.loginUrl ?? new URL('/login', config.launchUrl).toString();
  const username = await readInput('Webflow test-account username: ');
  if (!username) throw new Error('username is required');
  let password = await readInput('Webflow test-account password: ', {hidden: true});
  if (!password) throw new Error('password is required');
  const saved = runAgentBrowser(
    [
      'auth',
      'save',
      profile.name,
      '--url',
      loginUrl,
      '--username',
      username,
      '--password-stdin',
      '--username-selector',
      '#email-input',
      '--password-selector',
      '#password-input',
      '--submit-selector',
      '[data-automation-id="login-button"]',
    ],
    {input: `${password}\n`, profile: profile.profile},
  );
  password = '';
  if (saved.error || saved.status !== 0) {
    throw new Error('agent-browser could not save the encrypted Auth Vault profile');
  }
  await mkdir(profile.profile, {recursive: true, mode: 0o700});
  await chmod(profile.profile, 0o700);
  const temporaryPath = `${configPath}.${process.pid}.tmp`;
  await writeFile(
    temporaryPath,
    `${JSON.stringify(
      {
        ...config,
        browserEngine: BROWSER_ENGINE,
        loginProfile: profile.name,
        profileSelector: profile.profile,
      },
      null,
      2,
    )}\n`,
    {mode: 0o600},
  );
  await rename(temporaryPath, configPath);
  await chmod(configPath, 0o600);
  await status(configPath);
}

export async function main(argv = process.argv.slice(2)) {
  const [command = 'status', configArgument, ...extraArguments] = argv;
  if (extraArguments.length > 0 || !['setup', 'status'].includes(command)) {
    process.stderr.write(`usage: ${process.argv[1]} <setup|status> [config-path]\n`);
    return 2;
  }
  const configPath = path.resolve(configArgument ?? DEFAULT_CONFIG);
  try {
    if (command === 'setup') await setup(configPath);
    else await status(configPath);
    return 0;
  } catch (error) {
    process.stderr.write(`${error instanceof Error ? error.message : 'unknown error'}\n`);
    return 1;
  }
}

const invokedPath = process.argv[1] ? realpathSync(process.argv[1]) : null;
const modulePath = realpathSync(fileURLToPath(import.meta.url));
if (invokedPath && pathToFileURL(invokedPath).href === pathToFileURL(modulePath).href) {
  process.exitCode = await main();
}
