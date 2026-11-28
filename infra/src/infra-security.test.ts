import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const INFRA_ROOT = path.resolve(__dirname, "..");

function readInfraFile(relPath: string): string {
  return fs.readFileSync(path.join(INFRA_ROOT, relPath), "utf8");
}

describe("SST Infrastructure Security Hardening (#408 / MEDIUM-4)", () => {
  it("wraps IAM AccessKey secrets in $util.secret and marks additionalSecretOutputs in iam.ts", () => {
    const iamTs = readInfraFile("src/components/iam.ts");

    expect(iamTs).toContain("secretAccessKey: $util.secret(workerKey.secret)");
    expect(iamTs).toContain("secretAccessKey: $util.secret(caddyAcmeAccessKey.secret)");
    expect(iamTs).not.toMatch(/secretAccessKey:\s*workerKey\.secret\b/);
    expect(iamTs).not.toMatch(/secretAccessKey:\s*caddyAcmeAccessKey\.secret\b/);

    const additionalSecretMatches = iamTs.match(
      /additionalSecretOutputs:\s*\["secret",\s*"sesSmtpPasswordV4"\]/g
    );
    expect(additionalSecretMatches).toHaveLength(2);
  });

  it("propagates $util.secret wrapping through email-ingress and public-redirect flows", () => {
    const emailIngressTs = readInfraFile("src/flows/email-ingress.ts");
    const publicRedirectTs = readInfraFile("src/flows/public-redirect.ts");

    expect(emailIngressTs).toContain(
      "mailWorkerSecretAccessKey: $util.secret(workerCreds.secretAccessKey)"
    );
    expect(emailIngressTs).not.toMatch(
      /mailWorkerSecretAccessKey:\s*workerCreds\.secretAccessKey\b/
    );

    expect(publicRedirectTs).toContain(
      "caddyAcmeSecretAccessKey: $util.secret(caddyAcme.secretAccessKey)"
    );
    expect(publicRedirectTs).not.toMatch(
      /caddyAcmeSecretAccessKey:\s*caddyAcme\.secretAccessKey\b/
    );
  });

  it("redacts IAM secret access keys from top-level SST CLI outputs in sst.config.ts", () => {
    const sstConfigTs = readInfraFile("sst.config.ts");

    expect(sstConfigTs).toContain(
      "const { caddyAcmeSecretAccessKey: _caddySecret, ...publicRedirectOutputs } = redirectFlow.outputs;"
    );
    expect(sstConfigTs).toContain(
      "const { mailWorkerSecretAccessKey: _mailWorkerSecret, ...publicEmailIngressOutputs } = emailIngressFlow.outputs;"
    );
    expect(sstConfigTs).toContain("...publicRedirectOutputs,");
    expect(sstConfigTs).toContain("...publicEmailIngressOutputs,");
    expect(sstConfigTs).toContain('caddyAcmeSecretAccessKey: $util.secret("[REDACTED');
    expect(sstConfigTs).toContain('mailWorkerSecretAccessKey: $util.secret("[REDACTED');
    expect(sstConfigTs).not.toContain("...redirectFlow.outputs");
    expect(sstConfigTs).not.toContain("...emailIngressFlow.outputs");
  });

  it("attaches full BucketPublicAccessBlock to createDummyOriginBucket in s3.ts", () => {
    const s3Ts = readInfraFile("src/components/s3.ts");
    const dummyBlock = s3Ts.slice(s3Ts.indexOf("export function createDummyOriginBucket"));

    expect(dummyBlock).toContain('new aws.s3.BucketPublicAccessBlock("BrainsOSDummyOriginPAB"');
    expect(dummyBlock).toContain("bucket: dummyBucket.id");
    expect(dummyBlock).toContain("blockPublicAcls: true");
    expect(dummyBlock).toContain("blockPublicPolicy: true");
    expect(dummyBlock).toContain("ignorePublicAcls: true");
    expect(dummyBlock).toContain("restrictPublicBuckets: true");
  });
});
