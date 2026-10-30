#!/usr/bin/env node
/**
 * Create a dashboard login (there is no public registration page).
 *
 *   npm run create-admin -- --local            # local D1 used by `npm run dev`
 *   npm run create-admin -- --remote           # production D1 on Cloudflare
 *   npm run create-admin -- --remote --reset   # change an existing user's password and sign them out
 *
 * The script prompts for a username and password (the password is not echoed), hashes the
 * password here with PBKDF2-SHA256 and a random salt, and stores only that hash in D1 through
 * `wrangler d1 execute`. The password itself never leaves this process and is never written to
 * disk; the SQL is written to a private temporary file that is deleted straight afterwards.
 *
 * When stdin is not a terminal (automation), it reads three lines: username, password, password.
 */
import { spawnSync } from "node:child_process";
import { pbkdf2Sync, randomBytes } from "node:crypto";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import readline from "node:readline";
import { fileURLToPath } from "node:url";

// Must match src/auth.ts. Kept low enough for the Workers Free 10 ms CPU limit per request
// (about 5 ms per login); login rate limiting and the 12-character minimum make up for it.
// The count is stored inside each hash, so it can be raised later without breaking old hashes.
export const ITERATIONS = 30_000;
const DATABASE = "ontop-gaming-db";
const USERNAME_RE = /^[A-Za-z0-9_.-]{3,32}$/;
const MIN_PASSWORD = 12;
const MAX_PASSWORD = 256;

export function hashPassword(password, iterations = ITERATIONS) {
  const salt = randomBytes(16);
  const hash = pbkdf2Sync(password.normalize("NFC"), salt, iterations, 32, "sha256");
  return `pbkdf2_sha256$${iterations}$${salt.toString("base64")}$${hash.toString("base64")}`;
}

function parseArgs(argv) {
  const args = new Set(argv);
  const unknown = [...args].filter((a) => !["--local", "--remote", "--reset"].includes(a));
  if (unknown.length || args.has("--local") === args.has("--remote")) {
    console.error("Usage: npm run create-admin -- (--local | --remote) [--reset]");
    process.exit(2);
  }
  return { target: args.has("--remote") ? "--remote" : "--local", reset: args.has("--reset") };
}

let pipedLines = null;
async function readPipedLine() {
  if (pipedLines === null) {
    const chunks = [];
    for await (const chunk of process.stdin) chunks.push(chunk);
    pipedLines = Buffer.concat(chunks).toString("utf8").split(/\r?\n/);
  }
  return pipedLines.shift() ?? "";
}

function ask(question, hidden = false) {
  if (!process.stdin.isTTY) return readPipedLine();
  return new Promise((resolve) => {
    const rl = readline.createInterface({ input: process.stdin, output: process.stdout, terminal: true });
    let muted = false;
    rl._writeToOutput = (text) => {
      if (!muted) rl.output.write(text);
    };
    rl.question(question, (answer) => {
      if (hidden) rl.output.write("\n");
      rl.close();
      resolve(answer);
    });
    muted = hidden;
  });
}

async function main() {
  const { target, reset } = parseArgs(process.argv.slice(2));
  console.log(`${reset ? "Reset the password of" : "Create"} a dashboard user in the ${target.slice(2)} database.`);
  console.log("Use a new password: not your Cloudflare password and not the desktop SYNC_TOKEN.\n");

  const username = (await ask("Username: ")).trim();
  if (!USERNAME_RE.test(username)) {
    console.error("Username must be 3-32 characters: letters, digits, '.', '_' or '-'.");
    process.exit(1);
  }
  const password = await ask("Password: ", true);
  const confirm = await ask("Repeat password: ", true);
  if (password !== confirm) {
    console.error("The passwords do not match.");
    process.exit(1);
  }
  if (password.length < MIN_PASSWORD || password.length > MAX_PASSWORD) {
    console.error(`Password must be ${MIN_PASSWORD}-${MAX_PASSWORD} characters long.`);
    process.exit(1);
  }
  if (password.toLowerCase().includes(username.toLowerCase())) {
    console.error("Password must not contain the username.");
    process.exit(1);
  }

  const hash = hashPassword(password);
  const now = Math.floor(Date.now() / 1000);
  // Both values are restricted to SQL-safe characters (validated username, base64 hash).
  const sql = reset
    ? `INSERT INTO users (username, password_hash, created_at, updated_at) VALUES ('${username}', '${hash}', ${now}, ${now})
  ON CONFLICT(username) DO UPDATE SET password_hash = excluded.password_hash, updated_at = excluded.updated_at;
DELETE FROM auth_sessions WHERE user_id IN (SELECT id FROM users WHERE username = '${username}');
DELETE FROM login_attempts WHERE bucket = 'user:${username.toLowerCase()}';\n`
    : `INSERT INTO users (username, password_hash, created_at, updated_at) VALUES ('${username}', '${hash}', ${now}, ${now});\n`;

  const dir = mkdtempSync(join(tmpdir(), "ontop-admin-"));
  const file = join(dir, "user.sql");
  let result;
  try {
    writeFileSync(file, sql, { mode: 0o600 });
    const projectDir = join(dirname(fileURLToPath(import.meta.url)), "..");
    const wrangler = join(projectDir, "node_modules", "wrangler", "bin", "wrangler.js");
    result = spawnSync(process.execPath, [wrangler, "d1", "execute", DATABASE, target, "--file", file], {
      cwd: projectDir,
      stdio: "inherit",
    });
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
  if (result.status !== 0) {
    console.error(
      `\nWrangler could not save the user.${reset ? "" : " If the username already exists, run again with --reset."}`,
    );
    process.exit(result.status ?? 1);
  }
  console.log(`\nSaved user '${username}'. Only the password hash was stored.`);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
