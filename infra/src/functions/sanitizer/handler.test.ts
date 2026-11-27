import { describe, it, expect, vi, beforeEach } from "vitest";
import { Readable } from "stream";

const { s3SendMock, sqsSendMock } = vi.hoisted(() => ({
  s3SendMock: vi.fn(),
  sqsSendMock: vi.fn(),
}));

vi.mock("@aws-sdk/client-s3", () => {
  class S3Client {
    send = s3SendMock;
  }
  class GetObjectCommand {
    constructor(public input: Record<string, unknown>) {}
  }
  class PutObjectCommand {
    constructor(public input: Record<string, unknown>) {}
  }
  return { S3Client, GetObjectCommand, PutObjectCommand };
});

vi.mock("@aws-sdk/client-sqs", () => {
  class SQSClient {
    send = sqsSendMock;
  }
  class SendMessageCommand {
    constructor(public input: Record<string, unknown>) {}
  }
  return { SQSClient, SendMessageCommand };
});

import { handler, isValidMessageId } from "./handler.js";

function buildRawMime(options?: { authResults?: string }): string {
  const authLine = options?.authResults
    ? `Authentication-Results: ${options.authResults}\r\n`
    : "";
  return (
    `From: patternsatscale@gmail.com\r\n` +
    `To: bawtford@local.brainsos.ai\r\n` +
    `Subject: Operator Directive\r\n` +
    authLine +
    `MIME-Version: 1.0\r\n` +
    `Content-Type: text/plain; charset=UTF-8\r\n\r\n` +
    `Proceed with deployment check.`
  );
}

describe("Sanitizer Lambda Handler (#401)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    process.env.ALLOWED_EXTERNAL_SENDERS = "patternsatscale@gmail.com";
    process.env.ALLOWED_RECIPIENT_DOMAINS = "local.brainsos.ai,brainsos.ai";
    process.env.MAIL_INGRESS_BUCKET = "brainsos-ingress-test";
    process.env.INGRESS_QUEUE_URL = "https://sqs.us-east-1.amazonaws.com/123456/ingress";
  });

  it("validates messageId allowlist and blocks traversal/dots/control characters", () => {
    expect(isValidMessageId("0100018f-abc_123.eml")).toBe(true);
    expect(isValidMessageId("..")).toBe(false);
    expect(isValidMessageId(".")).toBe(false);
    expect(isValidMessageId("foo..bar")).toBe(false);
    expect(isValidMessageId("../secrets/evil")).toBe(false);
    expect(isValidMessageId("a/b")).toBe(false);
    expect(isValidMessageId("bad\r\nid")).toBe(false);
    expect(isValidMessageId("")).toBe(false);
  });

  it("rejects invalid S3 and SES messageIds before making any S3 or SQS calls", async () => {
    const badS3Keys = [
      "raw/../secrets/evil",
      "raw/..",
      "raw/.",
      "raw/foo..bar",
      "raw/nested/path",
      "raw/bad%0d%0aid",
      "raw/",
      "raw/%ZZ",
    ];

    for (const key of badS3Keys) {
      const res = await handler({
        Records: [{ s3: { bucket: { name: "bkt" }, object: { key, size: 10 } } }],
      });
      expect(res.statusCode).toBe(400);
    }

    const sesRes = await handler({
      Records: [
        {
          ses: {
            mail: { messageId: "../evil" },
            receipt: {
              spfVerdict: { status: "PASS" },
              dkimVerdict: { status: "PASS" },
              dmarcVerdict: { status: "PASS" },
            },
          },
        },
      ],
    });
    expect(sesRes.statusCode).toBe(400);
    expect(s3SendMock).not.toHaveBeenCalled();
    expect(sqsSendMock).not.toHaveBeenCalled();
  });

  it("approves SES event when spfVerdict, dkimVerdict, and dmarcVerdict all PASS", async () => {
    const rawMime = buildRawMime();
    s3SendMock.mockResolvedValueOnce({ Body: Readable.from(Buffer.from(rawMime)) });
    s3SendMock.mockResolvedValueOnce({});
    sqsSendMock.mockResolvedValueOnce({});

    const res = await handler({
      Records: [
        {
          eventSource: "aws:ses",
          ses: {
            mail: { messageId: "0100018f-abc_123.eml" },
            receipt: {
              spfVerdict: { status: "PASS" },
              dkimVerdict: { status: "PASS" },
              dmarcVerdict: { status: "PASS" },
            },
          },
        },
      ],
    });

    expect(res.statusCode).toBe(200);
    expect(s3SendMock).toHaveBeenCalledTimes(2);
    expect(s3SendMock.mock.calls[0]?.[0]?.input).toEqual({
      Bucket: "brainsos-ingress-test",
      Key: "raw/0100018f-abc_123.eml",
    });
    expect(s3SendMock.mock.calls[1]?.[0]?.input?.Key).toBe(
      "approved/0100018f-abc_123.eml.json"
    );
    expect(sqsSendMock).toHaveBeenCalledTimes(1);
    const sqsBody = JSON.parse(String(sqsSendMock.mock.calls[0]?.[0]?.input?.MessageBody));
    expect(sqsBody.s3Key).toBe("approved/0100018f-abc_123.eml.json");
  });

  it("quarantines SES event when any receipt verdict fails even if MIME headers claim pass", async () => {
    const rawMime = buildRawMime({
      authResults:
        "mx.amazonses.com; dkim=pass header.d=gmail.com; spf=pass; dmarc=pass header.from=gmail.com",
    });

    for (const badReceipt of [
      { spfVerdict: { status: "PASS" }, dkimVerdict: { status: "FAIL" }, dmarcVerdict: { status: "PASS" } },
      { spfVerdict: { status: "PASS" }, dkimVerdict: { status: "GRAY" }, dmarcVerdict: { status: "PASS" } },
      { spfVerdict: { status: "DISABLED" }, dkimVerdict: { status: "PASS" }, dmarcVerdict: { status: "PASS" } },
      { spfVerdict: { status: "PASS" }, dkimVerdict: { status: "PASS" } },
    ]) {
      vi.clearAllMocks();
      s3SendMock.mockResolvedValueOnce({ Body: Readable.from(Buffer.from(rawMime)) });
      s3SendMock.mockResolvedValueOnce({});

      const res = await handler({
        Records: [
          {
            eventSource: "aws:ses",
            ses: {
              mail: { messageId: "msg-bad-verdict" },
              receipt: badReceipt,
            },
          },
        ],
      });

      expect(res.statusCode).toBe(200);
      expect(s3SendMock).toHaveBeenCalledTimes(2);
      expect(s3SendMock.mock.calls[1]?.[0]?.input?.Key).toBe("quarantine/msg-bad-verdict.json");
      const qBody = JSON.parse(String(s3SendMock.mock.calls[1]?.[0]?.input?.Body));
      expect(qBody.rejectionReason).toBe("REJECTED_CRYPTO_AUTH");
      expect(sqsSendMock).not.toHaveBeenCalled();
    }
  });

  it("fails closed when S3Event lacks SES receipt verdicts", async () => {
    const rawMime = buildRawMime({
      authResults:
        "mx.amazonses.com; dkim=pass header.d=gmail.com; spf=pass; dmarc=pass header.from=gmail.com",
    });
    s3SendMock.mockResolvedValueOnce({ Body: Readable.from(Buffer.from(rawMime)) });
    s3SendMock.mockResolvedValueOnce({});

    const res = await handler({
      Records: [
        {
          s3: {
            bucket: { name: "brainsos-ingress-test" },
            object: { key: "raw/s3-only-msg", size: 256 },
          },
        },
      ],
    });

    expect(res.statusCode).toBe(200);
    expect(s3SendMock).toHaveBeenCalledTimes(2);
    expect(s3SendMock.mock.calls[1]?.[0]?.input?.Key).toBe("quarantine/s3-only-msg.json");
    const qBody = JSON.parse(String(s3SendMock.mock.calls[1]?.[0]?.input?.Body));
    expect(qBody.rejectionReason).toBe("REJECTED_CRYPTO_AUTH");
    expect(sqsSendMock).not.toHaveBeenCalled();
  });

  it("rejects traversal, double-encoded, nested, empty, non-raw, and control-char SES receipt.action.objectKey before S3/SQS calls (#401)", async () => {
    const badObjectKeys = [
      "raw/../approved/pwn",
      "raw/%2e%2e/secrets",
      "raw/%252e%252e/secrets",
      "raw/foo..bar",
      "raw/.",
      "raw/a/b",
      "raw/bad\r\nid",
      "raw/bad\u0000id",
      "raw/",
      "raw/%ZZ",
      "other/valid-id",
      "/raw/valid-id",
      "",
    ];

    for (const objectKey of badObjectKeys) {
      vi.clearAllMocks();
      const res = await handler({
        Records: [
          {
            eventSource: "aws:ses",
            ses: {
              mail: { messageId: "valid-msg-id" },
              receipt: {
                spfVerdict: { status: "PASS" },
                dkimVerdict: { status: "PASS" },
                dmarcVerdict: { status: "PASS" },
                action: {
                  bucketName: "brainsos-ingress-test",
                  objectKey,
                },
              },
            },
          },
        ],
      });
      expect(res.statusCode).toBe(400);
      expect(s3SendMock).not.toHaveBeenCalled();
      expect(sqsSendMock).not.toHaveBeenCalled();
    }

    vi.clearAllMocks();
    const rawMime = buildRawMime();
    s3SendMock.mockResolvedValueOnce({ Body: Readable.from(Buffer.from(rawMime)) });
    s3SendMock.mockResolvedValueOnce({});
    sqsSendMock.mockResolvedValueOnce({});

    const validRes = await handler({
      Records: [
        {
          eventSource: "aws:ses",
          ses: {
            mail: { messageId: "0100018f-abc_123.eml" },
            receipt: {
              spfVerdict: { status: "PASS" },
              dkimVerdict: { status: "PASS" },
              dmarcVerdict: { status: "PASS" },
              action: {
                bucketName: "brainsos-ingress-test",
                objectKey: "raw/0100018f-abc_123.eml",
              },
            },
          },
        },
      ],
    });
    expect(validRes.statusCode).toBe(200);
    expect(s3SendMock).toHaveBeenCalledTimes(2);
    expect(sqsSendMock).toHaveBeenCalledTimes(1);
  });

  it("rejects mismatched S3 bucket in both S3Event and SesEvent when MAIL_INGRESS_BUCKET is set (#401)", async () => {
    const s3RawRes = await handler({
      Records: [
        {
          s3: {
            bucket: { name: "attacker-bucket" },
            object: { key: "raw/valid-id", size: 256 },
          },
        },
      ],
    });
    expect(s3RawRes.statusCode).toBe(400);
    expect(s3SendMock).not.toHaveBeenCalled();
    expect(sqsSendMock).not.toHaveBeenCalled();

    const s3ApprovedRes = await handler({
      Records: [
        {
          s3: {
            bucket: { name: "attacker-bucket" },
            object: { key: "approved/valid-id.json", size: 256 },
          },
        },
      ],
    });
    expect(s3ApprovedRes.statusCode).toBe(400);
    expect(s3SendMock).not.toHaveBeenCalled();

    const sesBadBucketRes = await handler({
      Records: [
        {
          eventSource: "aws:ses",
          ses: {
            mail: { messageId: "valid-id" },
            receipt: {
              spfVerdict: { status: "PASS" },
              dkimVerdict: { status: "PASS" },
              dmarcVerdict: { status: "PASS" },
              action: {
                bucketName: "attacker-bucket",
              },
            },
          },
        },
      ],
    });
    expect(sesBadBucketRes.statusCode).toBe(400);
    expect(s3SendMock).not.toHaveBeenCalled();
    expect(sqsSendMock).not.toHaveBeenCalled();

    const sesEmptyBucketRes = await handler({
      Records: [
        {
          eventSource: "aws:ses",
          ses: {
            mail: { messageId: "valid-id" },
            receipt: {
              spfVerdict: { status: "PASS" },
              dkimVerdict: { status: "PASS" },
              dmarcVerdict: { status: "PASS" },
              action: {
                bucketName: "",
              },
            },
          },
        },
      ],
    });
    expect(sesEmptyBucketRes.statusCode).toBe(400);
    expect(s3SendMock).not.toHaveBeenCalled();
  });
});
