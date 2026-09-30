/// <reference path="../.sst/platform/config.d.ts" />

export function setupDns(
  zoneName: string,
  subdomain: string,
  redirectUrl: string,
  createZone: boolean = false
) {
  const fullDomain = `${subdomain}.${zoneName}`;

  // 1. Hosted Zone lookup or creation
  let zoneId: any;
  let zoneArn: any;

  if (createZone) {
    const zone = new aws.route53.Zone("BrainsOSHostedZone", {
      name: zoneName,
      comment: "brainsOS Split-Horizon Public DNS Zone",
    });
    zoneId = zone.zoneId;
    zoneArn = zone.arn;
  } else {
    const zone = aws.route53.getZoneOutput({
      name: zoneName,
    });
    zoneId = zone.zoneId;
    zoneArn = zone.arn;
  }

  // 2. Public Split-Horizon Redirect (HTTP 301/302 to destination URL)
  // Utilizes a CloudFront Function to instantly redirect public visitors
  const redirectFunction = new aws.cloudfront.Function("BrainsOSPublicRedirectFn", {
    name: `brainsos-redirect-${subdomain}-${zoneName.replace(/[^a-zA-Z0-9]/g, "-")}`,
    runtime: "cloudfront-js-2.0",
    comment: "Redirects public HTTP/HTTPS traffic to brainsOS",
    code: `function handler(event) {
    return {
        statusCode: 302,
        statusDescription: 'Found',
        headers: {
            'location': { value: '${redirectUrl}' },
            'cache-control': { value: 'max-age=3600' }
        }
    };
}`,
  });

  // Request ACM public certificate in us-east-1 for CloudFront
  const cert = new aws.acm.Certificate("BrainsOSRedirectCert", {
    domainName: fullDomain,
    validationMethod: "DNS",
  });

  const certValidationRecord = new aws.route53.Record("BrainsOSRedirectCertValidation", {
    zoneId,
    name: cert.domainValidationOptions[0].resourceRecordName,
    type: cert.domainValidationOptions[0].resourceRecordType,
    records: [cert.domainValidationOptions[0].resourceRecordValue],
    ttl: 60,
  });

  const certValidation = new aws.acm.CertificateValidation("BrainsOSRedirectCertValidationWait", {
    certificateArn: cert.arn,
    validationRecordFqdns: [certValidationRecord.fqdn],
  });

  // CloudFront Distribution without backend origin (CloudFront function handles the response directly)
  // S3 placeholder origin required by CloudFront schema
  const dummyBucket = new aws.s3.Bucket("BrainsOSDummyOriginBucket", {
    bucket: `brainsos-origin-${subdomain}-${zoneName.replace(/[^a-zA-Z0-9]/g, "-")}`,
    forceDestroy: true,
  });

  const oac = new aws.cloudfront.OriginAccessControl("BrainsOSDummyOAC", {
    name: `brainsos-oac-${subdomain}`,
    originAccessControlOriginType: "s3",
    signingBehavior: "always",
    signingProtocol: "sigv4",
  });

  const distribution = new aws.cloudfront.Distribution("BrainsOSRedirectDistribution", {
    enabled: true,
    aliases: [fullDomain],
    origins: [
      {
        originId: "dummyS3",
        domainName: dummyBucket.bucketRegionalDomainName,
        originAccessControlId: oac.id,
      },
    ],
    defaultCacheBehavior: {
      targetOriginId: "dummyS3",
      viewerProtocolPolicy: "redirect-to-https",
      allowedMethods: ["GET", "HEAD"],
      cachedMethods: ["GET", "HEAD"],
      forwardedValues: {
        queryString: false,
        cookies: { forward: "none" },
      },
      functionAssociations: [
        {
          eventType: "viewer-request",
          functionArn: redirectFunction.arn,
        },
      ],
    },
    viewerCertificate: {
      acmCertificateArn: certValidation.certificateArn,
      sslSupportMethod: "sni-only",
      minimumProtocolVersion: "TLSv1.2_2021",
    },
    restrictions: {
      geoRestriction: {
        restrictionType: "none",
      },
    },
  });

  // Route 53 Alias Record pointing to CloudFront
  new aws.route53.Record("BrainsOSRedirectAliasRecord", {
    zoneId,
    name: fullDomain,
    type: "A",
    aliases: [
      {
        name: distribution.domainName,
        zoneId: distribution.hostedZoneId,
        evaluateTargetHealth: false,
      },
    ],
  });

  // 3. Least-Privilege IAM User & Policy for Local Appliance Caddy ACME DNS-01 Challenge
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
    zoneId,
    fullDomain,
    distributionDomain: distribution.domainName,
    caddyAcmeAccessKeyId: caddyAcmeAccessKey.id,
    caddyAcmeSecretAccessKey: caddyAcmeAccessKey.secret,
  };
}
