/// <reference path="../../.sst/platform/config.d.ts" />

export function setupCloudFrontRedirect(
  fullDomain: string,
  zoneId: any,
  dummyBucketDomain: any,
  redirectFunctionArn: any,
  subdomain: string
) {
  // 1. ACM Public Certificate in us-east-1 for CloudFront
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

  // 2. CloudFront Origin Access Control
  const oac = new aws.cloudfront.OriginAccessControl("BrainsOSDummyOAC", {
    name: `brainsos-oac-${subdomain}`,
    originAccessControlOriginType: "s3",
    signingBehavior: "always",
    signingProtocol: "sigv4",
  });

  // 3. CloudFront Distribution
  const distribution = new aws.cloudfront.Distribution("BrainsOSRedirectDistribution", {
    enabled: true,
    aliases: [fullDomain],
    origins: [
      {
        originId: "dummyS3",
        domainName: dummyBucketDomain,
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
          functionArn: redirectFunctionArn,
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

  // 4. Route 53 Alias Record pointing to CloudFront
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

  return {
    distribution,
    distributionDomain: distribution.domainName,
  };
}
