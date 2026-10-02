/// <reference path="../../.sst/platform/config.d.ts" />

export function setupSesIdentities(
  domains: string[],
  zoneId: any,
  zoneName: string,
  region: string = "us-east-1"
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

    // 3. Route 53 DNS Records (DKIM + Inbound SES MX)
    if (domain === zoneName || domain.endsWith(`.${zoneName}`)) {
      // Inbound MX record pointing to AWS SES
      new aws.route53.Record(`SesMxRecord-${cleanId}`, {
        zoneId,
        name: domain,
        type: "MX",
        ttl: 300,
        records: [`10 inbound-smtp.${region}.amazonaws.com`],
      });

      // Easy DKIM CNAME records
      for (let i = 0; i < 3; i++) {
        new aws.route53.Record(`SesDkimRecord-${cleanId}-${i}`, {
          zoneId,
          name: $interpolate`${domainDkim.dkimTokens[i]}._domainkey.${domain}`,
          type: "CNAME",
          ttl: 600,
          records: [$interpolate`${domainDkim.dkimTokens[i]}.dkim.amazonses.com`],
        });
      }

      // SPF TXT record
      new aws.route53.Record(`SesSpfRecord-${cleanId}`, {
        zoneId,
        name: domain,
        type: "TXT",
        ttl: 300,
        records: ["v=spf1 include:amazonses.com ~all"],
      });

      // DMARC TXT record
      new aws.route53.Record(`SesDmarcRecord-${cleanId}`, {
        zoneId,
        name: `_dmarc.${domain}`,
        type: "TXT",
        ttl: 300,
        records: ["v=DMARC1; p=none;"],
      });
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
  bucketId: any,
  dependsOn?: any[]
) {
  const cleanStage = stage.toLowerCase().replace(/[^a-zA-Z0-9]/g, "-");

  const ruleSet = new aws.ses.ReceiptRuleSet(`BrainsOSMailIngressRuleSet-${cleanStage}`, {
    ruleSetName: `brainsos-mail-ingress-rules-${cleanStage}`,
  });

  const receiptRule = new aws.ses.ReceiptRule(
    `BrainsOSMailIngressRule-${cleanStage}`,
    {
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
    },
    { dependsOn: dependsOn || [] }
  );

  const activeRuleSet = new aws.ses.ActiveReceiptRuleSet(`BrainsOSMailActiveRuleSet-${cleanStage}`, {
    ruleSetName: ruleSet.ruleSetName,
  }, { dependsOn: [receiptRule] });

  return {
    ruleSet,
    ruleSetName: ruleSet.ruleSetName,
    receiptRule,
    ruleName: receiptRule.name,
    activeRuleSet,
  };
}
