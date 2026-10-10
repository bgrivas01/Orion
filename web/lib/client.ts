import { createClient } from "@orion/shared";

/** Point this at the FastAPI server. Override per-machine in .env.local. */
export const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

export const api = createClient(API_BASE);
