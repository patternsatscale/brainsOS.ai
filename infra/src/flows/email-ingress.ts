/// <reference path="../../.sst/platform/config.d.ts" />
import { createMailIngressBucket } from "../components/s3.js";
import { createMailIngressQueues } from "../components/sqs.js";
import { setupSesIdentities, createMailReceiptRule } from "../components/ses.js";
import {
  createSesSenderPolicy,
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
  const cleanStage = stage.toLowerCase().replace(/[^a-zA-Z0-9]/g, "-");

  // 1. SES Domain Identities & Outbound Send Policy
  const region = process.env.BRAINSOS_INFRA_AWS_REGION || process.env.AWS_REGION || "us-east-1";
  const allSesDomains = Array.from(new Set([...sesDomains, ...ingressDomains]));
  const sesIdentities = setupSesIdentities(allSesDomains, zoneId, zoneName, region);
  const sesSenderPolicy = createSesSenderPolicy();

  // 2. Multi-Stage Ingress S3 Bucket with Expiration Lifecycles
  const ingressBucket = createMailIngressBucket(stage);

  // 3. Multi-Stage Ingress SQS Queue & Dead Letter Queue (DLQ)
  const ingressQueues = createMailIngressQueues(stage);

  // 4. Ingress Sanitizer Lambda (Ticket #210, #401)
  const sanitizerLambda = new sst.aws.Function(`BrainsOSMailSanitizer-${cleanStage}`, {
    handler: "src/functions/sanitizer/handler.handler",
    environment: {
      ALLOWED_EXTERNAL_SENDERS:
        process.env.ALLOWED_EXTERNAL_SENDERS || "patternsatscale@gmail.com",
      ALLOWED_RECIPIENT_DOMAINS: ingressDomains.join(","),
      INGRESS_QUEUE_URL: ingressQueues.queueUrl,
      MAIL_INGRESS_BUCKET: ingressBucket.bucketId,
    },
    permissions: [
      {
        actions: ["s3:GetObject", "s3:DeleteObject"],
        resources: [$interpolate`${ingressBucket.bucketArn}/raw/*`],
      },
      {
        actions: ["s3:PutObject"],
        resources: [
          $interpolate`${ingressBucket.bucketArn}/approved/*`,
          $interpolate`${ingressBucket.bucketArn}/quarantine/*`,
        ],
      },
      {
        actions: ["sqs:SendMessage"],
        resources: [ingressQueues.queueArn],
      },
    ],
  });

  // 5. SES Trigger Permission & Receipt Rule Set with Authoritative Verdicts
  const caller = aws.getCallerIdentityOutput({});
  const sesPermission = new aws.lambda.Permission(
    `BrainsOSMailSanitizerSesPerm-${cleanStage}`,
    {
      action: "lambda:InvokeFunction",
      function: sanitizerLambda.arn,
      principal: "ses.amazonaws.com",
      sourceAccount: caller.accountId,
    }
  );

  const mailReceipt = createMailReceiptRule(
    stage,
    ingressDomains,
    ingressBucket.bucketId,
    sanitizerLambda.arn,
    [ingressBucket.bucketPolicy, sesPermission]
  );

  // 7. Local Workstation Worker IAM Policy & Credentials (Least Privilege)
  const workerCreds = createMailWorkerCredentials(
    stage,
    ingressBucket.bucketArn,
    ingressQueues.queueArn
  );

  return {
    sesIdentities,
    sanitizerLambda,
    outputs: {
      mailIngressDomains: ingressDomains,
      mailIngressBucket: ingressBucket.bucketId,
      mailIngressQueueUrl: ingressQueues.queueUrl,
      mailIngressDlqUrl: ingressQueues.dlqUrl,
      mailIngressRuleSet: mailReceipt.ruleSetName,
      mailIngressRule: mailReceipt.ruleName,
      mailSanitizerLambdaArn: sanitizerLambda.arn,
      mailWorkerPolicyArn: workerCreds.policyArn,
      mailWorkerAccessKeyId: workerCreds.accessKeyId,
      mailWorkerSecretAccessKey: workerCreds.secretAccessKey,
      sesSenderPolicyArn: sesSenderPolicy.arn,
    },
  };
}
