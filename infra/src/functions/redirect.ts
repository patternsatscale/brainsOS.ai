/// <reference path="../../.sst/platform/config.d.ts" />

export function createRedirectFunction(
  subdomain: string,
  zoneName: string,
  redirectUrl: string
) {
  const cleanZone = zoneName.replace(/[^a-zA-Z0-9]/g, "-");
  return new aws.cloudfront.Function("BrainsOSPublicRedirectFn", {
    name: `brainsos-redirect-${subdomain}-${cleanZone}`,
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
}
