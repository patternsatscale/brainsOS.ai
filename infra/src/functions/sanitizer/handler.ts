import {
  S3Client,
  GetObjectCommand,
  PutObjectCommand,
} from "@aws-sdk/client-s3";
import { SQSClient, SendMessageCommand } from "@aws-sdk/client-sqs";
import { simpleParser } from "mailparser";
import { Readable } from "stream";
import { processEmailThroughPipeline, SesReceiptVerdicts } from "./pipeline.js";

const s3Client = new S3Client({});
const sqsClient = new SQSClient({});

export const MESSAGE_ID_REGEX = /^[A-Za-z0-9._-]+$/;

export interface S3EventRecord {
  s3: {
    bucket: {
      name: string;
    };
    object: {
      key: string;
      size: number;
    };
  };
}

export interface SesVerdict {
  status?: string;
}

export interface SesReceipt {
  spfVerdict?: SesVerdict | string;
  dkimVerdict?: SesVerdict | string;
  dmarcVerdict?: SesVerdict | string;
  spamVerdict?: SesVerdict | string;
  virusVerdict?: SesVerdict | string;
  action?: {
    type?: string;
    bucketName?: string;
    objectKey?: string;
    objectKeyPrefix?: string;
    functionArn?: string;
  };
}

export interface SesEventRecord {
  eventSource?: string;
  ses: {
    mail: {
      messageId: string;
      source?: string;
      destination?: string[];
    };
    receipt?: SesReceipt;
  };
}

export type IngressEventRecord = SesEventRecord | S3EventRecord;

export interface S3Event {
  Records?: S3EventRecord[];
}

export interface SesEvent {
  Records?: IngressEventRecord[];
}

export function isValidMessageId(messageId: string): boolean {
  return (
    Boolean(messageId) &&
    MESSAGE_ID_REGEX.test(messageId) &&
    !messageId.includes("..") &&
    messageId !== "."
  );
}

function decodeS3Key(rawKey: string): string | null {
  try {
    return decodeURIComponent(rawKey.replace(/\+/g, " "));
  } catch {
    return null;
  }
}

export type ExtractedCoordinates =
  | {
      status: "ok";
      bucket: string;
      key: string;
      messageId: string;
      sesReceipt: SesReceiptVerdicts;
    }
  | { status: "skip"; reason: string }
  | { status: "invalid"; reason: string };

export function extractS3Coordinates(
  record: IngressEventRecord,
  defaultBucket: string
): ExtractedCoordinates {
  if ("ses" in record && record.ses) {
    const messageId = (record.ses.mail?.messageId || "").trim();
    if (!isValidMessageId(messageId)) {
      return {
        status: "invalid",
        reason: `Rejected invalid SES messageId: ${JSON.stringify(messageId)}`,
      };
    }

    const receipt = record.ses.receipt;
    const rawBucket =
      receipt?.action?.bucketName !== undefined
        ? receipt.action.bucketName
        : defaultBucket;
    const bucket = rawBucket.trim();
    if (!bucket) {
      return {
        status: "invalid",
        reason: `Missing S3 bucket for messageId ${messageId}`,
      };
    }
    if (defaultBucket && bucket !== defaultBucket) {
      return {
        status: "invalid",
        reason: `Rejected mismatched SES S3 bucket ${JSON.stringify(bucket)} (expected ${JSON.stringify(defaultBucket)})`,
      };
    }

    let key: string;
    if (receipt?.action?.objectKey !== undefined) {
      const decoded = decodeS3Key(receipt.action.objectKey);
      if (decoded === null || !decoded.startsWith("raw/")) {
        return {
          status: "invalid",
          reason: `Rejected invalid SES action objectKey: ${String(receipt.action.objectKey)}`,
        };
      }
      const objectMessageId = decoded.replace(/^raw\//, "");
      if (!isValidMessageId(objectMessageId)) {
        return {
          status: "invalid",
          reason: `Rejected invalid SES action objectKey messageId: ${JSON.stringify(decoded)}`,
        };
      }
      key = decoded;
    } else {
      key = `raw/${messageId}`;
    }

    return {
      status: "ok",
      bucket,
      key,
      messageId,
      // Pass a defined sesReceipt object so pipeline.ts always enforces authoritative SES verdicts.
      sesReceipt: {
        spfVerdict: receipt?.spfVerdict,
        dkimVerdict: receipt?.dkimVerdict,
        dmarcVerdict: receipt?.dmarcVerdict,
      },
    };
  }

  if ("s3" in record && record.s3) {
    const bucket = (record.s3.bucket?.name || "").trim();
    if (!bucket) {
      return {
        status: "invalid",
        reason: "Missing S3 bucket in S3 event record",
      };
    }
    if (defaultBucket && bucket !== defaultBucket) {
      return {
        status: "invalid",
        reason: `Rejected mismatched S3 bucket ${JSON.stringify(bucket)} (expected ${JSON.stringify(defaultBucket)})`,
      };
    }

    const decoded = decodeS3Key(record.s3.object?.key || "");
    if (decoded === null) {
      return {
        status: "invalid",
        reason: "Rejected malformed URL-encoded S3 key",
      };
    }

    // Expecting key under raw/
    if (!decoded.startsWith("raw/")) {
      return {
        status: "skip",
        reason: `Skipping non-raw key: ${decoded}`,
      };
    }

    const messageId = decoded.replace(/^raw\//, "");
    if (!isValidMessageId(messageId)) {
      return {
        status: "invalid",
        reason: `Rejected invalid S3 messageId from key: ${JSON.stringify(decoded)}`,
      };
    }

    return {
      status: "ok",
      bucket,
      key: decoded,
      messageId,
      // Fail closed: S3Event without SES receipt verdicts must never fall back to MIME headers.
      sesReceipt: {},
    };
  }

  return {
    status: "invalid",
    reason: "Rejected unrecognized ingress event record",
  };
}

export async function handler(event: SesEvent | S3Event) {
  const allowedSenders = (process.env.ALLOWED_EXTERNAL_SENDERS || "")
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);

  const allowedRecipientDomains = process.env.ALLOWED_RECIPIENT_DOMAINS
    ? process.env.ALLOWED_RECIPIENT_DOMAINS.split(",")
        .map((d) => d.trim())
        .filter(Boolean)
    : undefined;

  const queueUrl = process.env.INGRESS_QUEUE_URL;
  const defaultBucket = (process.env.MAIL_INGRESS_BUCKET || "").trim();

  const records = event.Records || [];
  console.log(`[SANITIZER] Processing batch of ${records.length} ingress event records`);

  let hasInvalidRecord = false;

  for (const record of records) {
    const coords = extractS3Coordinates(record, defaultBucket);
    if (coords.status === "invalid") {
      console.error(`[SANITIZER] ${coords.reason}`);
      hasInvalidRecord = true;
      continue;
    }
    if (coords.status === "skip") {
      console.log(`[SANITIZER] ${coords.reason}`);
      continue;
    }
    const { bucket, key, messageId, sesReceipt } = coords;

    console.log(`[SANITIZER] Received ingress object: s3://${bucket}/${key}`);

    try {
      // 1. Fetch raw MIME from S3
      const getObjResp = await s3Client.send(
        new GetObjectCommand({
          Bucket: bucket,
          Key: key,
        })
      );

      if (!getObjResp.Body) {
        throw new Error(`Empty body returned for s3://${bucket}/${key}`);
      }

      // Convert body to Buffer/stream for mailparser
      let rawStream: Readable;
      if (getObjResp.Body instanceof Readable) {
        rawStream = getObjResp.Body;
      } else {
        const bytes = await getObjResp.Body.transformToByteArray();
        rawStream = Readable.from(Buffer.from(bytes));
      }

      // 2. Parse MIME structure
      const parsed = await simpleParser(rawStream);

      // 3. Execute 5-Stage Defensive Gate with authoritative SES receipt verdicts
      const verdict = processEmailThroughPipeline(messageId, parsed, {
        allowedSenders,
        allowedRecipientDomains,
        sesReceipt,
      });

      if (verdict.status === "APPROVED") {
        console.log(`[SANITIZER] [VERDICT: APPROVED] Email ${messageId} passed all 5 defensive gates`);

        const approvedKey = `approved/${messageId}.json`;
        await s3Client.send(
          new PutObjectCommand({
            Bucket: bucket,
            Key: approvedKey,
            Body: JSON.stringify(verdict.payload, null, 2),
            ContentType: "application/json",
          })
        );

        if (queueUrl) {
          const claimCheck = verdict.claimCheck(bucket);
          await sqsClient.send(
            new SendMessageCommand({
              QueueUrl: queueUrl,
              MessageBody: JSON.stringify(claimCheck),
            })
          );
          console.log(`[SANITIZER] Enqueued claim check to SQS: ${queueUrl}`);
        } else {
          console.warn("[SANITIZER] INGRESS_QUEUE_URL is not configured; SQS emission skipped.");
        }
      } else {
        console.warn(
          `[SANITIZER] [VERDICT: QUARANTINED] Email ${messageId} rejected: ${verdict.payload.rejectionReason} - ${verdict.payload.details}`
        );

        const quarantineKey = `quarantine/${messageId}.json`;
        await s3Client.send(
          new PutObjectCommand({
            Bucket: bucket,
            Key: quarantineKey,
            Body: JSON.stringify(verdict.payload, null, 2),
            ContentType: "application/json",
          })
        );
      }
    } catch (err: any) {
      console.error(`[SANITIZER] Critical error processing s3://${bucket}/${key}:`, err);
      // Write error record to quarantine
      const quarantineKey = `quarantine/${messageId}.json`;
      await s3Client.send(
        new PutObjectCommand({
          Bucket: bucket,
          Key: quarantineKey,
          Body: JSON.stringify(
            {
              version: "1.0",
              messageId,
              timestamp: new Date().toISOString(),
              rejectionReason: "REJECTED_PARSE_ERROR",
              details: err?.message || String(err),
            },
            null,
            2
          ),
          ContentType: "application/json",
        })
      );
    }
  }

  if (hasInvalidRecord) {
    return { statusCode: 400, status: "rejected" };
  }

  return { statusCode: 200, status: "completed" };
}
