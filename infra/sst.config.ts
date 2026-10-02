/// <reference path="./.sst/platform/config.d.ts" />
import { setupPublicRedirectFlow } from "./src/flows/public-redirect.js";
import { setupEmailIngressFlow } from "./src/flows/email-ingress.js";

// Load root .env if running directly from infra/ or repo root
try {
  process.loadEnvFile?.(process.cwd().endsWith("/infra") ? "../.env" : ".env");
} catch { }

const parseList = (val?: string) =>
  val?.split(",").map((s) => s.trim()).filter(Boolean) ?? [];

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
    const zoneName = process.env.BRAINSOS_ZONE_NAME || "brainsos.ai";
    const subdomain = process.env.BRAINSOS_SUBDOMAIN || "brainsos";
    const redirectUrl = process.env.BRAINSOS_REDIRECT_URL || "https://github.com/patternsatscale/brainsOS.ai/tree/brainsos";
    const createZone = process.env.BRAINSOS_CREATE_ZONE === "true";
    const sesDomains = parseList(process.env.SES_DOMAINS);
    const ingressDomains = parseList(
      process.env.BRAINSOS_EMAIL_DOMAIN || process.env.BRAINSOS_EXTERNAL_EMAIL_DOMAIN
    );
    if (ingressDomains.length === 0) {
      ingressDomains.push(`${stage}.public.${zoneName}`);
    }

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
