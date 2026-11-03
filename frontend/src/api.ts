let token = '';
export async function api<T = any>(path: string, body?: unknown, method?: string): Promise<T> {
  if (!token) { const session = await fetch('/api/v1/session', {credentials:'same-origin'}); if (!session.ok) throw new Error('无法连接本机评测服务'); token = (await session.json()).csrf_token; }
  const response = await fetch(`/api/v1${path}`, {method:method || (body === undefined ? 'GET':'POST'),credentials:'same-origin',headers:{'Content-Type':body instanceof Blob?'application/zip':'application/json','X-CSRF-Token':token},body:body === undefined ? undefined:body instanceof Blob?body:JSON.stringify(body)});
  if (!response.ok) { let error:any; try { error=await response.json(); } catch { throw new Error(`请求失败 (${response.status})`); } throw new Error(error.message || error.detail?.message || (typeof error.detail === 'string'?error.detail:JSON.stringify(error.detail || error))); }
  return response.json();
}
export const op = () => crypto.randomUUID();
