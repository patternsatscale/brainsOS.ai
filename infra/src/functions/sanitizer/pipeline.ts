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

function domainsAligned(candidate: string, fromDomain: string): boolean {
  const cand = extractDomain(candidate);
  const from = extractDomain(fromDomain);
  if (!cand || !from) return false;
  return from === cand || from.endsWith(`.${cand}`);
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

function stripRfc5322Comments(input: string): string {
  let out = "";
  let parenDepth = 0;
  let inQuotes = false;

  for (let i = 0; i < input.length; i++) {
    const ch = input[i]!;
    if (parenDepth > 0) {
      if (ch === "\\") {
        i++;
      } else if (ch === "(") {
        parenDepth++;
      } else if (ch === ")") {
        parenDepth--;
        if (parenDepth === 0) {
          out += " ";
        }
      }
      continue;
    }

    if (inQuotes) {
      out += ch;
      if (ch === "\\") {
        if (i + 1 < input.length) {
          out += input[i + 1]!;
          i++;
        }
      } else if (ch === '"') {
        inQuotes = false;
      }
      continue;
    }

    if (ch === '"') {
      inQuotes = true;
      out += ch;
    } else if (ch === "(") {
      parenDepth = 1;
    } else {
      out += ch;
    }
  }

  return out;
}

function stripQuotedStrings(input: string): string {
  let out = "";
  let inQuotes = false;

  for (let i = 0; i < input.length; i++) {
    const ch = input[i]!;
    if (inQuotes) {
      if (ch === "\\") {
        i++;
      } else if (ch === '"') {
        inQuotes = false;
      }
      continue;
    }

    if (ch === '"') {
      inQuotes = true;
    } else {
      out += ch;
    }
  }

  return out;
}

function splitAuthClauses(cleaned: string): string[] {
  const clauses: string[] = [];
  let current = "";
  let inQuotes = false;

  for (let i = 0; i < cleaned.length; i++) {
    const ch = cleaned[i]!;
    if (inQuotes) {
      current += ch;
      if (ch === "\\") {
        if (i + 1 < cleaned.length) {
          current += cleaned[i + 1]!;
          i++;
        }
      } else if (ch === '"') {
        inQuotes = false;
      }
      continue;
    }

    if (ch === '"') {
      inQuotes = true;
      current += ch;
    } else if (ch === ";") {
      clauses.push(current.trim());
      current = "";
    } else {
      current += ch;
    }
  }

  if (current.trim() || clauses.length > 0) {
    clauses.push(current.trim());
  }

  return clauses.filter(Boolean);
}

function evaluateMechanismVerdict(
  resultClauses: string[],
  mechanism: "dkim" | "spf" | "dmarc"
): boolean {
  const headRe = new RegExp(
    `^${mechanism}(?:/[a-z0-9_-]+)?=([a-z0-9_-]+)(?=\\s|$)`,
    "i"
  );
  const nonPassRe = new RegExp(
    `\\b${mechanism}=(?:fail|softfail|permerror|temperror|none|neutral|policy)\\b`,
    "i"
  );

  let hasPass = false;
  let hasNonPass = false;

  for (const clause of resultClauses) {
    const unquoted = stripQuotedStrings(clause);
    if (nonPassRe.test(unquoted)) {
      hasNonPass = true;
    }
    const match = clause.trim().match(headRe);
    if (match) {
      if (match[1]!.toLowerCase() === "pass") {
        hasPass = true;
      } else {
        hasNonPass = true;
      }
    }
  }

  return hasPass && !hasNonPass;
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

  // Strip RFC 5322 comments before checking trusted authserv-id and evaluating the topmost entry.
  const trustedEntries = headerEntries
    .map((entry) => stripRfc5322Comments(entry))
    .filter((cleaned) => {
      const firstClause = splitAuthClauses(cleaned)[0] || "";
      const authServ = firstClause.trim().split(/\s+/)[0] || "";
      return trustedAuthServPattern.test(authServ);
    });

  if (trustedEntries.length === 0) {
    return {
      valid: false,
      details: "No trusted AWS SES Authentication-Results header found (untrusted/spoofed authserv-id)",
    };
  }

  const authResults = trustedEntries[0]!;
  const resultClauses = splitAuthClauses(authResults).slice(1);
  const hasDkimPass = evaluateMechanismVerdict(resultClauses, "dkim");
  const hasSpfPass = evaluateMechanismVerdict(resultClauses, "spf");
  const hasDmarcPass = evaluateMechanismVerdict(resultClauses, "dmarc");

  if (!hasDkimPass || !hasSpfPass || !hasDmarcPass) {
    return {
      valid: false,
      details: `Cryptographic check failed: dkim=${hasDkimPass ? "pass" : "fail"}, spf=${hasSpfPass ? "pass" : "fail"}, dmarc=${hasDmarcPass ? "pass" : "fail"}`,
    };
  }

  // Enforce strict From: domain alignment against unquoted, comment-stripped header.from / header.d / header.i claims.
  if (fromAddress) {
    const fromDomain = extractDomain(fromAddress);
    if (!fromDomain) {
      return { valid: false, details: "Unable to extract From domain for alignment verification" };
    }
    const unquotedAuthResults = stripQuotedStrings(authResults);
    const headerFromMatch = unquotedAuthResults.match(/\bheader\.from=([^\s;]+)/i);
    const headerDMatch = unquotedAuthResults.match(/\bheader\.d=([^\s;]+)/i);
    const headerIMatch = unquotedAuthResults.match(/\bheader\.i=([^\s;]+)/i);

    const alignmentCandidates = [
      headerFromMatch?.[1],
      headerDMatch?.[1],
      headerIMatch?.[1],
    ].filter((v): v is string => Boolean(v));

    if (alignmentCandidates.length === 0) {
      return {
        valid: false,
        details: `Cryptographic From: alignment claims missing (header.from/header.d/header.i) for '${fromDomain}'`,
      };
    }

    if (alignmentCandidates.some((c) => !domainsAligned(c, fromDomain))) {
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

function extractSingleFromAddress(parsedMail: ParsedMail): {
  valid: boolean;
  address: string;
  isMultiOrGroup?: boolean;
  rawFrom?: string;
  details?: string;
} {
  const fromHeaderLines = Array.isArray(parsedMail.headerLines)
    ? parsedMail.headerLines.filter((h) => h.key?.toLowerCase() === "from")
    : [];
  if (fromHeaderLines.length > 1) {
    return {
      valid: false,
      address: "",
      isMultiOrGroup: true,
      rawFrom: parsedMail.from?.text || "",
      details: `Multiple From headers are not allowed (found ${fromHeaderLines.length})`,
    };
  }

  const rawHeaderFrom =
    parsedMail.headers instanceof Map ? parsedMail.headers.get("from") : undefined;
  if (Array.isArray(rawHeaderFrom) && rawHeaderFrom.length > 1) {
    return {
      valid: false,
      address: "",
      isMultiOrGroup: true,
      rawFrom: parsedMail.from?.text || "",
      details: `Multiple From headers are not allowed (found ${rawHeaderFrom.length})`,
    };
  }

  const fromEntries = parsedMail.from?.value ?? [];
  if (fromEntries.length > 1) {
    return {
      valid: false,
      address: "",
      isMultiOrGroup: true,
      rawFrom:
        parsedMail.from?.text ||
        fromEntries
          .map((e) => e.address)
          .filter(Boolean)
          .join(", "),
      details: `Multiple From addresses are not allowed (found ${fromEntries.length})`,
    };
  }

  if (fromEntries.some((entry) => Boolean((entry as { group?: unknown[] })?.group?.length))) {
    return {
      valid: false,
      address: "",
      isMultiOrGroup: true,
      rawFrom: parsedMail.from?.text || "",
      details: "Group syntax in From header is not allowed",
    };
  }

  const address = (fromEntries[0]?.address || "").trim();
  if (!address) {
    return {
      valid: false,
      address: "",
      isMultiOrGroup: false,
      details: "Missing From address in email",
    };
  }

  return { valid: true, address };
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
  const fromCheck = extractSingleFromAddress(parsedMail);
  const fromAddress = fromCheck.address;
  const toAddress =
    Array.isArray(parsedMail.to) && parsedMail.to.length > 0
      ? parsedMail.to[0]?.value?.[0]?.address || ""
      : (parsedMail.to as any)?.value?.[0]?.address || "";
  const subject = parsedMail.subject || "(No Subject)";

  if (!fromCheck.valid && fromCheck.isMultiOrGroup) {
    return {
      status: "QUARANTINED",
      payload: {
        version: "1.0",
        messageId,
        timestamp,
        from: fromCheck.rawFrom || "",
        to: toAddress,
        subject,
        rejectionReason: "REJECTED_UNAUTHORIZED_SENDER",
        details: fromCheck.details || "Multiple or invalid From addresses are not permitted",
      },
    };
  }

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
