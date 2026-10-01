/// <reference path="../../.sst/platform/config.d.ts" />

export function setupSesIdentities(
  domains: string[],
  zoneId: any,
  zoneName: string
) {
  const sesResources: Record<string, any> = {};

  for (const domain of domains) {
    const cleanId = domain.replace(/[^a-zA-Z0-9]/g, "-");

    // 1. SES Domain Identity
    const domainIdentity = new aws.ses.DomainIdentity(`SesIdentity-${cleanId}`, {
      domain,
    });

    // 2. SES Domain DKIM (Easy DKIM)
    const domainDkim = new aws.ses.DomainDkim(`SesDkim-${cleanId}`, {
      domain: domainIdentity.domain,
    });

    // 3. Optional DKIM Route 53 records
    if (
      process.env.SETUP_SES_DNS_RECORDS === "true" &&
      (domain === zoneName || domain.endsWith(`.${zoneName}`))
    ) {
      for (let i = 0; i < 3; i++) {
        new aws.route53.Record(`SesDkimRecord-${cleanId}-${i}`, {
          zoneId,
          name: $interpolate`${domainDkim.dkimTokens[i]}._domainkey.${domain}`,
          type: "CNAME",
          ttl: 600,
          records: [$interpolate`${domainDkim.dkimTokens[i]}.dkim.amazonses.com`],
        });
      }
    }

    sesResources[cleanId] = {
      domain,
      verificationToken: domainIdentity.verificationToken,
    };
  }

  return sesResources;
}

export function createMailReceiptRule(
  stage: string,
  ingressDomains: string[],
  bucketId: any
) {
  const cleanStage = stage.toLowerCase().replace(/[^a-zA-Z0-9]/g, "-");

  const ruleSet = new aws.ses.ReceiptRuleSet(`BrainsOSMailIngressRuleSet-${cleanStage}`, {
    ruleSetName: `brainsos-mail-ingress-rules-${cleanStage}`,
  });

  const receiptRule = new aws.ses.ReceiptRule(`BrainsOSMailIngressRule-${cleanStage}`, {
    name: `brainsos-mail-ingress-rule-${cleanStage}`,
    ruleSetName: ruleSet.ruleSetName,
    recipients: ingressDomains,
    enabled: true,
    scanEnabled: true,
    s3Actions: [
      {
        bucketName: bucketId,
        objectKeyPrefix: "raw/",
        position: 1,
      },
    ],
  });

  return {
    ruleSet,
    ruleSetName: ruleSet.ruleSetName,
    receiptRule,
    ruleName: receiptRule.name,
  };
}
