// JSON calls to the review server. A non-2xx response throws an Error whose
// message is the server's safe error text.

async function call(url, options = {}) {
  const resp = await fetch(url, options);
  const body = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(body.error || `${resp.status} ${resp.statusText}`);
  return body;
}

export const getJSON = (url) => call(url);

export const postJSON = (url, body) =>
  call(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body ?? {}) });
