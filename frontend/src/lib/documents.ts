import { ApiFailure, refreshOnce, request, type ApiError } from "@/lib/api";

export type Category =
  "lab_report" | "scan" | "prescription" | "referral" | "discharge" | "insurance" | "other";

export type PatientDocument = {
  id: string;
  patient_id: string;
  category: Category;
  title: string;
  dated: string | null;
  original_name: string;
  content_type: "application/pdf" | "image/jpeg" | "image/png" | "image/webp";
  size_bytes: number;
  uploaded_at: string;
  uploaded_by: string | null;
  consultation_id: string | null;
  visit_date: string | null;
  lab_order_id: string | null;
  lab_order_number: string | null;
  lab_test_name: string | null;
  can_change: boolean;
};

export type DocumentPage = {
  items: PatientDocument[];
  total: number;
  counts: Partial<Record<Category, number>>;
};

export const CATEGORIES: Category[] = [
  "lab_report",
  "scan",
  "prescription",
  "referral",
  "discharge",
  "insurance",
  "other",
];

export const CATEGORY_WORDS: Record<Category, string> = {
  lab_report: "Lab report",
  scan: "Scan, X-ray or ECG",
  prescription: "Prescription",
  referral: "Referral letter",
  discharge: "Discharge summary",
  insurance: "Insurance or ID",
  other: "Other",
};

/** Matches the server. Vercel turns away anything much bigger before the API sees it. */
export const MAX_BYTES = 4 * 1024 * 1024;

export const listDocuments = (
  patientId: string,
  filters: {
    category?: Category;
    visit?: string;
    labOrder?: string;
    limit?: number;
    offset?: number;
  } = {},
) => {
  const params = new URLSearchParams();
  if (filters.category) params.set("category", filters.category);
  if (filters.visit) params.set("consultation_id", filters.visit);
  if (filters.labOrder) params.set("lab_order_id", filters.labOrder);
  if (filters.limit) params.set("limit", String(filters.limit));
  if (filters.offset) params.set("offset", String(filters.offset));
  const query = params.toString();
  return request<DocumentPage>(`/patients/${patientId}/documents${query ? `?${query}` : ""}`);
};

export const getDocument = (id: string) => request<PatientDocument>(`/documents/${id}`);

export const changeDocument = (
  id: string,
  changes: {
    title?: string;
    category?: Category;
    dated?: string | null;
    lab_order_id?: string | null;
  },
) =>
  request<PatientDocument>(`/documents/${id}`, {
    method: "PATCH",
    body: JSON.stringify(changes),
  });

export const removeDocument = (id: string) =>
  request<{ removed: boolean }>(`/documents/${id}`, { method: "DELETE" });

/** Where the browser fetches the file itself, on the session cookie. */
export const fileHref = (id: string, download = false) =>
  `/api/v1/documents/${id}/file${download ? "?download=true" : ""}`;

export type UploadDetails = {
  category: Category;
  title?: string;
  dated?: string;
  visit?: string;
  labOrder?: string;
};

function sendOnce(
  patientId: string,
  file: Blob,
  name: string,
  details: UploadDetails,
  onProgress: (fraction: number) => void,
  signal?: AbortSignal,
): Promise<{ status: number; body: string }> {
  const params = new URLSearchParams({ name, category: details.category });
  if (details.title?.trim()) params.set("title", details.title.trim());
  if (details.dated) params.set("dated", details.dated);
  if (details.visit) params.set("consultation_id", details.visit);
  if (details.labOrder) params.set("lab_order_id", details.labOrder);

  // XMLHttpRequest rather than fetch, which still cannot say how much of a
  // request body has gone.
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `/api/v1/patients/${patientId}/documents?${params}`);
    xhr.withCredentials = true;
    xhr.setRequestHeader("Content-Type", file.type || "application/octet-stream");
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress(event.loaded / event.total);
    };
    xhr.onload = () => resolve({ status: xhr.status, body: xhr.responseText });
    xhr.onerror = () =>
      reject(
        new ApiFailure(0, {
          code: "NETWORK_UNREACHABLE",
          message: "The connection dropped before the file went. Try again.",
        }),
      );
    xhr.onabort = () => reject(new DOMException("Stopped", "AbortError"));
    signal?.addEventListener("abort", () => xhr.abort(), { once: true });
    xhr.send(file);
  });
}

function failureFrom(status: number, body: string): ApiFailure {
  try {
    const parsed = JSON.parse(body) as { error?: ApiError };
    if (parsed.error) return new ApiFailure(status, parsed.error);
  } catch {
    // Not the API answering: a proxy or the platform in front of it.
  }
  if (status === 413) {
    return new ApiFailure(status, {
      code: "FILE_TOO_LARGE",
      message: "That file is larger than 4 MB.",
    });
  }
  return new ApiFailure(status, {
    code: "SERVICE_UNAVAILABLE",
    message: "The file could not be added just now. Try again in a moment.",
  });
}

/** Sends one file, signing in again once if the session ran out on the way. */
export async function uploadDocument(
  patientId: string,
  file: Blob,
  name: string,
  details: UploadDetails,
  onProgress: (fraction: number) => void,
  signal?: AbortSignal,
): Promise<PatientDocument> {
  let answer = await sendOnce(patientId, file, name, details, onProgress, signal);
  if (answer.status === 401 && (await refreshOnce())) {
    onProgress(0);
    answer = await sendOnce(patientId, file, name, details, onProgress, signal);
  }
  if (answer.status >= 200 && answer.status < 300) {
    return (JSON.parse(answer.body) as { data: PatientDocument }).data;
  }
  throw failureFrom(answer.status, answer.body);
}

export function readableSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} bytes`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function isImage(type: string): boolean {
  return type.startsWith("image/");
}

const PHOTO_TYPES = ["image/jpeg", "image/png", "image/webp"];
const PHOTO_EXTENSIONS = ["jpg", "jpeg", "jfif", "png", "webp"];

function extensionOf(name: string): string {
  const dot = name.lastIndexOf(".");
  return dot > 0 ? name.slice(dot + 1).toLowerCase() : "";
}

export type Prepared = { blob: Blob; name: string; shrunk: boolean };

// A phone photo of a report is legible well below this, and a lot smaller.
const LONGEST_SIDE = 2400;
const WORTH_SHRINKING = 1.5 * 1024 * 1024;

async function shrink(file: File): Promise<Blob | null> {
  try {
    // Turned the right way up from the camera's own note of how it was held.
    const bitmap = await createImageBitmap(file, { imageOrientation: "from-image" });
    const scale = Math.min(1, LONGEST_SIDE / Math.max(bitmap.width, bitmap.height));
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(bitmap.width * scale);
    canvas.height = Math.round(bitmap.height * scale);
    const context = canvas.getContext("2d");
    if (!context) return null;
    // White under a transparent PNG, or it turns black as a JPEG.
    context.fillStyle = "#ffffff";
    context.fillRect(0, 0, canvas.width, canvas.height);
    context.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
    bitmap.close();
    return await new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", 0.85));
  } catch {
    return null;
  }
}

/**
 * The file as it will be sent, or why it cannot be. A large photo is made
 * smaller here, which is also what keeps it under the limit; a PDF cannot be,
 * so one that is too large is refused with what to do instead.
 */
export async function prepare(file: File): Promise<Prepared> {
  const extension = extensionOf(file.name);
  if (file.size === 0) throw new Error("This file is empty.");
  if (["heic", "heif"].includes(extension) || /image\/hei[cf]/.test(file.type)) {
    throw new Error(
      "iPhone photos in HEIC cannot be shown here. Share it as a JPEG, or take a screenshot of it, and add that.",
    );
  }

  const isPdf = file.type === "application/pdf" || extension === "pdf";
  const isPhoto = PHOTO_TYPES.includes(file.type) || PHOTO_EXTENSIONS.includes(extension);
  if (!isPdf && !isPhoto) {
    throw new Error("Only PDFs and photos (JPEG, PNG or WebP) can be added.");
  }

  if (isPhoto && file.size > WORTH_SHRINKING) {
    const smaller = await shrink(file);
    if (smaller && smaller.size < file.size) {
      if (smaller.size > MAX_BYTES) {
        throw new Error(`Even made smaller this photo is ${readableSize(smaller.size)}.`);
      }
      const stem = file.name.replace(/\.[^.]+$/, "") || "photo";
      return { blob: smaller, name: `${stem}.jpg`, shrunk: true };
    }
  }

  if (file.size > MAX_BYTES) {
    throw new Error(
      isPdf
        ? `This PDF is ${readableSize(file.size)}, and files can be up to 4 MB. Ask the lab for a smaller copy, or photograph the pages instead.`
        : `This photo is ${readableSize(file.size)}, and files can be up to 4 MB.`,
    );
  }
  return { blob: file, name: file.name, shrunk: false };
}

/** The file's name without its extension, as a starting title. */
export function titleFrom(name: string): string {
  const stem = name.replace(/\.[^.]+$/, "");
  return (stem || name).replace(/_/g, " ").replace(/\s+/g, " ").trim().slice(0, 120);
}
