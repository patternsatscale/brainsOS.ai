/// <reference path="../../.sst/platform/config.d.ts" />
import { setupRoute53Zone } from "../components/dns.js";
import { createRedirectFunction } from "../functions/redirect.js";
import { createDummyOriginBucket } from "../components/s3.js";
import { setupCloudFrontRedirect } from "../components/cdn.js";
import { createCaddyAcmeCredentials } from "../components/iam.js";

export interface PublicRedirectFlowInput {
  zoneName: string;
  subdomain: string;
  redirectUrl: string;
  createZone: boolean;
}

export function setupPublicRedirectFlow(input: PublicRedirectFlowInput) {
  const { zoneName, subdomain, redirectUrl, createZone } = input;
  const fullDomain = `${subdomain}.${zoneName}`;

  // 1. Route 53 DNS Zone
  const { zoneId } = setupRoute53Zone(zoneName, createZone);

  // 2. CloudFront Edge Function & S3 Dummy Origin
  const redirectFn = createRedirectFunction(subdomain, zoneName, redirectUrl);
  const dummyOrigin = createDummyOriginBucket(subdomain, zoneName);

  // 3. CloudFront Distribution & Public ACM SSL
  const cdn = setupCloudFrontRedirect(
    fullDomain,
    zoneId,
    dummyOrigin.bucketRegionalDomainName,
    redirectFn.arn,
    subdomain
  );

  // 4. Host Appliance Caddy ACME IAM Credentials
  const caddyAcme = createCaddyAcmeCredentials(subdomain, zoneId);

  return {
    zoneId,
    outputs: {
      brainsosDomain: fullDomain,
      redirectUrl,
      publicDistribution: cdn.distributionDomain,
      caddyAcmeAccessKeyId: caddyAcme.accessKeyId,
      caddyAcmeSecretAccessKey: caddyAcme.secretAccessKey,
    },
  };
}
