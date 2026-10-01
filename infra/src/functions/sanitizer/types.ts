export interface ApprovedEmailPayload {
  version: "1.0";
  messageId: string;
  from: string;
  to: string;
  subject: string;
  timestamp: string;
  body: string;
  headers: Record<string, string>;
  securityVerdict: "VERIFIED_OPERATOR";
  dkimVerdict: "pass";
  spfVerdict: "pass";
}

export interface QuarantinedEmailPayload {
  version: "1.0";
  messageId: string;
  timestamp: string;
  from?: string;
  to?: string;
  subject?: string;
  rejectionReason:
    | "REJECTED_CRYPTO_AUTH"
    | "REJECTED_UNAUTHORIZED_SENDER"
    | "REJECTED_PROMPT_INJECTION"
    | "REJECTED_PARSE_ERROR";
  details: string;
  rawSample?: string;
}

export interface ClaimCheckMessage {
  version: "1.0";
  messageId: string;
  s3Bucket: string;
  s3Key: string;
  from: string;
  to: string;
  subject: string;
  timestamp: string;
}

export type PipelineVerdict =
  | {
      status: "APPROVED";
      payload: ApprovedEmailPayload;
      claimCheck: (bucket: string) => ClaimCheckMessage;
    }
  | {
      status: "QUARANTINED";
      payload: QuarantinedEmailPayload;
    };
