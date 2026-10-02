/// <reference path="../../.sst/platform/config.d.ts" />

export function createMailSanitizerPolicy(
  stage: string,
  bucketArn: any,
  queueArn: any
) {
  const cleanStage = stage.toLowerCase().replace(/[^a-zA-Z0-9]/g, "-");

  return new aws.iam.Policy(`BrainsOSMailSanitizerPolicy-${cleanStage}`, {
    name: `brainsos-mail-sanitizer-policy-${cleanStage}`,
    description: "Least-privilege policy for external email sanitizer Lambda",
    policy: $interpolate`{
      "Version": "2012-10-17",
      "Statement": [
        {
          "Sid": "S3RawAccess",
          "Effect": "Allow",
          "Action": [
            "s3:GetObject",
            "s3:DeleteObject"
          ],
          "Resource": "${bucketArn}/raw/*"
        },
        {
          "Sid": "S3ProcessedWrite",
          "Effect": "Allow",
          "Action": [
            "s3:PutObject"
          ],
          "Resource": [
            "${bucketArn}/approved/*",
            "${bucketArn}/quarantine/*"
          ]
        },
        {
          "Sid": "SQSSendMessage",
          "Effect": "Allow",
          "Action": [
            "sqs:SendMessage"
          ],
          "Resource": "${queueArn}"
        }
      ]
    }`,
  });
}

export function createMailWorkerCredentials(
  stage: string,
  bucketArn: any,
  queueArn: any
) {
  const cleanStage = stage.toLowerCase().replace(/[^a-zA-Z0-9]/g, "-");

  const workerPolicy = new aws.iam.Policy(`BrainsOSMailWorkerPolicy-${cleanStage}`, {
    name: `brainsos-mail-worker-policy-${cleanStage}`,
    description: "Least-privilege policy for local brainsOS-mail consumer",
    policy: $interpolate`{
      "Version": "2012-10-17",
      "Statement": [
        {
          "Sid": "SQSConsumer",
          "Effect": "Allow",
          "Action": [
            "sqs:ReceiveMessage",
            "sqs:DeleteMessage",
            "sqs:GetQueueAttributes",
            "sqs:ChangeMessageVisibility"
          ],
          "Resource": "${queueArn}"
        },
        {
          "Sid": "S3ApprovedFetch",
          "Effect": "Allow",
          "Action": [
            "s3:GetObject",
            "s3:DeleteObject"
          ],
          "Resource": "${bucketArn}/approved/*"
        },
        {
          "Sid": "SESSend",
          "Effect": "Allow",
          "Action": [
            "ses:SendEmail",
            "ses:SendRawEmail"
          ],
          "Resource": "*"
        }
      ]
    }`,
  });

  const workerUser = new aws.iam.User(`BrainsOSMailWorkerUser-${cleanStage}`, {
    name: `brainsos-mail-worker-${cleanStage}`,
  });

  new aws.iam.UserPolicyAttachment(`BrainsOSMailWorkerAttachment-${cleanStage}`, {
    user: workerUser.name,
    policyArn: workerPolicy.arn,
  });

  const workerKey = new aws.iam.AccessKey(`BrainsOSMailWorkerKey-${cleanStage}`, {
    user: workerUser.name,
  });

  return {
    policyArn: workerPolicy.arn,
    accessKeyId: workerKey.id,
    secretAccessKey: workerKey.secret,
  };
}

export function createSesSenderPolicy() {
  return new aws.iam.Policy("BrainsOSSesSenderPolicy", {
    name: "brainsos-ses-sender-policy",
    description: "Least-privilege policy allowing agent communications layer to send via verified SES identities",
    policy: JSON.stringify({
      Version: "2012-10-17",
      Statement: [
        {
          Effect: "Allow",
          Action: ["ses:SendEmail", "ses:SendRawEmail"],
          Resource: "*",
        },
      ],
    }),
  });
}

export function createCaddyAcmeCredentials(subdomain: string, zoneId: any) {
  const caddyAcmePolicy = new aws.iam.Policy("BrainsOSCaddyAcmePolicy", {
    name: `brainsos-caddy-acme-${subdomain}`,
    description: "Least-privilege policy for Caddy ACME DNS-01 challenge in Route 53",
    policy: $interpolate`{
      "Version": "2012-10-17",
      "Statement": [
        {
          "Effect": "Allow",
          "Action": "route53:GetChange",
          "Resource": "arn:aws:route53:::change/*"
        },
        {
          "Effect": "Allow",
          "Action": "route53:ChangeResourceRecordSets",
          "Resource": "arn:aws:route53:::hostedzone/${zoneId}"
        },
        {
          "Effect": "Allow",
          "Action": [
            "route53:ListHostedZonesByName",
            "route53:ListHostedZones"
          ],
          "Resource": "*"
        }
      ]
    }`,
  });

  const caddyAcmeUser = new aws.iam.User("BrainsOSCaddyAcmeUser", {
    name: `brainsos-caddy-acme-${subdomain}`,
  });

  new aws.iam.UserPolicyAttachment("BrainsOSCaddyAcmeUserAttachment", {
    user: caddyAcmeUser.name,
    policyArn: caddyAcmePolicy.arn,
  });

  const caddyAcmeAccessKey = new aws.iam.AccessKey("BrainsOSCaddyAcmeKey", {
    user: caddyAcmeUser.name,
  });

  return {
    policyArn: caddyAcmePolicy.arn,
    accessKeyId: caddyAcmeAccessKey.id,
    secretAccessKey: caddyAcmeAccessKey.secret,
  };
}
