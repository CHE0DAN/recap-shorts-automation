/** 서버가 오류로 답한 것. detail 이 객체이면(예: 409 중복 글 {code, message, jobs}) code 와 본문을 들고 있다. */
export class ApiError extends Error {
  status: number;
  code?: string;
  detail?: Record<string, unknown>;
  constructor(message: string, status: number, detail?: Record<string, unknown>) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
    this.code = typeof detail?.code === "string" ? detail.code : undefined;
  }
}
