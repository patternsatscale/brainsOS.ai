/// <reference path="../.sst/platform/config.d.ts" />

export function setupSes(domains: string[], zoneId: any, zoneName: string) {
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

    // 3. Optional DKIM records if needed (never clobber existing apex TXT/SPF/DMARC records)
    // Note: Apex SPF/DMARC records are omitted to prevent breaking existing email configurations
    // on production domains (e.g. example.com).
    if (process.env.SETUP_SES_DNS_RECORDS === "true" && (domain === zoneName || domain.endsWith(`.${zoneName}`))) {
      // Easy DKIM 3x CNAME tokens
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

  // 4. Outbound IAM Send Policy Scaffolding (Building block for future agent email dispatch)
  const sesSenderPolicy = new aws.iam.Policy("TitanSesSenderPolicy", {
    name: "titan-ses-sender-policy",
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

  return {
    sesResources,
    senderPolicyArn: sesSenderPolicy.arn,
  };
}
