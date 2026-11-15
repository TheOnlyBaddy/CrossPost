import type { Health, MetaPage, Platform, Post, User } from "./types";

export class ApiError extends Error {
  problems: string[];

  constructor(message: string, problems: string[] = []) {
    super(message);
    this.problems = problems;
  }
}

async function unwrap<T>(resp: Response): Promise<T> {
  if (resp.ok) return (await resp.json()) as T;

  let problems: string[] = [];
  let message = `Request failed (${resp.status})`;
  try {
    const body = await resp.json();
    const detail = body?.detail;
    if (Array.isArray(detail?.problems)) {
      problems = detail.problems;
      message = problems.join(" ");
    } else if (typeof detail === "string") {
      message = detail;
    }
  } catch {
    // non-JSON error body; keep the generic message
  }
  throw new ApiError(message, problems);
}

export async function signUp(email: string, password: string): Promise<User> {
  return unwrap<User>(
    await fetch("/api/users", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    }),
  );
}

export async function logIn(email: string, password: string): Promise<User> {
  return unwrap<User>(
    await fetch("/api/session", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    }),
  );
}

export async function logOut(): Promise<void> {
  await fetch("/api/session", { method: "DELETE" });
}

export async function getHealth(): Promise<Health> {
  return unwrap<Health>(await fetch("/api/health"));
}

export async function listPosts(): Promise<Post[]> {
  const body = await unwrap<{ posts: Post[] }>(await fetch("/api/posts"));
  return body.posts;
}

export async function retryTarget(
  postId: string,
  platform: Platform,
): Promise<void> {
  await unwrap(
    await fetch(`/api/posts/${postId}/retry/${platform}`, { method: "POST" }),
  );
}

export async function getMetaPages(): Promise<MetaPage[]> {
  const body = await unwrap<{ pages: MetaPage[] }>(
    await fetch("/api/auth/meta/pages"),
  );
  return body.pages;
}

export async function selectMetaPage(
  pageId: string,
): Promise<{ warning: string | null }> {
  return unwrap(
    await fetch(`/api/auth/meta/select-page?pageId=${encodeURIComponent(pageId)}`, {
      method: "POST",
    }),
  );
}

export async function disconnect(platform: Platform): Promise<void> {
  await unwrap(await fetch(`/api/auth/${platform}`, { method: "DELETE" }));
}

export async function cancelPost(postId: string): Promise<void> {
  await unwrap(await fetch(`/api/posts/${postId}/cancel`, { method: "POST" }));
}

export async function reschedulePost(
  postId: string,
  scheduledAt: string,
): Promise<void> {
  const form = new FormData();
  form.append("scheduledAt", scheduledAt);
  await unwrap(
    await fetch(`/api/posts/${postId}/reschedule`, {
      method: "POST",
      body: form,
    }),
  );
}

/**
 * Uses XHR rather than fetch so the upload can report progress — fetch has no
 * upload progress event.
 */
export function createPost(
  input: {
    file: File;
    title: string;
    caption: string;
    targets: Platform[];
    /** UTC ISO instant, or "" to publish now. */
    scheduledAt: string;
  },
  onProgress: (fraction: number) => void,
): Promise<Post> {
  const form = new FormData();
  form.append("file", input.file);
  form.append("title", input.title);
  form.append("caption", input.caption);
  form.append("targets", input.targets.join(","));
  form.append("scheduledAt", input.scheduledAt);

  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/posts");

    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress(event.loaded / event.total);
    };

    xhr.onload = () => {
      let body: unknown;
      try {
        body = JSON.parse(xhr.responseText);
      } catch {
        reject(new ApiError(`Upload failed (${xhr.status})`));
        return;
      }

      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(body as Post);
        return;
      }

      const detail = (body as { detail?: unknown })?.detail;
      const problems =
        detail && typeof detail === "object" && "problems" in detail
          ? ((detail as { problems: string[] }).problems ?? [])
          : [];
      reject(
        new ApiError(
          problems.length
            ? problems.join(" ")
            : typeof detail === "string"
              ? detail
              : `Upload failed (${xhr.status})`,
          problems,
        ),
      );
    };

    xhr.onerror = () => reject(new ApiError("Network error during upload"));
    xhr.send(form);
  });
}
