/// <reference path="./.sst/platform/config.d.ts" />

export default $config({
  app(input) {
    return {
      name: "cindy-pawford",
      removal: input?.stage === "production" ? "retain" : "remove",
      home: "aws",
      providers: {
        aws: {
          region: "us-east-1",
          version: "6.50.0",
        },
      },
    };
  },
  async run() {
    // 1. DynamoDB Table for community suggestions & upvoting partitioned by era
    const suggestions = new sst.aws.Dynamo("Suggestions", {
      fields: {
        era_id: "string",
        id: "string",
      },
      primaryIndex: { hashKey: "era_id", rangeKey: "id" },
    });

    // 2. Serverless API Gateway for suggestions, voting & Cindy's daily query
    const api = new sst.aws.ApiGatewayV2("CindyApi");

    api.route("GET /api/top-suggestions", {
      handler: "src/api.topSuggestions",
      link: [suggestions],
    });

    api.route("POST /api/suggest", {
      handler: "src/api.suggest",
      link: [suggestions],
    });

    api.route("POST /api/vote/{id}", {
      handler: "src/api.vote",
      link: [suggestions],
    });

    // 3. Production StaticSite on AWS S3 + CloudFront (cindypawford.com + www redirect)
    const productionSite = new sst.aws.StaticSite("ProductionSite", {
      path: "../site",
      domain: {
        name: "cindypawford.com",
        redirects: ["www.cindypawford.com"],
      },
      environment: {
        CINDY_API_URL: api.url,
      },
    });

    // 4. Archive Museum StaticSite on AWS S3 + CloudFront (archive.cindypawford.com)
    new sst.aws.StaticSite("ArchiveSite", {
      path: "../archive",
      domain: "archive.cindypawford.com",
    });
  },
});
