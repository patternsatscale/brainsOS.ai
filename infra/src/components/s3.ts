/// <reference path="../../.sst/platform/config.d.ts" />

export function createMailIngressBucket(stage: string) {
  const cleanStage = stage.toLowerCase().replace(/[^a-zA-Z0-9]/g, "-");
  const caller = aws.getCallerIdentityOutput({});

  const ingressBucket = new aws.s3.BucketV2(`BrainsOSMailIngressBucket-${cleanStage}`, {
    bucket: `brainsos-mail-ingress-${cleanStage}`,
    forceDestroy: true,
  });

  new aws.s3.BucketPublicAccessBlock(`BrainsOSMailIngressPAB-${cleanStage}`, {
    bucket: ingressBucket.id,
    blockPublicAcls: true,
    blockPublicPolicy: true,
    ignorePublicAcls: true,
    restrictPublicBuckets: true,
  });

  new aws.s3.BucketLifecycleConfigurationV2(`BrainsOSMailIngressLifecycle-${cleanStage}`, {
    bucket: ingressBucket.id,
    rules: [
      {
        id: "raw-7d-expiration",
        status: "Enabled",
        filter: { prefix: "raw/" },
        expiration: { days: 7 },
      },
      {
        id: "approved-14d-expiration",
        status: "Enabled",
        filter: { prefix: "approved/" },
        expiration: { days: 14 },
      },
      {
        id: "quarantine-30d-expiration",
        status: "Enabled",
        filter: { prefix: "quarantine/" },
        expiration: { days: 30 },
      },
    ],
  });

  new aws.s3.BucketPolicy(`BrainsOSMailIngressBucketPolicy-${cleanStage}`, {
    bucket: ingressBucket.id,
    policy: $interpolate`{
      "Version": "2012-10-17",
      "Statement": [
        {
          "Sid": "AllowSESPuts",
          "Effect": "Allow",
          "Principal": {
            "Service": "ses.amazonaws.com"
          },
          "Action": "s3:PutObject",
          "Resource": "${ingressBucket.arn}/raw/*",
          "Condition": {
            "StringEquals": {
              "AWS:SourceAccount": "${caller.accountId}"
            }
          }
        }
      ]
    }`,
  });

  return {
    bucket: ingressBucket,
    bucketId: ingressBucket.id,
    bucketArn: ingressBucket.arn,
  };
}

export function createDummyOriginBucket(subdomain: string, zoneName: string) {
  const cleanZone = zoneName.replace(/[^a-zA-Z0-9]/g, "-");
  const dummyBucket = new aws.s3.Bucket("BrainsOSDummyOriginBucket", {
    bucket: `brainsos-origin-${subdomain}-${cleanZone}`,
    forceDestroy: true,
  });

  return {
    bucket: dummyBucket,
    bucketRegionalDomainName: dummyBucket.bucketRegionalDomainName,
  };
}
