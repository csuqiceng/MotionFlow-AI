"use strict";

const assert = require("node:assert/strict");
const path = require("node:path");

const policy = require(path.join(__dirname, "..", "..", "build", "trusted-origin-policy.js"));

const trusted = policy.trustedLoopbackOrigin("http://127.0.0.1:48123/app");
assert.equal(trusted, "http://127.0.0.1:48123");
assert.equal(policy.hasExactOrigin("http://127.0.0.1:48123/other", trusted), true);
assert.equal(policy.hasExactOrigin("http://127.0.0.1:48124/attack", trusted), false);
assert.equal(policy.hasExactOrigin("http://localhost:48123/attack", trusted), false);
assert.equal(policy.hasExactOrigin("https://127.0.0.1:48123/attack", trusted), false);
assert.equal(policy.mayOpenInSystemBrowser("https://example.com/docs"), true);
assert.equal(policy.mayOpenInSystemBrowser("javascript:alert(1)"), false);
assert.equal(policy.mayOpenInSystemBrowser("file:///C:/secret"), false);

console.log("trusted origin policy tests passed");
