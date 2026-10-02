import { ParsedMail } from "mailparser";
import {
  ApprovedEmailPayload,
  ClaimCheckMessage,
  PipelineVerdict,
  QuarantinedEmailPayload,
} from "./types.js";

export interface PipelineOptions {
  allowedSenders: string[];
  allowedRecipientDomains?: string[];
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

/**
 * Stage 1: Cryptographic Origin Verification
 * Inspects SES Authentication-Results header for dkim=pass and spf=pass
 */
export function verifyCryptographicOrigin(headers: Map<string, any> | Record<string, any>): {
  valid: boolean;
  details: string;
} {
  let authResults = "";

  if (headers instanceof Map) {
    authResults = String(headers.get("authentication-results") || "");
  } else {
    authResults = String(headers["authentication-results"] || "");
  }

  if (!authResults) {
    return {
      valid: false,
      details: "Missing Authentication-Results header in email",
    };
  }

  const hasDkimPass = /\bdkim=pass\b/i.test(authResults);
  const hasSpfPass = /\bspf=pass\b/i.test(authResults);

  if (!hasDkimPass || !hasSpfPass) {
    return {
      valid: false,
      details: `Cryptographic check failed: dkim=${hasDkimPass ? "pass" : "fail"}, spf=${hasSpfPass ? "pass" : "fail"}`,
    };
  }

  return { valid: true, details: "DKIM and SPF verified pass" };
}

/**
 * Stage 2: Strict Sender Allowlist Validation
 */
export function verifySenderAllowlist(
  fromAddress: string | undefined,
  toAddress: string | undefined,
  allowedSenders: string[],
  allowedRecipientDomains?: string[]
): { valid: boolean; details: string } {
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

  if (allowedRecipientDomains && allowedRecipientDomains.length > 0 && toAddress) {
    const toDomain = toAddress.split("@")[1]?.toLowerCase().trim();
    if (toDomain) {
      const isAllowedDomain = allowedRecipientDomains.some((d) =>
        toDomain.endsWith(d.toLowerCase().trim())
      );
      if (!isAllowedDomain) {
        return {
          valid: false,
          details: `Recipient domain '${toDomain}' is not in allowed domains: [${allowedRecipientDomains.join(", ")}]`,
        };
      }
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
 */
export function envelopeContent(sanitizedBody: string): string {
  return `<<<EXTERNAL_UNTRUSTED_CONTENT>>>\n${sanitizedBody}\n<<</EXTERNAL_UNTRUSTED_CONTENT>>>`;
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
  const cryptoResult = verifyCryptographicOrigin(parsedMail.headers);
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
