/**
 * Lambda Authorizer for CurateAI Widget JWT Verification
 *
 * Flow:
 * 1. Extract Bearer token from Authorization header
 * 2. Decode JWT (without verification) to get iss/client_id
 * 3. Look up customer config from DynamoDB (JWKS URL, origins, tenant_id)
 * 4. Fetch and cache JWKS from customer's endpoint
 * 5. Verify JWT signature, exp, aud
 * 6. Validate Origin header against allowed origins
 * 7. Return IAM policy (allow/deny) with tenant context
 */

import { DynamoDBClient } from "@aws-sdk/client-dynamodb";
import { DynamoDBDocumentClient, GetCommand } from "@aws-sdk/lib-dynamodb";
import {
  JwksCache,
  SimpleJwksCache,
  assertStringEquals,
  decomposeUnverifiedJwt,
} from "aws-jwt-verify/jwt-rsa";
import { fetchJwk } from "aws-jwt-verify/https";

const TABLE_NAME = process.env.TABLE_NAME || "CurateAI-WidgetClients";
const EXPECTED_AUD = process.env.EXPECTED_AUD || "curateai";

const ddbClient = new DynamoDBClient({});
const docClient = DynamoDBDocumentClient.from(ddbClient);

// In-memory caches (persist across warm Lambda invocations)
const clientConfigCache = new Map();   // client_id → DynamoDB record
const CLIENT_CACHE_TTL_MS = 5 * 60 * 1000; // 5 min

const jwksCache = new Map(); // jwks_url → { keys, fetchedAt }
const JWKS_CACHE_TTL_MS = 10 * 60 * 1000; // 10 min

/**
 * Look up client config from DynamoDB with caching.
 */
async function getClientConfig(clientId) {
  const cached = clientConfigCache.get(clientId);
  if (cached && Date.now() - cached.fetchedAt < CLIENT_CACHE_TTL_MS) {
    return cached.data;
  }

  const result = await docClient.send(
    new GetCommand({
      TableName: TABLE_NAME,
      Key: { client_id: clientId },
    })
  );

  const item = result.Item;
  if (item) {
    clientConfigCache.set(clientId, { data: item, fetchedAt: Date.now() });
  }
  return item || null;
}

/**
 * Fetch JWKS from a URL with caching.
 */
async function getJwks(jwksUrl) {
  const cached = jwksCache.get(jwksUrl);
  if (cached && Date.now() - cached.fetchedAt < JWKS_CACHE_TTL_MS) {
    return cached.keys;
  }

  const response = await fetch(jwksUrl);
  if (!response.ok) {
    throw new Error(`Failed to fetch JWKS from ${jwksUrl}: ${response.status}`);
  }

  const jwksData = await response.json();
  jwksCache.set(jwksUrl, { keys: jwksData.keys, fetchedAt: Date.now() });
  return jwksData.keys;
}

/**
 * Find the matching key from JWKS by kid.
 */
function findKey(keys, kid) {
  const key = keys.find((k) => k.kid === kid);
  if (!key) {
    throw new Error(`Key with kid '${kid}' not found in JWKS`);
  }
  return key;
}

/**
 * Verify JWT signature using the Web Crypto API.
 */
async function verifyJwt(token, jwksUrl) {
  const { header, payload } = decomposeUnverifiedJwt(token);

  const keys = await getJwks(jwksUrl);
  const jwk = findKey(keys, header.kid);

  // Import the public key
  const algorithm =
    header.alg === "RS256"
      ? { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" }
      : header.alg === "ES256"
        ? { name: "ECDSA", namedCurve: "P-256" }
        : null;

  if (!algorithm) {
    throw new Error(`Unsupported algorithm: ${header.alg}`);
  }

  const cryptoKey = await crypto.subtle.importKey(
    "jwk",
    jwk,
    algorithm,
    false,
    ["verify"]
  );

  // Verify signature
  const [headerB64, payloadB64, signatureB64] = token.split(".");
  const data = new TextEncoder().encode(`${headerB64}.${payloadB64}`);
  const signature = base64UrlDecode(signatureB64);

  const signParams =
    header.alg === "ES256"
      ? { name: "ECDSA", hash: "SHA-256" }
      : algorithm;

  const valid = await crypto.subtle.verify(signParams, cryptoKey, signature, data);

  if (!valid) {
    throw new Error("JWT signature verification failed");
  }

  return payload;
}

/**
 * Base64url decode to ArrayBuffer.
 */
function base64UrlDecode(str) {
  const base64 = str.replace(/-/g, "+").replace(/_/g, "/");
  const padded = base64 + "=".repeat((4 - (base64.length % 4)) % 4);
  const binary = atob(padded);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) {
    bytes[i] = binary.charCodeAt(i);
  }
  return bytes.buffer;
}

/**
 * Build an IAM policy for API Gateway.
 */
function buildPolicy(principalId, effect, resource, context = {}) {
  return {
    principalId,
    policyDocument: {
      Version: "2012-10-17",
      Statement: [
        {
          Action: "execute-api:Invoke",
          Effect: effect,
          Resource: resource,
        },
      ],
    },
    context,
  };
}

/**
 * Lambda handler.
 */
export async function handler(event) {
  const token = (event.headers?.authorization || event.headers?.Authorization || "")
    .replace(/^Bearer\s+/i, "");

  if (!token) {
    console.log("No Bearer token provided");
    return buildPolicy("anonymous", "Deny", event.routeArn);
  }

  try {
    // Decode without verification to get claims
    const { payload: unverified } = decomposeUnverifiedJwt(token);
    const clientId = unverified.client_id;

    if (!clientId) {
      console.log("JWT missing client_id claim");
      return buildPolicy("anonymous", "Deny", event.routeArn);
    }

    // Look up client config
    const config = await getClientConfig(clientId);
    if (!config) {
      console.log(`Unknown client_id: ${clientId}`);
      return buildPolicy("anonymous", "Deny", event.routeArn);
    }

    if (!config.is_active) {
      console.log(`Client ${clientId} is inactive`);
      return buildPolicy("anonymous", "Deny", event.routeArn);
    }

    // Verify JWT signature against customer's JWKS
    const payload = await verifyJwt(token, config.jwks_url);

    // Check expiry
    const now = Math.floor(Date.now() / 1000);
    if (payload.exp && payload.exp < now) {
      console.log(`Token expired: exp=${payload.exp}, now=${now}`);
      return buildPolicy("anonymous", "Deny", event.routeArn);
    }

    // Check audience
    if (EXPECTED_AUD) {
      const tokenAud = Array.isArray(payload.aud) ? payload.aud : [payload.aud];
      if (!tokenAud.includes(EXPECTED_AUD)) {
        console.log(`Invalid audience: ${payload.aud}`);
        return buildPolicy("anonymous", "Deny", event.routeArn);
      }
    }

    // Check issuer matches config
    if (config.expected_iss && payload.iss !== config.expected_iss) {
      console.log(`Issuer mismatch: got ${payload.iss}, expected ${config.expected_iss}`);
      return buildPolicy("anonymous", "Deny", event.routeArn);
    }

    // Validate Origin header
    const origin = event.headers?.origin || event.headers?.Origin;
    if (origin && config.allowed_origins?.length > 0) {
      if (!config.allowed_origins.includes(origin)) {
        console.log(`Origin ${origin} not in allowed list for ${clientId}`);
        return buildPolicy("anonymous", "Deny", event.routeArn);
      }
    }

    // Allow — pass tenant context to backend
    console.log(`Authorized: client=${clientId}, sub=${payload.sub}`);
    return buildPolicy(payload.sub || clientId, "Allow", event.routeArn, {
      tenant_id: config.tenant_id,
      client_id: clientId,
      user_id: payload.sub || "",
    });
  } catch (err) {
    console.error("Authorization failed:", err.message);
    return buildPolicy("anonymous", "Deny", event.routeArn);
  }
}
