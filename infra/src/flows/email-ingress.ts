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
  const sesIdentities = setupSesIdentities(sesDomains, zoneId, zoneName);
  const sesSenderPolicy = createSesSenderPolicy();

  // 2. Multi-Stage Ingress S3 Bucket with Expiration Lifecycles
  const ingressBucket = createMailIngressBucket(stage);

  // 3. Multi-Stage Ingress SQS Queue & Dead Letter Queue (DLQ)
  const ingressQueues = createMailIngressQueues(stage);

  // 4. SES Inbound Receipt Rule Set & Receipt Rules
  const mailReceipt = createMailReceiptRule(stage, ingressDomains, ingressBucket.bucketId);

  // 5. Ingress Sanitizer Lambda (Ticket #210)
  const sanitizerLambda = new sst.aws.Function(`BrainsOSMailSanitizer-${cleanStage}`, {
    handler: "src/functions/sanitizer/handler.handler",
    environment: {
      ALLOWED_EXTERNAL_SENDERS:
        process.env.ALLOWED_EXTERNAL_SENDERS || "patternsatscale@gmail.com",
      ALLOWED_RECIPIENT_DOMAINS: ingressDomains.join(","),
      INGRESS_QUEUE_URL: ingressQueues.queueUrl,
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

  // 6. S3 Trigger to Lambda on raw/ ObjectCreated
  new aws.lambda.Permission(`BrainsOSMailSanitizerPerm-${cleanStage}`, {
    action: "lambda:InvokeFunction",
    function: sanitizerLambda.arn,
    principal: "s3.amazonaws.com",
    sourceArn: ingressBucket.bucketArn,
  });

  new aws.s3.BucketNotification(`BrainsOSMailIngressNotification-${cleanStage}`, {
    bucket: ingressBucket.bucketId,
    lambdaFunctions: [
      {
        lambdaFunctionArn: sanitizerLambda.arn,
        events: ["s3:ObjectCreated:*"],
        filterPrefix: "raw/",
      },
    ],
  });

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
