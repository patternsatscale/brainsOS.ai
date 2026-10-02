/// <reference path="../../.sst/platform/config.d.ts" />

export function createMailIngressQueues(stage: string) {
  const cleanStage = stage.toLowerCase().replace(/[^a-zA-Z0-9]/g, "-");

  const dlq = new aws.sqs.Queue(`BrainsOSMailIngressDlq-${cleanStage}`, {
    name: `brainsos-mail-ingress-dlq-${cleanStage}`,
    messageRetentionSeconds: 1209600, // 14 days
    sqsManagedSseEnabled: true,
  });

  const ingressQueue = new aws.sqs.Queue(`BrainsOSMailIngressQueue-${cleanStage}`, {
    name: `brainsos-mail-ingress-queue-${cleanStage}`,
    messageRetentionSeconds: 1209600, // 14 days
    visibilityTimeoutSeconds: 60,
    receiveWaitTimeSeconds: 20, // Long-polling default
    sqsManagedSseEnabled: true,
    redrivePolicy: $interpolate`{"deadLetterTargetArn":"${dlq.arn}","maxReceiveCount":5}`,
  });

  return {
    queue: ingressQueue,
    queueUrl: ingressQueue.id,
    queueArn: ingressQueue.arn,
    dlq,
    dlqUrl: dlq.id,
    dlqArn: dlq.arn,
  };
}
