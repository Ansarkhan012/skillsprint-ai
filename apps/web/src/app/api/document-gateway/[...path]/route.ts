import { NextRequest, NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";
import { apiBaseUrl } from "@/lib/env";

const uuid = "[0-9a-fA-F-]{36}";
const allowedGet = new RegExp(`^(documents|documents/${uuid}|documents/${uuid}/current-effective-version|document-versions/${uuid}|document-versions/${uuid}/(chunks|original))$`);
const allowedPost = new RegExp(`^(documents/uploads|document-versions/${uuid}/(submit|approve|reject|retry))$`);
const rrmGet = new RegExp(`^(requirements|requirements/${uuid}|rrm/evidence|rrm/evidence/${uuid}/chunks|rrm/configs|roles/${uuid}/matrices|roles/${uuid}/ground-truth|matrices/${uuid})$`);
const rrmPost = new RegExp(`^(requirements|rrm/configs|roles/${uuid}/matrices|matrices/${uuid}/(submit|approve|reject|issues)|issues/${uuid}/resolve)$`);
const rrmPatch = new RegExp(`^matrices/${uuid}$`);
const employeePath = /^employees$/;
const generationPreflightGet = new RegExp(`^generation-runs/preflight/${uuid}$`);
const generationDetailGet = new RegExp(`^generation-runs/${uuid}$`);
const generationCreatePost = /^generation-runs$/;
const rrmRequestLimit = 512 * 1024;
const configuredFileLimit = Number(process.env.MAX_UPLOAD_BYTES ?? 15728640);
const fileLimit = Number.isSafeInteger(configuredFileLimit) && configuredFileLimit > 0
  ? Math.min(configuredFileLimit, 100 * 1024 * 1024) : 15728640;
const requestLimit = fileLimit + 1024 * 1024;

async function forward(request: NextRequest, segments: string[], method: "GET" | "POST" | "PATCH") {
  const path = segments.join("/");
  const isRrm = (method === "GET" ? rrmGet : method === "POST" ? rrmPost : rrmPatch).test(path);
  const isFoundationPost = method === "POST" && /^(departments|roles)$/.test(path);
  const isEmployee = method !== "PATCH" && employeePath.test(path);
  const isGenerationPreflight = method === "GET" && generationPreflightGet.test(path);
  const isGenerationDetail = method === "GET" && generationDetailGet.test(path);
  const isGenerationCreate = method === "POST" && generationCreatePost.test(path);
  const isDocument = method === "GET" ? allowedGet.test(path) : method === "POST" && allowedPost.test(path);
  if (!isDocument && !isRrm && !isFoundationPost && !isEmployee && !isGenerationPreflight && !isGenerationDetail && !isGenerationCreate) {
    return NextResponse.json({ code: "NOT_FOUND" }, { status: 404 });
  }
  if (method !== "GET") {
    const origin = request.headers.get("origin");
    if (origin && origin !== request.nextUrl.origin) {
      return NextResponse.json({ code: "FORBIDDEN_ORIGIN" }, { status: 403 });
    }
  }
  const supabase = await createClient();
  const { data: { session } } = await supabase.auth.getSession();
  if (!session) return NextResponse.json({ code: "AUTH_REQUIRED" }, { status: 401 });
  const url = `${apiBaseUrl()}/api/v1/${path}${method === "GET" ? request.nextUrl.search : ""}`;
  const contentType = request.headers.get("content-type");
  const declaredLength = Number(request.headers.get("content-length") ?? 0);
  const maxLength = isRrm || isFoundationPost || isEmployee || isGenerationCreate ? rrmRequestLimit : requestLimit;
  if (method !== "GET" && (isRrm || isFoundationPost || isEmployee || isGenerationCreate) && contentType?.split(";")[0] !== "application/json") {
    return NextResponse.json({ code: "INVALID_CONTENT_TYPE" }, { status: 415 });
  }
  if (method !== "GET" && declaredLength > maxLength) {
    return NextResponse.json({ code: "REQUEST_TOO_LARGE" }, { status: 413 });
  }
  let exceeded = false;
  let bytes = 0;
  const body = method !== "GET" && request.body ? request.body.pipeThrough(new TransformStream<Uint8Array, Uint8Array>({
    transform(chunk, controller) {
      bytes += chunk.byteLength;
      if (bytes > maxLength) {
        exceeded = true;
        controller.error(new Error("REQUEST_TOO_LARGE"));
      } else controller.enqueue(chunk);
    },
  })) : undefined;
  let response: Response;
  try {
    response = await fetch(url, {
    method,
    headers: {
      Authorization: `Bearer ${session.access_token}`,
      ...(contentType && method !== "GET" ? { "Content-Type": contentType } : {}),
      ...(isGenerationCreate && request.headers.get("idempotency-key")
        ? { "Idempotency-Key": request.headers.get("idempotency-key")! } : {}),
    },
    body,
    duplex: "half",
    cache: "no-store",
    } as RequestInit & { duplex: "half" });
  } catch {
    return NextResponse.json({ code: exceeded ? "REQUEST_TOO_LARGE" : "DOCUMENT_SERVICE_UNAVAILABLE" },
      { status: exceeded ? 413 : 503 });
  }
  const payload = await response.arrayBuffer();
  return new NextResponse(payload, {
    status: response.status,
    headers: {
      "Content-Type": response.headers.get("content-type") ?? "application/json",
      ...(response.headers.get("content-disposition")
        ? { "Content-Disposition": response.headers.get("content-disposition")! } : {}),
    },
  });
}

export async function GET(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params;
  return forward(request, path, "GET");
}

export async function POST(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params;
  return forward(request, path, "POST");
}

export async function PATCH(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params;
  return forward(request, path, "PATCH");
}
