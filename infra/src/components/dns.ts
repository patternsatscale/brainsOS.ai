/// <reference path="../../.sst/platform/config.d.ts" />

export function setupRoute53Zone(zoneName: string, createZone: boolean = false) {
  let zoneId: any;
  let zoneArn: any;

  if (createZone) {
    const zone = new aws.route53.Zone("BrainsOSHostedZone", {
      name: zoneName,
      comment: "brainsOS Split-Horizon Public DNS Zone",
    });
    zoneId = zone.zoneId;
    zoneArn = zone.arn;
  } else {
    const zone = aws.route53.getZoneOutput({
      name: zoneName,
    });
    zoneId = zone.zoneId;
    zoneArn = zone.arn;
  }

  return {
    zoneId,
    zoneArn,
  };
}
