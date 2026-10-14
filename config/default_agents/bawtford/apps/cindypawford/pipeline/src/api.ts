import { DynamoDBClient } from "@aws-sdk/client-dynamodb";
import {
  DynamoDBDocumentClient,
  QueryCommand,
  PutCommand,
  UpdateCommand,
  GetCommand,
} from "@aws-sdk/lib-dynamodb";
import { Resource } from "sst";
import crypto from "node:crypto";

declare module "sst" {
  export interface Resource {
    Suggestions: {
      name: string;
    };
  }
}

const client = new DynamoDBClient({});
const docClient = DynamoDBDocumentClient.from(client);

// Default active era if not specified
const CURRENT_ACTIVE_ERA = process.env.ACTIVE_ERA_ID || "autumn-paws-gala-2026";

const CORS_HEADERS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type, Authorization",
  "Content-Type": "application/json",
};

// Profanity & Spam Heuristics
const BLOCKED_WORDS = [
  "viagra",
  "casino",
  "crypto-scam",
  "buy-followers",
  "free-crypto",
  "nude",
  "porn",
  "fuck",
  "shit",
  "bitch",
  "asshole",
];

function isProfaneOrSpam(text: string): boolean {
  const lower = text.toLowerCase();
  for (const word of BLOCKED_WORDS) {
    if (lower.includes(word)) return true;
  }
  // URL spam check: more than 1 URL or suspicious scheme
  const urlMatches = text.match(/https?:\/\//gi);
  if (urlMatches && urlMatches.length > 1) return true;
  return false;
}

export async function topSuggestions(event: any) {
  if (event.requestContext?.http?.method === "OPTIONS") {
    return { statusCode: 204, headers: CORS_HEADERS };
  }

  try {
    const eraId =
      event.queryStringParameters?.era || CURRENT_ACTIVE_ERA;
    const tableName = Resource.Suggestions.name;

    const command = new QueryCommand({
      TableName: tableName,
      KeyConditionExpression: "era_id = :era",
      ExpressionAttributeValues: {
        ":era": eraId,
      },
    });

    const result = await docClient.send(command);
    const items = result.Items || [];

    // Sort by votes descending, return top 25
    items.sort((a, b) => (b.votes || 0) - (a.votes || 0));
    const top = items.slice(0, 25);

    return {
      statusCode: 200,
      headers: CORS_HEADERS,
      body: JSON.stringify({
        era_id: eraId,
        is_active: eraId === CURRENT_ACTIVE_ERA,
        count: top.length,
        suggestions: top,
      }),
    };
  } catch (err: any) {
    console.error("Error fetching suggestions:", err);
    return {
      statusCode: 500,
      headers: CORS_HEADERS,
      body: JSON.stringify({ error: "Failed to fetch suggestions", details: err.message }),
    };
  }
}

export async function suggest(event: any) {
  if (event.requestContext?.http?.method === "OPTIONS") {
    return { statusCode: 204, headers: CORS_HEADERS };
  }

  try {
    const body = JSON.parse(event.body || "{}");
    const rawText = (body.text || "").trim();
    const eraId = body.era_id || CURRENT_ACTIVE_ERA;

    // Reject suggestions for closed eras
    if (eraId !== CURRENT_ACTIVE_ERA) {
      return {
        statusCode: 403,
        headers: CORS_HEADERS,
        body: JSON.stringify({ error: "Voting and suggestions are closed for past eras." }),
      };
    }

    if (!rawText || rawText.length === 0) {
      return {
        statusCode: 400,
        headers: CORS_HEADERS,
        body: JSON.stringify({ error: "Suggestion text cannot be empty." }),
      };
    }

    if (rawText.length > 140) {
      return {
        statusCode: 400,
        headers: CORS_HEADERS,
        body: JSON.stringify({ error: "Suggestion exceeds maximum length of 140 characters." }),
      };
    }

    if (isProfaneOrSpam(rawText)) {
      return {
        statusCode: 422,
        headers: CORS_HEADERS,
        body: JSON.stringify({ error: "Content violates community standards or spam filters." }),
      };
    }

    const id = crypto.randomUUID();
    const item = {
      era_id: eraId,
      id,
      text: rawText,
      votes: 1,
      status: "active",
      created_at: new Date().toISOString(),
      source_ip: event.requestContext?.http?.sourceIp || "unknown",
    };

    const tableName = Resource.Suggestions.name;
    await docClient.send(
      new PutCommand({
        TableName: tableName,
        Item: item,
      })
    );

    return {
      statusCode: 201,
      headers: CORS_HEADERS,
      body: JSON.stringify({
        success: true,
        message: "Suggestion recorded for Cindy's atelier consideration.",
        item: {
          id: item.id,
          era_id: item.era_id,
          text: item.text,
          votes: item.votes,
          created_at: item.created_at,
        },
      }),
    };
  } catch (err: any) {
    console.error("Error creating suggestion:", err);
    return {
      statusCode: 500,
      headers: CORS_HEADERS,
      body: JSON.stringify({ error: "Failed to submit suggestion", details: err.message }),
    };
  }
}

export async function vote(event: any) {
  if (event.requestContext?.http?.method === "OPTIONS") {
    return { statusCode: 204, headers: CORS_HEADERS };
  }

  try {
    const id = event.pathParameters?.id;
    if (!id) {
      return {
        statusCode: 400,
        headers: CORS_HEADERS,
        body: JSON.stringify({ error: "Missing suggestion ID in path." }),
      };
    }

    let eraId = event.queryStringParameters?.era || CURRENT_ACTIVE_ERA;
    const tableName = Resource.Suggestions.name;

    // Check if the era is closed
    if (eraId !== CURRENT_ACTIVE_ERA) {
      return {
        statusCode: 403,
        headers: CORS_HEADERS,
        body: JSON.stringify({ error: "Voting has ended for this archived era." }),
      };
    }

    const updateCmd = new UpdateCommand({
      TableName: tableName,
      Key: {
        era_id: eraId,
        id: id,
      },
      UpdateExpression: "ADD votes :inc",
      ConditionExpression: "attribute_exists(id) AND #status = :active",
      ExpressionAttributeNames: {
        "#status": "status",
      },
      ExpressionAttributeValues: {
        ":inc": 1,
        ":active": "active",
      },
      ReturnValues: "ALL_NEW",
    });

    const response = await docClient.send(updateCmd);
    const updated = response.Attributes;

    return {
      statusCode: 200,
      headers: CORS_HEADERS,
      body: JSON.stringify({
        success: true,
        id: updated?.id,
        votes: updated?.votes,
      }),
    };
  } catch (err: any) {
    if (err.name === "ConditionalCheckFailedException") {
      return {
        statusCode: 404,
        headers: CORS_HEADERS,
        body: JSON.stringify({ error: "Suggestion not found or voting is closed." }),
      };
    }
    console.error("Error voting:", err);
    return {
      statusCode: 500,
      headers: CORS_HEADERS,
      body: JSON.stringify({ error: "Failed to record vote", details: err.message }),
    };
  }
}
