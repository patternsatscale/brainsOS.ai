import {
  S3Client,
  GetObjectCommand,
  PutObjectCommand,
} from "@aws-sdk/client-s3";
import { SQSClient, SendMessageCommand } from "@aws-sdk/client-sqs";
import { simpleParser } from "mailparser";
import { Readable } from "stream";
import { processEmailThroughPipeline } from "./pipeline.js";

const s3Client = new S3Client({});
const sqsClient = new SQSClient({});

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

export interface S3Event {
  Records?: S3EventRecord[];
}

export async function handler(event: S3Event) {
  const allowedSenders = (process.env.ALLOWED_EXTERNAL_SENDERS || "patternsatscale@gmail.com")
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);

  const allowedRecipientDomains = process.env.ALLOWED_RECIPIENT_DOMAINS
    ? process.env.ALLOWED_RECIPIENT_DOMAINS.split(",").map((d) => d.trim()).filter(Boolean)
    : undefined;

  const queueUrl = process.env.INGRESS_QUEUE_URL;

  console.log(`[SANITIZER] Processing batch of ${event.Records?.length || 0} S3 event records`);

  for (const record of event.Records || []) {
    const bucket = record.s3.bucket.name;
    const key = decodeURIComponent(record.s3.object.key.replace(/\+/g, " "));

    console.log(`[SANITIZER] Received S3 object: s3://${bucket}/${key}`);

    // Expecting key under raw/
    if (!key.startsWith("raw/")) {
      console.log(`[SANITIZER] Skipping non-raw key: ${key}`);
      continue;
    }

    const messageId = key.replace(/^raw\//, "");

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

      // 3. Execute 5-Stage Defensive Gate
      const verdict = processEmailThroughPipeline(messageId, parsed, {
        allowedSenders,
        allowedRecipientDomains,
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

  return { statusCode: 200, status: "completed" };
}
