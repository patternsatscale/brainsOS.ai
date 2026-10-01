/// <reference path="./.sst/platform/config.d.ts" />
import { setupPublicRedirectFlow } from "./src/flows/public-redirect.js";
import { setupEmailIngressFlow } from "./src/flows/email-ingress.js";

export default $config({
  app(input) {
    return {
      name: "brainsos-infra",
      removal: input?.stage === "production" ? "retain" : "remove",
      home: "aws",
      providers: {
        aws: {
          region: (process.env.BRAINSOS_INFRA_AWS_REGION || process.env.AWS_REGION || "us-east-1") as any,
          version: "6.50.0",
        },
      },
    };
  },
  async run() {
    const stage = $app.stage;
    const zoneName = process.env.BRAINSOS_ZONE_NAME || "example.com";
    const subdomain = process.env.BRAINSOS_SUBDOMAIN || "brainsos";
    const redirectUrl = process.env.BRAINSOS_REDIRECT_URL || "https://brainsos.ai";
    const createZone = process.env.BRAINSOS_CREATE_ZONE === "true";
    const rawSesDomains = process.env.SES_DOMAINS || zoneName;
    const sesDomains = rawSesDomains.split(",").map((d) => d.trim()).filter(Boolean);

    // Ingress domains: environment-specific email domain or default to sesDomains
    const rawEmailDomain = process.env.BRAINSOS_EMAIL_DOMAIN;
    const ingressDomains = rawEmailDomain
      ? rawEmailDomain.split(",").map((d) => d.trim()).filter(Boolean)
      : sesDomains;

    // Flow 1: Public Split-Horizon DNS & Redirect Flow
    const redirectFlow = setupPublicRedirectFlow({
      zoneName,
      subdomain,
      redirectUrl,
      createZone,
    });

    // Flow 2: Multi-Stage Email Ingress Flow
    const emailIngressFlow = setupEmailIngressFlow({
      stage,
      ingressDomains,
      sesDomains,
      zoneId: redirectFlow.zoneId,
      zoneName,
    });

    return {
      stage,
      sesDomains,
      ...redirectFlow.outputs,
      ...emailIngressFlow.outputs,
    };
  },
});
