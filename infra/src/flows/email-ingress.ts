/// <reference path="../../.sst/platform/config.d.ts" />
import { createMailIngressBucket } from "../components/s3.js";
import { createMailIngressQueues } from "../components/sqs.js";
import { setupSesIdentities, createMailReceiptRule } from "../components/ses.js";
import {
  createSesSenderPolicy,
  createMailSanitizerPolicy,
  createMailWorkerCredentials,
} from "../components/iam.js";

export interface EmailIngressFlowInput {
  stage: string;
  ingressDomains: string[];
  sesDomains: string[];
  zoneId: any;
  zoneName: string;
}

export function setupEmailIngressFlow(input: EmailIngressFlowInput) {
  const { stage, ingressDomains, sesDomains, zoneId, zoneName } = input;

  // 1. SES Domain Identities & Outbound Send Policy
  const sesIdentities = setupSesIdentities(sesDomains, zoneId, zoneName);
  const sesSenderPolicy = createSesSenderPolicy();

  // 2. Multi-Stage Ingress S3 Bucket with Expiration Lifecycles
  const ingressBucket = createMailIngressBucket(stage);

  // 3. Multi-Stage Ingress SQS Queue & Dead Letter Queue (DLQ)
  const ingressQueues = createMailIngressQueues(stage);

  // 4. SES Inbound Receipt Rule Set & Receipt Rules
  const mailReceipt = createMailReceiptRule(stage, ingressDomains, ingressBucket.bucketId);

  // 5. Cloud Sanitizer Lambda IAM Policy (Ticket #210)
  const sanitizerPolicy = createMailSanitizerPolicy(
    stage,
    ingressBucket.bucketArn,
    ingressQueues.queueArn
  );

  // 6. Local Workstation Worker IAM Policy & Credentials (Least Privilege)
  const workerCreds = createMailWorkerCredentials(
    stage,
    ingressBucket.bucketArn,
    ingressQueues.queueArn
  );

  return {
    sesIdentities,
    outputs: {
      mailIngressDomains: ingressDomains,
      mailIngressBucket: ingressBucket.bucketId,
      mailIngressQueueUrl: ingressQueues.queueUrl,
      mailIngressDlqUrl: ingressQueues.dlqUrl,
      mailIngressRuleSet: mailReceipt.ruleSetName,
      mailIngressRule: mailReceipt.ruleName,
      mailWorkerPolicyArn: workerCreds.policyArn,
      mailWorkerAccessKeyId: workerCreds.accessKeyId,
      mailWorkerSecretAccessKey: workerCreds.secretAccessKey,
      mailSanitizerPolicyArn: sanitizerPolicy.arn,
      sesSenderPolicyArn: sesSenderPolicy.arn,
    },
  };
}
