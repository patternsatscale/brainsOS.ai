import { ParsedMail } from "mailparser";
import {
  ApprovedEmailPayload,
  ClaimCheckMessage,
  PipelineVerdict,
  QuarantinedEmailPayload,
} from "./types.js";

export interface SesReceiptVerdicts {
  spfVerdict?: { status?: string } | string;
  dkimVerdict?: { status?: string } | string;
  dmarcVerdict?: { status?: string } | string;
}

export interface PipelineOptions {
  allowedSenders: string[];
  allowedRecipientDomains?: string[];
  sesReceipt?: SesReceiptVerdicts;
  trustedAuthServPattern?: RegExp;
}

export const PROMPT_INJECTION_SIGNATURES = [
  /ignore\s+(all\s+)?previous\s+instructions/i,
  /system\s+override/i,
  /you\s+are\s+now\s+in\s+developer\s+mode/i,
  /you\s+are\s+now\s+an?\s+unfiltered/i,
  /disregard\s+(all\s+)?(prior|previous)\s+instructions/i,
  /cat\s+[/~]memories/i,
  /curl\s+-[A-Za-z0-9]*[sS]/i,
  /\brm\s+-rf\b/i,
  /\bbash\s+-c\b/i,
  /\bpython3?\s+-c\b/i,
];

// Zero-width Unicode, bidirectional overrides, and invisible joiners
export const ZERO_WIDTH_REGEX =
  /[\u200B-\u200D\uFEFF\u200E\u200F\u202A-\u202E\u2060-\u2064\u2066-\u2069]/g;

// Hidden HTML elements (display:none, visibility:hidden, font-size:0, opacity:0, hidden attribute)
export const HIDDEN_HTML_REGEX =
  /<([a-zA-Z0-9]+)[^>]*(?:style\s*=\s*["'][^"']*(?:display\s*:\s*none|visibility\s*:\s*hidden|font-size\s*:\s*0|opacity\s*:\s*0|color\s*:\s*(?:transparent|rgba\([^)]*0\)))[^"']*|(?:\s|^)hidden(?:\s|>|=))[^>]*>.*?<\/\1>/gis;

// Tracking pixel 1x1 or 0x0 images
export const TRACKING_PIXEL_REGEX =
  /<img[^>]*(?:width\s*=\s*["']?[01]["']?[^>]*height\s*=\s*["']?[01]["']?|height\s*=\s*["']?[01]["']?[^>]*width\s*=\s*["']?[01]["']?)[^>]*\/?>/gi;

// Unsafe executable HTML elements
export const UNSAFE_TAGS_REGEX = /<(?:script|style|iframe|object|embed|applet)[^>]*>.*?<\/(?:script|style|iframe|object|embed|applet)>/gis;

const DEFAULT_SES_AUTHSERV_RE = /^(?:[a-z0-9-]+\.)*amazonses\.com$/i;
const ENVELOPE_MARKER_REGEX = /<<<\s*\/?\s*EXTERNAL_UNTRUSTED_CONTENT\s*>>>/gi;

function verdictStatus(v?: { status?: string } | string): string {
  if (!v) return "";
  return (typeof v === "string" ? v : v.status || "").trim().toUpperCase();
}

function extractDomain(addrOrDomain: string): string {
  const cleaned = addrOrDomain.trim().toLowerCase().replace(/^.*@/, "");
  return cleaned.replace(/\.+$/, "");
}

function domainsAligned(a: string, b: string): boolean {
  const da = extractDomain(a);
  const db = extractDomain(b);
  if (!da || !db) return false;
  return da === db || da.endsWith(`.${db}`) || db.endsWith(`.${da}`);
}

function collectAuthResultsHeaders(headers: Map<string, any> | Record<string, any>): string[] {
  const raw =
    headers instanceof Map
      ? headers.get("authentication-results")
      : headers["authentication-results"];
  if (!raw) return [];
  const items = Array.isArray(raw) ? raw : [raw];
  return items
    .map((item) => {
      if (typeof item === "string") return item;
      if (item && typeof item === "object" && "text" in item) return String((item as any).text || "");
      if (item && typeof item === "object" && "value" in item) return String((item as any).value || "");
      return String(item || "");
    })
    .filter(Boolean);
}

/**
 * Stage 1: Cryptographic Origin Verification
 * Verifies trusted SES receipt verdicts (spfVerdict, dkimVerdict, dmarcVerdict === "PASS")
 * or trusted AWS SES Authentication-Results headers with DMARC + strict From: domain alignment.
 */
export function verifyCryptographicOrigin(
  headers: Map<string, any> | Record<string, any>,
  fromAddress?: string,
  sesReceipt?: SesReceiptVerdicts,
  trustedAuthServPattern: RegExp = DEFAULT_SES_AUTHSERV_RE
): {
  valid: boolean;
  details: string;
} {
  if (sesReceipt) {
    const spf = verdictStatus(sesReceipt.spfVerdict);
    const dkim = verdictStatus(sesReceipt.dkimVerdict);
    const dmarc = verdictStatus(sesReceipt.dmarcVerdict);
    if (spf === "PASS" && dkim === "PASS" && dmarc === "PASS") {
      return { valid: true, details: "SES receipt SPF, DKIM, and DMARC verdicts passed" };
    }
    return {
      valid: false,
      details: `SES receipt verdict check failed: spf=${spf || "NONE"}, dkim=${dkim || "NONE"}, dmarc=${dmarc || "NONE"}`,
    };
  }

  const headerEntries = collectAuthResultsHeaders(headers);
  if (headerEntries.length === 0) {
    return {
      valid: false,
      details: "Missing Authentication-Results header in email",
    };
  }

  // Filter for trusted SES authserv-id headers and evaluate the latest SES entry first.
  const trustedEntries = headerEntries.filter((entry) => {
    const authServ = entry.split(";")[0]?.trim().split(/\s+/)[0] || "";
    return trustedAuthServPattern.test(authServ);
  });

  if (trustedEntries.length === 0) {
    return {
      valid: false,
      details: "No trusted AWS SES Authentication-Results header found (untrusted/spoofed authserv-id)",
    };
  }

  const authResults = trustedEntries[trustedEntries.length - 1]!;
  const hasDkimPass = /\bdkim=pass\b/i.test(authResults);
  const hasSpfPass = /\bspf=pass\b/i.test(authResults);
  const hasDmarcPass = /\bdmarc=pass\b/i.test(authResults);

  if (!hasDkimPass || !hasSpfPass || !hasDmarcPass) {
    return {
      valid: false,
      details: `Cryptographic check failed: dkim=${hasDkimPass ? "pass" : "fail"}, spf=${hasSpfPass ? "pass" : "fail"}, dmarc=${hasDmarcPass ? "pass" : "fail"}`,
    };
  }

  // Enforce strict From: domain alignment against header.from / header.d / header.i claims.
  if (fromAddress) {
    const fromDomain = extractDomain(fromAddress);
    if (!fromDomain) {
      return { valid: false, details: "Unable to extract From domain for alignment verification" };
    }
    const headerFromMatch = authResults.match(/\bheader\.from=([^\s;]+)/i);
    const headerDMatch = authResults.match(/\bheader\.d=([^\s;]+)/i);
    const headerIMatch = authResults.match(/\bheader\.i=([^\s;]+)/i);

    const alignmentCandidates = [
      headerFromMatch?.[1],
      headerDMatch?.[1],
      headerIMatch?.[1],
    ].filter((v): v is string => Boolean(v));

    if (alignmentCandidates.length > 0 && alignmentCandidates.some((c) => !domainsAligned(c, fromDomain))) {
      return {
        valid: false,
        details: `Cryptographic From: domain alignment failed for '${fromDomain}' (${alignmentCandidates.join(", ")})`,
      };
    }
  }

  return { valid: true, details: "Trusted SES DKIM, SPF, DMARC, and From domain alignment passed" };
}

/**
 * Stage 2: Strict Sender Allowlist Validation (Fail-Closed + Dot-Bounded Domain Matching)
 */
export function verifySenderAllowlist(
  fromAddress: string | undefined,
  toAddress: string | undefined,
  allowedSenders: string[],
  allowedRecipientDomains?: string[]
): { valid: boolean; details: string } {
  if (!allowedSenders || allowedSenders.length === 0) {
    return { valid: false, details: "ALLOWED_EXTERNAL_SENDERS is empty (fail-closed)" };
  }

  if (!fromAddress) {
    return { valid: false, details: "Missing From address in email" };
  }

  const normalizedFrom = fromAddress.trim().toLowerCase();
  const isAllowedSender = allowedSenders.some(
    (allowed) => allowed.toLowerCase().trim() === normalizedFrom
  );

  if (!isAllowedSender) {
    return {
      valid: false,
      details: `Sender '${normalizedFrom}' is not in allowed external senders list: [${allowedSenders.join(", ")}]`,
    };
  }

  if (allowedRecipientDomains && allowedRecipientDomains.length > 0) {
    const toDomain = (toAddress || "").split("@")[1]?.toLowerCase().trim().replace(/\.+$/, "");
    if (!toDomain) {
      return {
        valid: false,
        details: "Missing valid To recipient domain while ALLOWED_RECIPIENT_DOMAINS is configured",
      };
    }
    const isAllowedDomain = allowedRecipientDomains.some((d) => {
      const dn = d.toLowerCase().trim().replace(/^\./, "").replace(/\.+$/, "");
      return Boolean(dn) && (toDomain === dn || toDomain.endsWith(`.${dn}`));
    });
    if (!isAllowedDomain) {
      return {
        valid: false,
        details: `Recipient domain '${toDomain}' is not in allowed domains: [${allowedRecipientDomains.join(", ")}]`,
      };
    }
  }

  return { valid: true, details: "Sender authorized" };
}

/**
 * Stage 3: Structural & MIME Normalization
 * Strips zero-width characters, tracking pixels, hidden HTML/CSS, and normalizes plain text
 */
export function normalizeContent(textBody?: string, htmlBody?: string): string {
  let content = textBody || "";

  if (!content && htmlBody) {
    // 1. Strip unsafe tags (scripts, styles, etc.)
    let sanitizedHtml = htmlBody.replace(UNSAFE_TAGS_REGEX, " ");
    // 2. Strip hidden CSS elements
    sanitizedHtml = sanitizedHtml.replace(HIDDEN_HTML_REGEX, " ");
    // 3. Strip tracking pixels
    sanitizedHtml = sanitizedHtml.replace(TRACKING_PIXEL_REGEX, " ");
    // 4. Strip basic HTML tags
    sanitizedHtml = sanitizedHtml
      .replace(/<br\s*\/?>/gi, "\n")
      .replace(/<\/p>/gi, "\n\n")
      .replace(/<[^>]+>/g, " ");
    content = sanitizedHtml;
  } else if (htmlBody) {
    // Text was provided, but ensure any embedded hidden/tracking elements in text are scrubbed
    content = content.replace(HIDDEN_HTML_REGEX, " ").replace(TRACKING_PIXEL_REGEX, " ");
  }

  // Strip zero-width & directional characters
  content = content.replace(ZERO_WIDTH_REGEX, "");

  // Normalize excessive whitespace while preserving paragraph lines
  content = content
    .split("\n")
    .map((line) => line.trim())
    .join("\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();

  return content;
}

/**
 * Stage 4: Heuristic Prompt Injection Scanner
 */
export function scanPromptInjection(
  subject: string,
  body: string
): { detected: boolean; signature?: string } {
  const combined = `${subject}\n${body}`;

  for (const regex of PROMPT_INJECTION_SIGNATURES) {
    if (regex.test(combined)) {
      return { detected: true, signature: regex.toString() };
    }
  }

  return { detected: false };
}

/**
 * Stage 5: Context Enveloping (Tainting)
 * Strips any breakout marker sequences before applying untrusted boundary delimiters.
 */
export function envelopeContent(sanitizedBody: string): string {
  const safeBody = sanitizedBody.replace(ENVELOPE_MARKER_REGEX, "[STRIPPED_MARKER]");
  return `<<<EXTERNAL_UNTRUSTED_CONTENT>>>\n${safeBody}\n<<</EXTERNAL_UNTRUSTED_CONTENT>>>`;
}

/**
 * Executes the full 5-stage defensive pipeline against parsed email
 */
export function processEmailThroughPipeline(
  messageId: string,
  parsedMail: ParsedMail,
  options: PipelineOptions
): PipelineVerdict {
  const timestamp = new Date().toISOString();
  const fromAddress = parsedMail.from?.value?.[0]?.address || "";
  const toAddress =
    Array.isArray(parsedMail.to) && parsedMail.to.length > 0
      ? parsedMail.to[0]?.value?.[0]?.address || ""
      : (parsedMail.to as any)?.value?.[0]?.address || "";
  const subject = parsedMail.subject || "(No Subject)";

  // Stage 1: Cryptographic Origin Verification
  const cryptoResult = verifyCryptographicOrigin(
    parsedMail.headers,
    fromAddress,
    options.sesReceipt,
    options.trustedAuthServPattern
  );
  if (!cryptoResult.valid) {
    return {
      status: "QUARANTINED",
      payload: {
        version: "1.0",
        messageId,
        timestamp,
        from: fromAddress,
        to: toAddress,
        subject,
        rejectionReason: "REJECTED_CRYPTO_AUTH",
        details: cryptoResult.details,
      },
    };
  }

  // Stage 2: Strict Sender Allowlist Validation
  const senderResult = verifySenderAllowlist(
    fromAddress,
    toAddress,
    options.allowedSenders,
    options.allowedRecipientDomains
  );
  if (!senderResult.valid) {
    return {
      status: "QUARANTINED",
      payload: {
        version: "1.0",
        messageId,
        timestamp,
        from: fromAddress,
        to: toAddress,
        subject,
        rejectionReason: "REJECTED_UNAUTHORIZED_SENDER",
        details: senderResult.details,
      },
    };
  }

  // Stage 3: Structural & MIME Normalization
  const normalizedBody = normalizeContent(
    parsedMail.text,
    parsedMail.html ? String(parsedMail.html) : undefined
  );

  // Stage 4: Heuristic Prompt Injection Scanner
  const injectionResult = scanPromptInjection(subject, normalizedBody);
  if (injectionResult.detected) {
    return {
      status: "QUARANTINED",
      payload: {
        version: "1.0",
        messageId,
        timestamp,
        from: fromAddress,
        to: toAddress,
        subject,
        rejectionReason: "REJECTED_PROMPT_INJECTION",
        details: `Detected prompt injection pattern: ${injectionResult.signature}`,
      },
    };
  }

  // Stage 5: Context Enveloping & Claim-Check Preparation
  const envelopedBody = envelopeContent(normalizedBody);

  const approvedPayload: ApprovedEmailPayload = {
    version: "1.0",
    messageId,
    from: fromAddress,
    to: toAddress,
    subject,
    timestamp,
    body: envelopedBody,
    headers: {
      from: fromAddress,
      to: toAddress,
      subject,
      "x-brainsos-security-verdict": "VERIFIED_OPERATOR",
      "x-brainsos-origin": "external-ses",
    },
    securityVerdict: "VERIFIED_OPERATOR",
    dkimVerdict: "pass",
    spfVerdict: "pass",
  };

  return {
    status: "APPROVED",
    payload: approvedPayload,
    claimCheck: (bucket: string): ClaimCheckMessage => ({
      version: "1.0",
      messageId,
      s3Bucket: bucket,
      s3Key: `approved/${messageId}.json`,
      from: fromAddress,
      to: toAddress,
      subject,
      timestamp,
    }),
  };
}
