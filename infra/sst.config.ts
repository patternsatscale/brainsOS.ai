/// <reference path="./.sst/platform/config.d.ts" />
import { setupDns } from "./src/dns.js";
import { setupSes } from "./src/ses.js";

export default $config({
  app(input) {
    return {
      name: "titan-infra",
      removal: input?.stage === "production" ? "retain" : "remove",
      home: "aws",
      providers: {
        aws: {
          region: (process.env.TITAN_INFRA_AWS_REGION || process.env.AWS_REGION || "us-east-1") as any,
          version: "6.50.0",
        },
      },
    };
  },
  async run() {
    const zoneName = process.env.TITAN_ZONE_NAME || "example.com";
    const subdomain = process.env.TITAN_SUBDOMAIN || "titan";
    const redirectUrl = process.env.TITAN_GITHUB_REDIRECT_URL || "https://github.com/patternsatscale/project-titan";
    const createZone = process.env.TITAN_CREATE_ZONE === "true";
    const rawSesDomains = process.env.SES_DOMAINS || zoneName;
    const sesDomains = rawSesDomains.split(",").map((d) => d.trim()).filter(Boolean);

    // 1. Setup Route 53 DNS, Public Redirect, and Caddy ACME IAM credentials
    const dns = setupDns(zoneName, subdomain, redirectUrl, createZone);

    // 2. Setup SES Domain Identities and DKIM/SPF/DMARC building blocks
    const ses = setupSes(sesDomains, dns.zoneId, zoneName);

    return {
      titanDomain: `${subdomain}.${zoneName}`,
      redirectUrl,
      publicDistribution: dns.distributionDomain,
      caddyAcmeAccessKeyId: dns.caddyAcmeAccessKeyId,
      caddyAcmeSecretAccessKey: dns.caddyAcmeSecretAccessKey,
      sesDomains,
      sesSenderPolicyArn: ses.senderPolicyArn,
    };
  },
});
