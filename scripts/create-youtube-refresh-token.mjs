#!/usr/bin/env node

import crypto from "node:crypto";
import fs from "node:fs/promises";
import http from "node:http";
import os from "node:os";
import path from "node:path";
import process from "node:process";
import { spawn } from "node:child_process";

const AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth";
const TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token";
const REDIRECT_URI = process.env.YOUTUBE_REDIRECT_URI?.trim() || "http://localhost:8080/oauth2callback";
const SCOPE = "https://www.googleapis.com/auth/youtube.upload";

const required = (name) => {
  const value = process.env[name]?.trim();
  if (!value) throw new Error(`${name} is required.`);
  return value;
};

const openBrowser = (url) => {
  const commands =
    process.platform === "darwin"
      ? [["open", [url]]]
      : process.platform === "win32"
        ? [["cmd", ["/c", "start", "", url]]]
        : [["xdg-open", [url]], ["gio", ["open", url]]];

  for (const [command, args] of commands) {
    try {
      const child = spawn(command, args, { detached: true, stdio: "ignore" });
      child.unref();
      return;
    } catch {
      // Try the next platform opener.
    }
  }
};

const exchangeCode = async ({ clientId, clientSecret, code }) => {
  const body = new URLSearchParams({
    client_id: clientId,
    client_secret: clientSecret,
    code,
    grant_type: "authorization_code",
    redirect_uri: REDIRECT_URI,
  });
  const response = await fetch(TOKEN_ENDPOINT, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body,
    signal: AbortSignal.timeout(60_000),
  });
  const text = await response.text();
  let payload;
  try {
    payload = JSON.parse(text);
  } catch {
    throw new Error(`Google returned invalid JSON with HTTP ${response.status}.`);
  }
  if (!response.ok) {
    const codeName = payload.error ?? "unknown";
    throw new Error(`Google token exchange failed with HTTP ${response.status} (${codeName}).`);
  }
  if (typeof payload.refresh_token !== "string" || payload.refresh_token.length < 20) {
    throw new Error(
      "Google did not return a refresh token. Revoke the app's prior grant, then run this helper again with consent.",
    );
  }
  return payload.refresh_token;
};

const main = async () => {
  const clientId = required("YOUTUBE_CLIENT_ID");
  const clientSecret = required("YOUTUBE_CLIENT_SECRET");
  const redirect = new URL(REDIRECT_URI);
  if (redirect.protocol !== "http:" || !["localhost", "127.0.0.1"].includes(redirect.hostname)) {
    throw new Error("YOUTUBE_REDIRECT_URI must be an HTTP localhost callback.");
  }
  const port = Number(redirect.port || "80");
  if (!Number.isInteger(port) || port < 1024 || port > 65535) {
    throw new Error("The localhost callback port must be between 1024 and 65535.");
  }

  const state = crypto.randomBytes(24).toString("hex");
  const authorization = new URL(AUTH_ENDPOINT);
  authorization.search = new URLSearchParams({
    client_id: clientId,
    redirect_uri: REDIRECT_URI,
    response_type: "code",
    scope: SCOPE,
    access_type: "offline",
    prompt: "consent",
    include_granted_scopes: "true",
    state,
  }).toString();

  const authorizationCode = await new Promise((resolve, reject) => {
    const timeout = setTimeout(() => {
      server.close();
      reject(new Error("Timed out waiting for Google OAuth consent."));
    }, 10 * 60_000);

    const server = http.createServer((request, response) => {
      const callback = new URL(request.url ?? "/", REDIRECT_URI);
      if (callback.pathname !== redirect.pathname) {
        response.writeHead(404, { "Content-Type": "text/plain; charset=utf-8" });
        response.end("Not found.");
        return;
      }
      if (callback.searchParams.get("state") !== state) {
        response.writeHead(400, { "Content-Type": "text/plain; charset=utf-8" });
        response.end("OAuth state mismatch.");
        clearTimeout(timeout);
        server.close();
        reject(new Error("Google OAuth state validation failed."));
        return;
      }
      const oauthError = callback.searchParams.get("error");
      if (oauthError) {
        response.writeHead(400, { "Content-Type": "text/plain; charset=utf-8" });
        response.end("Authorization was not completed. You may close this tab.");
        clearTimeout(timeout);
        server.close();
        reject(new Error(`Google authorization ended with ${oauthError}.`));
        return;
      }
      const code = callback.searchParams.get("code");
      if (!code) {
        response.writeHead(400, { "Content-Type": "text/plain; charset=utf-8" });
        response.end("Authorization code missing.");
        clearTimeout(timeout);
        server.close();
        reject(new Error("Google did not return an authorization code."));
        return;
      }

      response.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
      response.end(
        "<!doctype html><title>Telic authorized</title><main style='font:18px system-ui;padding:40px'><h1>Telic is authorized.</h1><p>You may close this tab.</p></main>",
      );
      clearTimeout(timeout);
      server.close();
      resolve(code);
    });

    server.on("error", (error) => {
      clearTimeout(timeout);
      reject(error);
    });
    server.listen(port, "127.0.0.1", () => {
      console.log("Open this Google authorization URL if the browser does not open automatically:");
      console.log(authorization.toString());
      openBrowser(authorization.toString());
    });
  });

  const refreshToken = await exchangeCode({ clientId, clientSecret, code: authorizationCode });
  const outputDir = path.join(os.homedir(), ".config", "telic");
  const outputPath = path.join(outputDir, "youtube-refresh-token");
  await fs.mkdir(outputDir, { recursive: true, mode: 0o700 });
  await fs.writeFile(outputPath, `${refreshToken}\n`, { mode: 0o600 });
  await fs.chmod(outputPath, 0o600);

  console.log(`Refresh token saved with owner-only permissions at ${outputPath}.`);
  console.log("Copy that file into the public worker secret YOUTUBE_REFRESH_TOKEN, then delete the local file.");
};

main().catch((error) => {
  console.error(error instanceof Error ? error.message : String(error));
  process.exitCode = 1;
});
